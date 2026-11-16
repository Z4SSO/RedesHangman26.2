"""Tabela de peers: estados, RTT, backoff, reconciliação com o Rendezvous.

Dono: Pessoa A. Issues 01.2 e 01.6. Logger: "PeerTable".
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from .models import PeerState
from .peer_connection import PeerConnection

log = logging.getLogger("PeerTable")

# Eventos que os outros módulos assinam (ver CONTRATO.md, seção 5).
EVENT_CONNECTED = "peer_connected"  # callback(peer_id)
EVENT_STALE = "peer_stale"  # callback(peer_id)  -> host remove jogador / jogador aborta
EVENT_GONE = "peer_gone"  # callback(peer_id)


class PeerTable:
    def __init__(self) -> None:
        raise NotImplementedError("issue 01.2")

    def subscribe(self, event: str, callback: Callable[[str], Awaitable[None]]) -> None:
        raise NotImplementedError("issue 01.2")

    def state_of(self, peer_id: str) -> PeerState | None:
        raise NotImplementedError("issue 01.2")

    def connected(self) -> list[PeerConnection]:
        """Conexões CONNECTED (exatamente uma por vizinho)."""
        raise NotImplementedError("issue 01.2")

    async def send_to(self, peer_id: str, msg: dict) -> bool:
        """É a implementação do `Sender` (models.Sender). False se não conectado."""
        raise NotImplementedError("issue 01.2")

    async def broadcast(self, msg_factory: Callable[[str], dict]) -> None:
        """Envia a todos os conectados; `msg_factory(peer_id)` monta a mensagem
        de cada um (o dst muda)."""
        raise NotImplementedError("issue 01.2")

    async def reconcile(self, discovered: list[dict]) -> None:
        """Aplica o resultado de um DISCOVER: novos -> DISCOVERED + conectar;
        ausentes -> GONE e BYE."""
        raise NotImplementedError("issue 01.2")
