# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
"""Servidor e cliente TCP entre peers, framing JSON-por-linha, HELLO, duplicadas.

Dono: Pessoa A. Issues 01.3 (transporte) e 01.4 (HELLO, BYE, duplicadas).
Logger: "PeerServer" (e "Wire" para o JSON bruto em DEBUG, setas -> e <-).

Especificação, "Transporte e Codificação":
- TCP, JSON UTF-8, um objeto por linha terminado em \\n, no máximo 32 KiB;
- linha que não é JSON válido: responde ERROR (bad_json) e fecha a conexão;
- erro de leitura/escrita: conexão fechada imediatamente.

Especificação, "Mensagens de sessão":
- quem ABRE a conexão envia HELLO; quem aceita responde HELLO_OK (mesmo
  msg_id). Até o HELLO_OK nenhuma outra mensagem é aceita;
- conexões duplicadas: vale a conexão aberta pelo peer de MENOR peer_id; a
  outra é fechada com BYE reason "duplicate";
- BYE: quem envia espera BYE_OK por até 2 s e fecha o socket de qualquer jeito;
  quem recebe responde BYE_OK e fecha.

Esta camada resolve sozinha HELLO/HELLO_OK, PING/PONG (o PONG vai para o
KeepAlive pelo gancho `on_pong`) e BYE/BYE_OK. Todo o resto sobe para o
MessageRouter por `on_message`.
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
OnPong = Callable[["PeerConnection", dict], None]
OnBadLine = Callable[["PeerConnection", Exception], Awaitable[None]]

CONNECT_TIMEOUT = 5.0  # abrir o socket de saída
HELLO_TIMEOUT = 5.0  # esperar o HELLO / HELLO_OK
BYE_TIMEOUT = 2.0  # esperar o BYE_OK (especificação)
CLOSE_TIMEOUT = 1.0  # esperar o socket terminar de fechar
DUPLICATE_GRACE = 2.0  # após BYE "duplicate", espera a conexão que vai substituir


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
        self._duplicate_bye = False  # o outro lado nos fechou com BYE "duplicate"
        self._bye_ack = asyncio.Event()  # chegou o BYE_OK que esperamos
        self._bye_msg_id: str | None = None  # msg_id do BYE que enviamos (o BYE_OK repete)
        self._write_lock = asyncio.Lock()

    @property
    def label(self) -> str:
        """Nome para os logs: peer_id se já conhecido, senão ip:porta."""
        return self.peer_id or self.remote_addr

    @property
    def supports_game(self) -> bool:
        """O vizinho anunciou a feature "hangman" (senão não recebe lobby/partida)."""
        return protocol.FEATURE_HANGMAN in self.features

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
            await self._answer_bad_line(exc)
            return None  # quem chama fecha a conexão

    async def _answer_bad_line(self, exc: protocol.ProtocolError) -> None:
        """Linha que não é JSON. ANTES do HELLO o vizinho ainda não tem peer_id
        (um ERROR sairia sem `dst`): só se fecha a conexão. DEPOIS do HELLO,
        quem responde `ERROR bad_json` é o roteador, pelo gancho `on_bad_line`
        (se não houver gancho, respondemos aqui mesmo)."""
        if self.peer_id is None:
            return
        hook = self._server.on_bad_line
        try:
            if hook is not None:
                await hook(self, exc)
            else:
                await self.send(protocol.new_message(
                    "ERROR", src=self._server.cfg.peer_id, dst=self.peer_id,
                    code=protocol.ErrorCode.BAD_JSON, message=exc.message))
        except Exception:
            log.exception("on_bad_line failed for %s", self.label)

    async def _read_until(self, msg_type: str, msg_id: str | None = None) -> dict | None:
        """Handshake: lê até chegar `msg_type` (e `msg_id`, se dado), no máximo
        HELLO_TIMEOUT s. Qualquer outra mensagem antes disso é descartada
        ("até o HELLO_OK nenhuma outra mensagem é aceita")."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + HELLO_TIMEOUT
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            try:
                msg = await asyncio.wait_for(self._read_message(), remaining)
            except asyncio.TimeoutError:
                return None
            if msg is None:
                return None
            if msg.get("ttl") != protocol.FIXED_TTL:
                # ttl != 1: descartada em silêncio (envelope comum) e seguimos esperando
                log.debug("dropping %s with ttl=%r from %s", msg.get("type"), msg.get("ttl"), self.label)
                continue
            if msg.get("type") == msg_type and (msg_id is None or msg.get("msg_id") == msg_id):
                return msg
            log.debug("dropping %s from %s before %s", msg.get("type"), self.label, msg_type)

    async def _dispatch(self, msg: dict) -> None:
        """Trata os tipos de sessão aqui; o resto sobe para o roteador.

        Erro no handler não derruba a conexão.
        """
        try:
            type_ = msg.get("type")
            if type_ in ("HELLO", "HELLO_OK"):
                log.debug("ignoring repeated %s from %s", type_, self.label)
            elif type_ == "PING":
                await self._on_ping(msg)
            elif type_ == "PONG":
                self._on_pong(msg)
            elif type_ == "BYE":
                await self._on_bye(msg)
            elif type_ == "BYE_OK":
                # só vale o BYE_OK do BYE que NÓS enviamos (mesmo msg_id)
                if self._bye_msg_id is not None and msg.get("msg_id") == self._bye_msg_id:
                    self._bye_ack.set()
            else:
                await self._server.on_message(self, msg)
        except Exception:
            log.exception("handler failed for %s from %s", msg.get("type"), self.label)

    def _valid_session_msg(self, msg: dict) -> bool:
        """PING/PONG/BYE: envelope e campos obrigatórios conferem?"""
        try:
            protocol.validate_envelope(msg, self._server.cfg.peer_id)
            return True
        except protocol.ProtocolError as exc:
            log.debug("dropping invalid %s from %s: %s", msg.get("type"), self.label, exc.message)
            return False

    async def _on_ping(self, msg: dict) -> None:
        """PONG repete o msg_id e o timestamp do PING (especificação)."""
        if self._valid_session_msg(msg):
            await self.send(protocol.reply(msg, "PONG", timestamp=msg["timestamp"]))

    def _on_pong(self, msg: dict) -> None:
        if self._valid_session_msg(msg) and self._server.on_pong is not None:
            self._server.on_pong(self, msg)  # KeepAlive.on_pong (01.5)

    async def _on_bye(self, msg: dict) -> None:
        """Quem recebe BYE responde BYE_OK e fecha o socket."""
        if not self._valid_session_msg(msg):
            return
        reason = msg.get("reason")
        log.info("BYE from %s (reason=%s)", self.label, reason)
        self._duplicate_bye = reason == "duplicate"
        await self.send(protocol.reply(msg, "BYE_OK"))
        await self._abort()

    # --- fechamento ---------------------------------------------------------

    async def close(self, reason: str = "shutdown", wait_ack: bool = True) -> None:
        """BYE, espera BYE_OK por até 2 s, fecha o socket com ou sem resposta.

        `wait_ack=False` envia o BYE e fecha na hora: usado pelo KeepAlive com
        um peer que já não responde (esperar 2 s só atrasaria o `peer_stale`).
        """
        if self.closed:
            return
        if self.peer_id is not None:
            bye = protocol.new_message(
                "BYE", src=self._server.cfg.peer_id, dst=self.peer_id, reason=reason
            )
            self._bye_msg_id = bye["msg_id"]
            if await self.send(bye) and wait_ack:
                try:
                    await asyncio.wait_for(self._bye_ack.wait(), BYE_TIMEOUT)
                except asyncio.TimeoutError:
                    log.debug("no BYE_OK from %s within %.0f s", self.label, BYE_TIMEOUT)
        await self._abort()

    async def _abort(self) -> None:
        """Fecha o socket sem conversa. Idempotente: só a 1ª chamada faz algo."""
        if self.closed:
            return
        self.closed = True
        self.state = PeerState.STALE
        # quem espera o BYE_OK num close() não precisa esperar mais: a conexão
        # acabou (ex.: os dois lados se encerram ao mesmo tempo e trocam BYEs)
        self._bye_ack.set()
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
        self.on_pong: OnPong | None = None  # KeepAlive.on_pong (01.5)
        self.on_bad_line: OnBadLine | None = None  # MessageRouter.on_bad_line: ERROR bad_json (só após o HELLO)
        self.port: int | None = None  # porta real (útil com listen_port=0 nos testes)
        self._server: asyncio.base_events.Server | None = None
        self._conns: set[PeerConnection] = set()
        self._by_peer: dict[str, PeerConnection] = {}  # a conexão válida de cada vizinho
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
        """Abre conexão de saída e faz o HELLO.

        None se falhar OU se perder o desempate de duplicada (nesse caso já
        existe uma conexão válida com aquele vizinho).
        """
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
        try:
            if not await self._hello_outbound(conn):
                await conn._abort()
                return None
            kept = await self._establish(conn)
        except asyncio.CancelledError:
            await conn._abort()  # cancelado no meio do HELLO (ex.: /quit): não deixa o socket aberto
            raise
        self._spawn(conn._read_loop(), f"read {conn.label}")
        if not kept:
            self._spawn(conn.close("duplicate"), f"close {conn.label}")
            return None
        return conn

    # --- HELLO --------------------------------------------------------------

    async def _hello_outbound(self, conn: PeerConnection) -> bool:
        """Quem abre a conexão envia HELLO e espera o HELLO_OK de mesmo msg_id."""
        hello = protocol.new_message(
            "HELLO",
            peer_id=self.cfg.peer_id,
            version=protocol.PROTOCOL_VERSION,
            features=[protocol.FEATURE_HANGMAN],
        )
        if not await conn.send(hello):
            return False
        reply = await conn._read_until("HELLO_OK", hello["msg_id"])
        if reply is None:
            log.warning("no HELLO_OK from %s; closing", conn.label)
            return False
        return self._accept_hello(conn, reply)

    async def _hello_inbound(self, conn: PeerConnection) -> bool:
        """Quem aceita espera o HELLO e responde HELLO_OK (mesmo msg_id)."""
        hello = await conn._read_until("HELLO")
        if hello is None:
            log.warning("no HELLO from %s; closing", conn.label)
            return False
        if not self._accept_hello(conn, hello):
            return False
        ok = protocol.reply(
            hello,
            "HELLO_OK",
            peer_id=self.cfg.peer_id,
            version=protocol.PROTOCOL_VERSION,
            features=[protocol.FEATURE_HANGMAN],
        )
        return await conn.send(ok)

    def _accept_hello(self, conn: PeerConnection, msg: dict) -> bool:
        """Valida o HELLO/HELLO_OK e guarda peer_id e features do vizinho."""
        try:
            protocol.validate_envelope(msg)
        except protocol.ProtocolError as exc:
            log.warning("invalid %s from %s: %s", msg.get("type"), conn.label, exc.message)
            return False
        peer_id = msg["peer_id"]
        name, namespace = protocol.split_peer_id(peer_id)
        if not name or not namespace:
            log.warning("bad peer_id %r from %s", peer_id, conn.label)
            return False
        if peer_id == self.cfg.peer_id:
            log.warning("%s claims to be me (%s); closing", conn.label, peer_id)
            return False
        if msg["version"] != protocol.PROTOCOL_VERSION:
            log.warning("%s speaks protocol %s (expected %s)",
                        peer_id, msg["version"], protocol.PROTOCOL_VERSION)
        conn.peer_id = peer_id
        conn.features = list(msg["features"])
        return True

    # --- duplicadas ---------------------------------------------------------

    async def _establish(self, conn: PeerConnection) -> bool:
        """Registra a conexão que acabou de concluir o HELLO.

        True se ela é a válida daquele vizinho (e foi anunciada por
        on_connected); False se perdeu o desempate de duplicada.
        """
        pid = conn.peer_id
        existing = self._by_peer.get(pid)
        if existing is not None and not existing.closed:
            winner = self._duplicate_winner(existing, conn)
            if winner is existing:
                return False  # a recém-chegada perde; quem chamou fecha com BYE duplicate
            # a nova vence: assume ANTES de fechar a antiga, para a PeerTable
            # trocar de conexão sem gerar um peer_stale falso
            self._by_peer[pid] = conn
            await self._announce(conn)
            self._spawn(existing.close("duplicate"), f"close {existing.label}")
            return True
        self._by_peer[pid] = conn
        await self._announce(conn)
        return True

    def _duplicate_winner(self, old: PeerConnection, new: PeerConnection) -> PeerConnection:
        """Vale a conexão aberta pelo peer de MENOR peer_id (especificação).

        Se eu sou o menor, vale a minha de saída; senão, a de entrada. Os dois
        lados chegam à mesma escolha sem conversar. Duas conexões da mesma
        direção não são o caso de "abertura simultânea" (é o vizinho que
        reconectou): fica a mais nova.
        """
        pid = new.peer_id
        if old.direction == new.direction:
            log.info("Replacing connection with %s (same direction, newer wins)", pid)
            return new
        keep = "outbound" if self.cfg.peer_id < pid else "inbound"
        winner = old if old.direction == keep else new
        log.info("Duplicate connection with %s — keeping %s (lower peer_id)", pid, keep)
        return winner

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
            if not await self._hello_inbound(conn):
                await conn._abort()
                return
            if not await self._establish(conn):
                self._spawn(conn.close("duplicate"), f"close {conn.label}")
            await conn._read_loop()
        finally:
            if task is not None:
                self._tasks.discard(task)

    async def _announce(self, conn: PeerConnection) -> None:
        """A conexão está pronta para uso: avisa quem assinou (PeerTable.attach)."""
        conn.state = PeerState.CONNECTED
        conn._announced = True
        log.info("%s connected: %s (features=%s)",
                 conn.direction.capitalize(), conn.peer_id, ",".join(conn.features))
        if self.on_connected is not None:
            await self._safe(self.on_connected, conn)

    async def _connection_closed(self, conn: PeerConnection) -> None:
        """Uma conexão acabou. Só avisa on_closed se ela ainda era a válida do
        vizinho (a duplicada descartada não conta como queda)."""
        self._conns.discard(conn)
        pid = conn.peer_id
        if self._stopping or pid is None or not conn._announced:
            return
        if conn._duplicate_bye:
            # O outro lado nos fechou por duplicada: a conexão vencedora pode
            # ainda não ter chegado aqui. Dá um tempo para ela substituir esta;
            # sem isso o host removeria o jogador por uma queda que não houve.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + DUPLICATE_GRACE
            while self._by_peer.get(pid) is conn and loop.time() < deadline:
                await asyncio.sleep(0.02)
        if self._by_peer.get(pid) is conn:
            del self._by_peer[pid]
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
