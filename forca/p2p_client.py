"""Orquestra tudo: registro, tarefas periódicas, encerramento limpo.

Dono: Pessoa A (ciclo de vida) com Pessoa C (ligação dos handlers). Issue 01.7.
Logger: "Client".

O P2PClient cria todos os objetos e os expõe como atributos (a CLI da C usa
`client.table`, `client.host`, `client.player`...). A parte de rede é ligada
aqui; a ligação do jogo ao roteador e à tabela é `game_wiring.wire_game`, da
Pessoa C (ver CONTRATO.md, seção 5.9). Sinais (Ctrl+C) são tratados pelo
`main.py`, que chama `client.stop()`.

Especificação, "Componentes de um peer": tarefas periódicas = DISCOVER a cada
N s (reconcilia a PeerTable e conecta nos novos) e refresh do registro antes
do TTL expirar. O Rendezvous bloqueia o IP por 1 min acima de 50 req/min, por
isso NENHUM laço aqui roda sem `await asyncio.sleep(...)`, nem quando dá erro.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from .config import Config
from .game_wiring import wire_game
from .keep_alive import KeepAlive
from .message_router import MessageRouter
from .peer_connection import PeerConnection, PeerServer
from .peer_table import PeerTable
from .rendezvous_connection import RendezvousConnection, RendezvousError

log = logging.getLogger("Client")

MANUAL_RECONNECT_MIN_INTERVAL = 5.0  # /reconnect não pode estourar o limite do Rendezvous


class P2PClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        # Tudo é criado aqui (e não no start()) para o stop() ser seguro mesmo
        # que o start() falhe ou seja cancelado no meio.
        self.rdv = RendezvousConnection(cfg)
        self.keep_alive = KeepAlive(cfg)
        self.table = PeerTable(cfg, self._connect)
        self.router = MessageRouter(cfg.peer_id, self.table.send_to)
        # jogo (B) ligado ao roteador e à tabela pela função da C
        self.host, self.player = wire_game(cfg, self.table, self.router)
        self.server = PeerServer(cfg, self.router.on_message, self._on_closed, self._on_connected)
        self.server.on_pong = self.keep_alive.on_pong
        self.server.on_bad_line = self.router.on_bad_line

        self._registered = False
        self._tasks: list[asyncio.Task] = []  # tarefas periódicas, canceladas no stop()
        self._stop_task: asyncio.Task | None = None
        self._last_manual = float("-inf")

    # --- ligações de rede ----------------------------------------------------

    async def _connect(self, ip: str, port: int) -> PeerConnection | None:
        """`connect_fn` da PeerTable (o servidor é criado depois da tabela)."""
        return await self.server.connect(ip, port)

    async def _on_connected(self, conn: PeerConnection) -> None:
        """Conexão pronta: começa a vigiar (PING) e avisa a PeerTable."""
        self.keep_alive.watch(conn)
        await self.table.attach(conn)

    async def _on_closed(self, conn: PeerConnection) -> None:
        await self.table.detach(conn)

    # --- início -------------------------------------------------------------

    async def start(self) -> None:
        """Ordem: PeerServer.start -> REGISTER -> tarefas periódicas.

        Falha ao escutar (porta ocupada) é fatal e propaga. Rendezvous fora do
        ar NÃO é: o peer sobe, avisa no log e o laço de DISCOVER tenta
        registrar de novo a cada intervalo. Nenhum `except` aqui engole o
        CancelledError (o main cancela o start() no primeiro Ctrl+C).
        """
        await self.server.start()
        if self.cfg.listen_port == 0:  # porta efêmera (testes): registra a real
            self.cfg = replace(self.cfg, listen_port=self.server.port)
            self.rdv.cfg = self.cfg
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

    async def reconcile_now(self) -> bool:
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
        # 4. UNREGISTER no Rendezvous (só se estamos registrados: com o servidor
        #    fora do ar ou travado não há o que remover, e o Ctrl+C não espera)
        if self._registered:
            await self._step("rdv.unregister", self.rdv.unregister())
        # 5. tarefas de PING e servidor TCP
        await self._step("keep_alive.stop", self.keep_alive.stop())
        await self._step("server.stop", self.server.stop())
        log.info("stopped")

    @staticmethod
    async def _step(name: str, coro) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("shutdown step %s failed: %r", name, exc)
