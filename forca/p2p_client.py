"""Orquestra tudo: registro, tarefas periódicas, encerramento limpo.

Dono: Pessoa A (ciclo de vida) com Pessoa C (ligação dos handlers). Issue 01.7.
Logger: "Client".

O P2PClient cria todos os objetos e os expõe como atributos (a CLI da C usa
`client.table`, `client.host`, `client.player`...). A parte de rede é ligada
aqui; a parte do jogo é ligada pela função `wire(client)` que a Pessoa C passa
no construtor (ver CONTRATO.md, seção 5.9).

Especificação, "Componentes de um peer": tarefas periódicas = DISCOVER a cada
N s (reconcilia a PeerTable e conecta nos novos) e refresh do registro antes
do TTL expirar. O Rendezvous bloqueia o IP por 1 min acima de 50 req/min, por
isso NENHUM laço aqui roda sem `await asyncio.sleep(...)`, nem quando dá erro.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import replace
from typing import Callable

from .config import Config
from .game_host import GameHost
from .game_player import GamePlayer
from .keep_alive import KeepAlive
from .message_router import MessageRouter
from .peer_connection import PeerConnection, PeerServer
from .peer_table import PeerTable
from .rendezvous_connection import RendezvousConnection, RendezvousError

log = logging.getLogger("Client")

MANUAL_RECONNECT_MIN_INTERVAL = 5.0  # /reconnect não pode estourar o limite do Rendezvous

Wire = Callable[["P2PClient"], None]


class P2PClient:
    def __init__(self, cfg: Config, wire: Wire | None = None) -> None:
        self.cfg = cfg
        self._wire = wire
        # --- rede (A) ---
        self.rdv = RendezvousConnection(cfg)
        self.keep_alive = KeepAlive(cfg)
        self.router = MessageRouter(cfg.peer_id)
        self.server = PeerServer(cfg, self.router.on_message, self._on_closed, self._on_connected)
        self.server.on_pong = self.keep_alive.on_pong
        self.table = PeerTable(cfg, self.server.connect)
        # --- jogo (B): falam com a rede só pelo Sender (table.send_to) ---
        self.host = GameHost(cfg, self.table.send_to, busy=lambda: self.player.active)
        self.player = GamePlayer(cfg, self.table.send_to, busy=lambda: self.host.active)

        self._registered = False
        self._started = False
        self._tasks: list[asyncio.Task] = []  # tarefas periódicas, canceladas no stop()
        self._stop_task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self._last_manual = float("-inf")

    # --- ligações de rede ----------------------------------------------------

    async def _on_connected(self, conn: PeerConnection) -> None:
        """Conexão pronta: começa a vigiar (PING) e avisa a PeerTable."""
        self.keep_alive.watch(conn)
        await self.table.attach(conn)

    async def _on_closed(self, conn: PeerConnection) -> None:
        await self.table.detach(conn)

    # --- início -------------------------------------------------------------

    async def start(self) -> None:
        """Ordem: ligar o jogo (wire) -> PeerServer.start -> REGISTER -> tarefas.

        Falha ao escutar (porta ocupada) é fatal e propaga. Rendezvous fora do
        ar NÃO é: o peer sobe, avisa no log e o laço de DISCOVER tenta
        registrar de novo a cada intervalo.
        """
        if self._wire is not None:
            self._wire(self)  # handlers do jogo no router e eventos da table (C)
        await self.server.start()
        if self.cfg.listen_port == 0:  # porta efêmera (testes): registra a real
            self.cfg = replace(self.cfg, listen_port=self.server.port)
            self.rdv.cfg = self.cfg
        self._started = True
        await self._register()
        self._tasks = [
            asyncio.create_task(self._discover_loop(), name="discover loop"),
            asyncio.create_task(self._refresh_loop(), name="register refresh"),
        ]

    # --- Rendezvous -----------------------------------------------------------

    async def _register(self) -> bool:
        """REGISTER (serve também de refresh). Nunca levanta."""
        try:
            await self.rdv.register()
        except RendezvousError as exc:
            self._registered = False
            log.warning("REGISTER failed: %s", exc.message)
            return False
        self._registered = True
        return True

    async def _discover_once(self) -> bool:
        """Um DISCOVER + reconciliação. Nunca levanta; devolve se deu certo.

        `peer_not_registered` (o registro expirou): REGISTER de novo e repete
        o DISCOVER uma vez (contrato 6.9). Se o DISCOVER falhar por qualquer
        motivo, NÃO reconcilia: senão uma falha do servidor marcaria todos os
        vizinhos como GONE.
        """
        for attempt in (1, 2):
            if not self._registered and not await self._register():
                return False
            try:
                peers = await self.rdv.discover()
            except RendezvousError as exc:
                if exc.message == "peer_not_registered":
                    self._registered = False
                    if attempt == 1:
                        continue
                log.warning("DISCOVER failed: %s", exc.message)
                return False
            await self.table.reconcile(peers)
            return True
        return False

    async def _discover_loop(self) -> None:
        """DISCOVER a cada `discover_interval`. O `sleep` está FORA do try: roda
        a cada volta, mesmo com erro (o limite do Rendezvous é 50 req/min)."""
        while True:
            try:
                await self._discover_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("discover loop error")
            await asyncio.sleep(self.cfg.discover_interval)

    async def _refresh_loop(self) -> None:
        """Renova o registro na metade do TTL (especificação: antes de expirar)."""
        while True:
            await asyncio.sleep(self.cfg.register_ttl / 2)
            try:
                await self._register()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("refresh loop error")

    async def reconnect_now(self) -> bool:
        """`/reconnect`: DISCOVER + reconciliação imediatos e tentativa já dos
        peers STALE. No máximo uma vez a cada 5 s, para o usuário não conseguir
        estourar o limite do Rendezvous repetindo o comando."""
        now = asyncio.get_running_loop().time()
        if now - self._last_manual < MANUAL_RECONNECT_MIN_INTERVAL:
            log.info("reconnect ignored: wait %.0f s between requests",
                     MANUAL_RECONNECT_MIN_INTERVAL - (now - self._last_manual))
            return False
        self._last_manual = now
        ok = await self._discover_once()
        self.table.retry_now()
        return ok

    # --- encerramento -------------------------------------------------------

    async def stop(self) -> None:
        """Encerramento limpo; `/quit` e `Ctrl+C` chamam este mesmo método.

        Idempotente: chamadas simultâneas esperam o mesmo encerramento.
        """
        await asyncio.shield(self._ensure_stop_task())

    async def wait_stopped(self) -> None:
        """Espera o encerramento terminar (para o main.py)."""
        await self._stopped.wait()

    def _ensure_stop_task(self) -> asyncio.Task:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._shutdown(), name="shutdown")
        return self._stop_task

    async def _shutdown(self) -> None:
        """Ordem do contrato (seção 8), cada passo protegido: um erro não
        impede os seguintes (o programa precisa terminar)."""
        # 0. nada novo (DISCOVER, refresh) no meio do encerramento
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        # 1. host com partida: GAME_OVER ABORTED (host_shutdown) aos jogadores
        await self._step("host.shutdown", self.host.shutdown())
        # 2. jogador em partida: LEAVE ao host
        await self._step("player.leave", self.player.leave())
        # 3. BYE a todos os vizinhos (espera BYE_OK até 2 s, em paralelo)
        await self._step("table.close_all", self.table.close_all("shutdown"))
        # 4. UNREGISTER no Rendezvous
        if self._started:
            await self._step("rdv.unregister", self.rdv.unregister())
        # 5. tarefas de PING e servidor TCP
        await self._step("keep_alive.stop", self.keep_alive.stop())
        await self._step("server.stop", self.server.stop())
        log.info("stopped")
        self._stopped.set()

    @staticmethod
    async def _step(name: str, coro) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("shutdown step %s failed: %r", name, exc)

    def install_signal_handlers(self) -> None:
        """`Ctrl+C` (SIGINT) e SIGTERM disparam o mesmo `stop()` do `/quit`."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._on_signal, sig)
            except (NotImplementedError, RuntimeError):
                pass  # Windows ou fora da thread principal

    def _on_signal(self, sig: signal.Signals) -> None:
        log.info("received %s: shutting down", sig.name)
        self._ensure_stop_task()
