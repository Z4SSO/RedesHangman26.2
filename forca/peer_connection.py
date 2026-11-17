"""Servidor e cliente TCP entre peers, framing JSON-por-linha, HELLO, duplicadas.

Dono: Pessoa A. Issues 01.3 (transporte) e 01.4 (HELLO, BYE, duplicadas).
Logger: "PeerServer" (e "Wire" para o JSON bruto em DEBUG, setas -> e <-).

Especificação, "Transporte e Codificação":
- TCP, JSON UTF-8, um objeto por linha terminado em \\n, no máximo 32 KiB;
- linha que não é JSON válido: responde ERROR (bad_json) e fecha a conexão;
- erro de leitura/escrita: conexão fechada imediatamente.

Esta camada resolve sozinha HELLO/HELLO_OK, PING/PONG (via KeepAlive) e
BYE/BYE_OK. Todo o resto sobe para o MessageRouter por `on_message`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from . import protocol
from .config import Config
from .models import PeerState

log = logging.getLogger("PeerServer")
wire = logging.getLogger("Wire")

OnMessage = Callable[["PeerConnection", dict], Awaitable[None]]
OnClosed = Callable[["PeerConnection"], Awaitable[None]]
OnConnected = Callable[["PeerConnection"], Awaitable[None]]

CONNECT_TIMEOUT = 5.0  # abrir o socket de saída
CLOSE_TIMEOUT = 1.0  # esperar o socket terminar de fechar


class PeerConnection:
    """Uma conexão TCP com um vizinho (um socket).

    Criada pelo PeerServer, nunca diretamente pelos outros módulos.
    """

    def __init__(
        self,
        server: "PeerServer",
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        direction: str,
    ) -> None:
        self._server = server
        self._reader = reader
        self._writer = writer
        self.direction = direction  # "inbound" | "outbound"
        self.peer_id: str | None = None  # do outro lado, conhecido após o HELLO
        self.features: list[str] = []  # anunciadas no HELLO do outro lado
        self.state = PeerState.CONNECTING
        self.rtt_ms: float | None = None  # média móvel dos últimos 10 PING/PONG (01.5)
        self.missed_pings = 0
        peer = writer.get_extra_info("peername")
        self.remote_addr = f"{peer[0]}:{peer[1]}" if peer else "?"
        self.closed = False
        self._announced = False  # já passou por on_connected?
        self._write_lock = asyncio.Lock()

    @property
    def label(self) -> str:
        """Nome para os logs: peer_id se já conhecido, senão ip:porta."""
        return self.peer_id or self.remote_addr

    # --- escrita ------------------------------------------------------------

    async def send(self, msg: dict) -> bool:
        """Escreve uma mensagem (uma linha). False se a conexão já caiu.

        Nunca levanta. O lock garante que duas tarefas escrevendo ao mesmo
        tempo (host, keep-alive, CLI) não misturem os bytes de duas linhas.
        """
        if self.closed:
            return False
        try:
            line = protocol.encode(msg)
        except protocol.ProtocolError as exc:
            log.warning("not sending %s to %s: %s", msg.get("type"), self.label, exc)
            return False
        try:
            async with self._write_lock:
                self._writer.write(line)
                await self._writer.drain()
        except (OSError, RuntimeError) as exc:
            log.warning("write to %s failed (%s); closing", self.label, exc)
            await self._abort()
            return False
        wire.debug("-> %s %s", self.label, line.decode("utf-8").rstrip())
        return True

    # --- leitura ------------------------------------------------------------

    async def _read_loop(self) -> None:
        """Lê linha a linha até a conexão acabar; sempre termina em _abort()."""
        try:
            while not self.closed:
                msg = await self._read_message()
                if msg is None:
                    break
                await self._dispatch(msg)
        finally:
            await self._abort()

    async def _read_message(self) -> dict | None:
        """Lê UMA mensagem. None quando a conexão deve ser fechada."""
        try:
            raw = await self._reader.readline()
        except ValueError:
            # o StreamReader levanta ValueError quando a linha passa do `limit`
            log.warning("%s sent a line over %d bytes; closing",
                        self.label, protocol.MAX_LINE_BYTES)
            return None
        except OSError as exc:
            log.info("read from %s failed (%s)", self.label, exc)
            return None
        if not raw or not raw.endswith(b"\n"):
            return None  # b"": o outro lado fechou (ou caiu no meio de uma linha)
        wire.debug("<- %s %s", self.label, raw.decode("utf-8", errors="replace").rstrip())
        try:
            return protocol.decode(raw)
        except protocol.ProtocolError as exc:
            log.warning("bad JSON from %s (%s); closing", self.label, exc.message)
            await self.send(
                protocol.new_message(
                    "ERROR",
                    src=self._server.cfg.peer_id,
                    dst=self.peer_id,
                    code=protocol.ErrorCode.BAD_JSON,
                    message=exc.message,
                )
            )
            return None

    async def _dispatch(self, msg: dict) -> None:
        """Entrega a mensagem ao roteador. Erro no handler não derruba a conexão."""
        try:
            await self._server.on_message(self, msg)
        except Exception:
            log.exception("handler failed for %s from %s", msg.get("type"), self.label)

    # --- fechamento ---------------------------------------------------------

    async def close(self, reason: str = "shutdown") -> None:
        """Fecha a conexão. (A 01.4 acrescenta o BYE / BYE_OK antes disto.)"""
        await self._abort()

    async def _abort(self) -> None:
        """Fecha o socket sem conversa. Idempotente: só a 1ª chamada faz algo."""
        if self.closed:
            return
        self.closed = True
        self.state = PeerState.STALE
        self._writer.close()
        try:
            await asyncio.wait_for(self._writer.wait_closed(), CLOSE_TIMEOUT)
        except (OSError, asyncio.TimeoutError):
            pass
        log.info("connection with %s closed", self.label)
        await self._server._connection_closed(self)


class PeerServer:
    """Aceita conexões de entrada e abre as de saída."""

    def __init__(
        self,
        cfg: Config,
        on_message: OnMessage,
        on_closed: OnClosed,
        on_connected: OnConnected | None = None,
    ) -> None:
        self.cfg = cfg
        self.on_message = on_message
        self.on_closed = on_closed
        self.on_connected = on_connected
        self.port: int | None = None  # porta real (útil com listen_port=0 nos testes)
        self._server: asyncio.base_events.Server | None = None
        self._conns: set[PeerConnection] = set()
        self._tasks: set[asyncio.Task] = set()
        self._stopping = False

    async def start(self) -> None:
        """Começa a escutar em cfg.listen_port, em todas as interfaces."""
        self._server = await asyncio.start_server(
            self._on_inbound, host="0.0.0.0", port=self.cfg.listen_port,
            limit=protocol.MAX_LINE_BYTES,
        )
        self.port = self._server.sockets[0].getsockname()[1]
        log.info("listening on port %d", self.port)

    async def stop(self) -> None:
        """Para de aceitar, fecha todas as conexões e cancela as tarefas."""
        self._stopping = True
        if self._server is not None:
            self._server.close()
        for conn in list(self._conns):
            await conn._abort()
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._server is not None:
            await self._server.wait_closed()

    async def connect(self, ip: str, port: int) -> PeerConnection | None:
        """Abre conexão de saída. None se falhar."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port, limit=protocol.MAX_LINE_BYTES),
                CONNECT_TIMEOUT,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            log.info("cannot connect to %s:%s (%s)", ip, port, exc or "timeout")
            return None
        conn = PeerConnection(self, reader, writer, "outbound")
        self._conns.add(conn)
        await self._ready(conn)
        self._spawn(conn._read_loop(), f"read {conn.label}")
        return conn

    # --- interno ------------------------------------------------------------

    async def _on_inbound(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Chamado pelo asyncio a cada conexão de entrada (já numa tarefa própria)."""
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        conn = PeerConnection(self, reader, writer, "inbound")
        self._conns.add(conn)
        try:
            await self._ready(conn)
            await conn._read_loop()
        finally:
            if task is not None:
                self._tasks.discard(task)

    async def _ready(self, conn: PeerConnection) -> None:
        """A conexão está pronta para uso: avisa quem assinou (PeerTable.attach)."""
        conn.state = PeerState.CONNECTED
        conn._announced = True
        if self.on_connected is not None:
            await self._safe(self.on_connected, conn)

    async def _connection_closed(self, conn: PeerConnection) -> None:
        self._conns.discard(conn)
        if conn._announced and not self._stopping:
            await self._safe(self.on_closed, conn)

    def _spawn(self, coro, name: str) -> None:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @staticmethod
    async def _safe(callback, conn: PeerConnection) -> None:
        try:
            await callback(conn)
        except Exception:
            log.exception("callback %r failed for %s", callback, conn.label)
