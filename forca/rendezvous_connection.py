"""Cliente do servidor Rendezvous: REGISTER / DISCOVER / UNREGISTER.

Dono: Pessoa A. Issue 01.1. Logger: "RDV".

Especificação, "Protocolo Peer–Rendezvous":
- cada conexão TCP aceita EXATAMENTE UM comando (uma linha JSON terminada em
  \\n) e o servidor fecha depois de responder: abrimos uma conexão nova por
  comando;
- a resposta tem `status` "OK" ou "ERROR" (com `message`);
- o servidor bloqueia o IP por 1 min acima de 50 req/min. Esta classe não tem
  laço nenhum: quem chama periodicamente (01.7) é que dá o intervalo.

O Rendezvous NÃO usa o envelope peer–peer (sem msg_id, e aqui `ttl` é o tempo
de vida do registro em segundos, não o ttl=1 das mensagens entre peers). Por
isso os pedidos são dicionários simples; de `protocol` só reaproveitamos o
`encode`/`decode` (uma linha JSON UTF-8, limite de 32 KiB).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from . import protocol
from .config import Config

log = logging.getLogger("RDV")

DEFAULT_TIMEOUT = 5.0  # segundos para conectar e, depois, para ler a resposta
LOCAL: Any = object()  # "o namespace local" (diferente de None, que significa "todos")


class RendezvousError(Exception):
    """Falha de um comando no Rendezvous.

    `message` traz o código do servidor quando `status == "ERROR"` (ex.:
    "bad_port", "peer_not_registered" ou o texto do bloqueio por excesso de
    requisições). Falhas de rede usam códigos nossos: "timeout",
    "connection_failed" e "bad_response". Assim quem chama trata um tipo só.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RendezvousConnection:
    def __init__(self, cfg: Config, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.cfg = cfg
        self.timeout = timeout
        self.public_ip: str | None = None  # preenchido pelo REGISTER

    # --- comandos -----------------------------------------------------------

    async def register(self) -> dict:
        """REGISTER (também serve de refresh do TTL).

        Guarda o `ip` observado pelo servidor em `self.public_ip` (é a única
        forma de o peer saber o próprio IP público) e registra no log
        '[RDV] registered alice@CIC as IP:PORT (ttl=7200)'.
        """
        resp = await self._command(
            {
                "type": "REGISTER",
                "namespace": self.cfg.namespace,
                "name": self.cfg.name,
                "port": self.cfg.listen_port,
                "ttl": self.cfg.register_ttl,
            }
        )
        ip = resp.get("ip")
        if not isinstance(ip, str):
            raise RendezvousError("bad_response")
        first_time = self.public_ip != ip
        self.public_ip = ip
        log.info(
            "registered %s as %s:%s (ttl=%s)",
            self.cfg.peer_id, ip, resp.get("port"), resp.get("ttl"),
        )
        if first_time:
            # Atrás de NAT, este é o IP do roteador: conexões de entrada só
            # chegam se a porta estiver encaminhada (comportamento esperado).
            log.info(
                "public address %s:%s; inbound connections need this port "
                "reachable (port forwarding if behind NAT)",
                ip, self.cfg.listen_port,
            )
        return resp

    async def discover(self, namespace: str | None = LOCAL) -> list[dict]:
        """DISCOVER no namespace dado. Padrão: o namespace local. `None` OMITE o
        campo `namespace` do pedido, e o servidor devolve os peers de TODOS os
        namespaces (especificação, DISCOVER; é o que o `/peers *` usa).

        A resposta do servidor inclui o próprio peer; ele é removido aqui
        (filtro por name + namespace). Cada item: ip, port, name, namespace,
        ttl, expires_in.
        """
        ns = self.cfg.namespace if namespace is LOCAL else namespace
        request: dict = {"type": "DISCOVER"}
        if ns is not None:
            request["namespace"] = ns
        resp = await self._command(request)
        peers = resp.get("peers")
        if not isinstance(peers, list):
            raise RendezvousError("bad_response")
        others = [
            p
            for p in peers
            if isinstance(p, dict)
            and not (
                p.get("name") == self.cfg.name
                and p.get("namespace") == self.cfg.namespace
            )
        ]
        log.debug("discovered %d peer(s) besides me", len(others))
        return others

    async def unregister(self) -> None:
        """UNREGISTER com namespace, name e port (devem bater com o registro)."""
        await self._command(
            {
                "type": "UNREGISTER",
                "namespace": self.cfg.namespace,
                "name": self.cfg.name,
                "port": self.cfg.listen_port,
            }
        )
        log.info("unregistered %s", self.cfg.peer_id)

    # --- transporte ---------------------------------------------------------

    async def _command(self, request: dict) -> dict:
        """Abre uma conexão, envia UMA linha, lê UMA linha e fecha.

        Devolve a resposta se `status == "OK"`; senão levanta RendezvousError.
        Conectar e ler têm timeout próprio: nada fica pendurado.
        """
        host, port = self.cfg.rdv_host, self.cfg.rdv_port
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), self.timeout
            )
        except asyncio.TimeoutError:
            log.warning("%s: timeout connecting to %s:%s", request["type"], host, port)
            raise RendezvousError("timeout") from None
        except OSError as exc:
            log.warning("%s: cannot connect to %s:%s (%s)", request["type"], host, port, exc)
            raise RendezvousError("connection_failed") from exc

        try:
            try:
                line = protocol.encode(request)
            except protocol.ProtocolError:
                # name/namespace gigantes: nem chega ao servidor (a especificação limita a 64)
                raise RendezvousError("request_too_large") from None
            log.debug("-> %s", line.decode("utf-8").rstrip())
            writer.write(line)
            await writer.drain()
            raw = await asyncio.wait_for(reader.readline(), self.timeout)
        except asyncio.TimeoutError:
            log.warning("%s: no response within %.0f s", request["type"], self.timeout)
            raise RendezvousError("timeout") from None
        except (OSError, ValueError) as exc:
            # ValueError: StreamReader estoura o limite de linha
            log.warning("%s: connection error (%s)", request["type"], exc)
            raise RendezvousError("connection_failed") from exc
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

        if not raw:
            log.warning("%s: server closed without answering", request["type"])
            raise RendezvousError("bad_response")
        log.debug("<- %s", raw.decode("utf-8", errors="replace").rstrip())

        try:
            resp = protocol.decode(raw)
        except protocol.ProtocolError:
            raise RendezvousError("bad_response") from None

        if resp.get("status") == "OK":
            return resp
        message = str(resp.get("message", "unknown error"))
        log.warning("%s failed: %s", request["type"], message)
        raise RendezvousError(message)
