"""PING/PONG periódico, RTT e detecção de STALE.

Dono: Pessoa A. Issue 01.5. Logger: "KeepAlive".

Especificação, "PING / PONG":
- PING enviado por AMBOS os lados de cada conexão a cada `ping_interval` s;
- RTT = recepção do PONG − envio do PING correspondente (casado por msg_id),
  média móvel dos últimos 10;
- após 3 PINGs consecutivos sem PONG, o peer é marcado STALE e a conexão é
  fechada (o fechamento chega à PeerTable, que emite `peer_stale`).

Quem responde o PING com PONG é a própria PeerConnection; aqui só se envia o
PING e se trata o PONG (ligado em `PeerServer.on_pong`).
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from . import protocol
from .config import Config
from .models import PeerState

if TYPE_CHECKING:
    from .peer_connection import PeerConnection

log = logging.getLogger("KeepAlive")

RTT_WINDOW = 10  # média móvel dos últimos 10 PING/PONG


@dataclass
class _Watch:
    """O que o KeepAlive guarda de cada conexão vigiada."""

    task: asyncio.Task | None = None
    pending: dict[str, float] = field(default_factory=dict)  # msg_id -> envio (loop.time())
    samples: deque = field(default_factory=lambda: deque(maxlen=RTT_WINDOW))  # RTTs em ms


class KeepAlive:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._watches: dict["PeerConnection", _Watch] = {}

    def watch(self, conn: "PeerConnection") -> None:
        """Começa a enviar PING a cada cfg.ping_interval nesta conexão.

        Chamar de novo para a mesma conexão não cria outra tarefa.
        """
        if conn in self._watches or conn.closed:
            return
        w = _Watch()
        self._watches[conn] = w
        w.task = asyncio.create_task(self._ping_loop(conn, w), name=f"ping {conn.label}")

    def unwatch(self, conn: "PeerConnection") -> None:
        """Para de vigiar a conexão (cancela a tarefa de PING)."""
        w = self._watches.pop(conn, None)
        if w is not None and w.task is not None:
            w.task.cancel()

    async def stop(self) -> None:
        """Cancela todas as tarefas de PING e espera terminarem."""
        tasks = [w.task for w in self._watches.values() if w.task is not None]
        self._watches.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def on_pong(self, conn: "PeerConnection", msg: dict) -> None:
        """RTT = agora − envio do PING casado pelo msg_id. Zera os PINGs perdidos."""
        w = self._watches.get(conn)
        if w is None:
            return
        sent = w.pending.pop(msg.get("msg_id"), None)
        if sent is None:
            log.debug("%s: PONG for unknown PING %s ignored", conn.label, msg.get("msg_id"))
            return
        rtt = (asyncio.get_running_loop().time() - sent) * 1000
        w.samples.append(rtt)
        conn.rtt_ms = sum(w.samples) / len(w.samples)
        # qualquer PONG prova que o par está vivo: os PINGs enviados antes
        # deste deixam de contar (um PING mais novo, ainda no ar, continua)
        conn.missed_pings = 0
        w.pending = {mid: t for mid, t in w.pending.items() if t > sent}
        log.info("%s RTT=%.1f ms (avg %.1f ms)", conn.peer_id, rtt, conn.rtt_ms)

    async def _ping_loop(self, conn: "PeerConnection", w: _Watch) -> None:
        """Um PING por intervalo. O 1º sai na hora (RTT disponível cedo)."""
        loop = asyncio.get_running_loop()
        limit = self.cfg.ping_miss_limit
        try:
            while not conn.closed:
                if w.pending:  # o PING anterior ficou sem PONG
                    conn.missed_pings += 1
                    if conn.missed_pings >= limit:
                        log.warning("%s missed %d PINGs — marking STALE", conn.peer_id, limit)
                        conn.state = PeerState.STALE
                        await conn.close("idle", wait_ack=False)
                        return
                ping = protocol.new_message("PING", timestamp=protocol.now_iso(millis=True))
                w.pending[ping["msg_id"]] = loop.time()
                if not await conn.send(ping):
                    return  # a conexão já caiu
                await asyncio.sleep(self.cfg.ping_interval)
        finally:
            # a tarefa termina sozinha quando a conexão fecha: sai do registro
            if self._watches.get(conn) is w:
                del self._watches[conn]
