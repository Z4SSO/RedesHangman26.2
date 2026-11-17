"""Valida o envelope e despacha cada mensagem recebida pelo `type`.

Dono: Pessoa C. Issue 03.2. Logger: "Router".
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from . import protocol as p
from .models import Sender

log = logging.getLogger("Router")

Handler = Callable[[Any, dict], Awaitable[None]]  # (conn, msg); conn é um PeerConnection

# Tipos que só circulam entre peers que anunciaram a feature "hangman" no HELLO.
GAME_FEATURE_TYPES = p.LOBBY_TYPES | p.GAME_TYPES


class MessageRouter:
    def __init__(self, local_peer_id: str, send: Sender) -> None:
        """`send` é o `PeerTable.send_to`: o `request()` envia por ele."""
        self.local_peer_id = local_peer_id
        self.send = send
        self._handlers: dict[str, Handler] = {}
        self._pending: dict[str, tuple[str, asyncio.Future]] = {}  # msg_id -> (peer, futuro)

    def register(self, msg_type: str, handler: Handler) -> None:
        """Associa um tipo (ex.: 'JOIN') a um handler `async def h(conn, msg)`."""
        self._handlers[msg_type] = handler

    # --- erros ---
    def _error(self, conn: Any, request: dict | None, code: str, text: str) -> dict:
        fields: dict[str, Any] = {"code": code, "message": text}
        if request and isinstance(request.get("msg_id"), str):
            fields["ref_msg_id"] = request["msg_id"]
        return p.new_message("ERROR", src=self.local_peer_id, dst=conn.peer_id, **fields)

    async def on_bad_line(self, conn: Any, exc: Exception) -> None:
        """Linha que não é JSON (a leitura do socket é da A): responde ERROR bad_json.
        Quem chama fecha a conexão depois (especificação, seção Transporte)."""
        log.warning("bad JSON from %s: %s", conn.peer_id, exc)
        if conn.peer_id is None:  # antes do HELLO: o ERROR sairia sem dst; a A só fecha a conexão
            log.debug("no ERROR sent: peer not identified yet")
            return
        await conn.send(self._error(conn, None, p.ErrorCode.BAD_JSON, str(exc)))

    # --- entrada ---
    async def on_message(self, conn: Any, msg: dict) -> None:
        """Ponto de entrada (é o `on_message` do PeerServer).
        validate_envelope -> ERROR quando preciso -> despacho. Peer sem a feature
        'hangman' nunca recebe/entrega mensagens de lobby/partida."""
        try:
            p.validate_envelope(msg, self.local_peer_id)
        except p.ProtocolError as exc:
            if exc.silent:  # ttl != 1: descarta sem resposta
                log.debug("dropped from %s: %s", conn.peer_id, exc.message)
            else:
                log.warning("invalid message from %s: %s (%s)", conn.peer_id, exc.code, exc.message)
                if msg.get("type") != "ERROR":  # ERROR nunca gera resposta
                    await conn.send(self._error(conn, msg, exc.code, exc.message))
            return  # a conexão permanece aberta

        type_ = msg["type"]
        # Decisão provisória (contrato 6): o src declarado tem de ser o peer do socket,
        # senão qualquer vizinho jogaria no lugar de outro.
        if msg.get("src") is not None and msg["src"] != conn.peer_id:
            log.warning("dropped %s: src %s does not match connection peer %s", type_, msg["src"], conn.peer_id)
            return

        if type_ == "ERROR":
            log.warning("ERROR from %s: %s: %s (ref %s)", conn.peer_id, msg["code"], msg["message"], msg.get("ref_msg_id"))
            # O ERROR tem msg_id novo e aponta a causa em ref_msg_id: se a causa é um request()
            # nosso, encerra o pedido em vez de esperar o timeout inteiro.
            ref = msg.get("ref_msg_id")
            pending = self._pending.get(ref) if isinstance(ref, str) else None
            if pending and pending[0] == msg["src"] and not pending[1].done():
                pending[1].set_result(msg)
            return  # nunca responde

        if type_ in GAME_FEATURE_TYPES and p.FEATURE_HANGMAN not in (getattr(conn, "features", None) or []):
            log.warning("dropped %s from %s: peer did not announce '%s'", type_, conn.peer_id, p.FEATURE_HANGMAN)
            return

        pending = self._pending.get(msg["msg_id"])
        if pending and pending[0] == msg["src"] and not pending[1].done():
            pending[1].set_result(msg)  # resposta de um request(): não vai aos handlers
            return

        handler = self._handlers.get(type_)
        if handler is None:
            log.debug("no handler for %s from %s", type_, conn.peer_id)
            return
        try:
            await handler(conn, msg)
        except Exception:  # um handler com defeito não derruba o roteador
            log.exception("handler for %s from %s failed", type_, conn.peer_id)

    # --- saída ---
    async def request(self, peer_id: str, msg: dict, timeout: float = 5.0) -> dict | None:
        """Envia e espera a resposta com o MESMO msg_id (GAME_LIST_OK, ...) ou um ERROR
        que aponte para ele em ref_msg_id: quem chama confere `reply["type"]`.
        None se estourar o timeout ou se o peer não estiver conectado. Respostas
        pendentes não vão para os handlers."""
        msg_id = msg["msg_id"]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = (peer_id, fut)  # antes do envio: a resposta pode ser rápida
        try:
            if not await self.send(peer_id, msg):
                return None
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            log.debug("request %s to %s timed out", msg["type"], peer_id)
            return None
        finally:
            self._pending.pop(msg_id, None)
