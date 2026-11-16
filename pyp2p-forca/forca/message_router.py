"""Valida o envelope e despacha cada mensagem recebida pelo `type`.

Dono: Pessoa C. Issue 03.2. Logger: "Router".
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from .peer_connection import PeerConnection

log = logging.getLogger("Router")

Handler = Callable[[PeerConnection, dict], Awaitable[None]]


class MessageRouter:
    def __init__(self, local_peer_id: str) -> None:
        self.local_peer_id = local_peer_id

    def register(self, msg_type: str, handler: Handler) -> None:
        """Associa um tipo (ex.: 'JOIN') a um handler `async def h(conn, msg)`."""
        raise NotImplementedError("issue 03.2")

    async def on_message(self, conn: PeerConnection, msg: dict) -> None:
        """Ponto de entrada (é o `on_message` do PeerServer).
        validate_envelope -> ERROR quando preciso -> despacho. Peer sem a feature
        'hangman' nunca recebe/entrega mensagens de lobby/partida."""
        raise NotImplementedError("issue 03.2")

    async def request(self, peer_id: str, msg: dict, timeout: float = 5.0) -> dict | None:
        """Envia e espera a resposta com o MESMO msg_id (GAME_LIST_OK, JOIN_OK...).
        None se estourar o timeout. Respostas pendentes não vão para os handlers."""
        raise NotImplementedError("issue 03.2")
