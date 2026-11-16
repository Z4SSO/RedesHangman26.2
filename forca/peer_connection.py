"""Servidor e cliente TCP entre peers, framing JSON-por-linha, HELLO, duplicadas.

Dono: Pessoa A. Issues 01.3 e 01.4. Logger: "PeerServer" (e "Wire" para o JSON
bruto em DEBUG, com setas -> e <-).

Esta camada resolve sozinha HELLO/HELLO_OK, PING/PONG (via KeepAlive) e
BYE/BYE_OK. Todo o resto sobe para o MessageRouter por `on_message`.
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from .config import Config
from .models import PeerState

log = logging.getLogger("PeerServer")
wire = logging.getLogger("Wire")

OnMessage = Callable[["PeerConnection", dict], Awaitable[None]]
OnClosed = Callable[["PeerConnection"], Awaitable[None]]


class PeerConnection:
    """Uma conexão TCP estabelecida (já com HELLO concluído)."""

    peer_id: str  # do outro lado
    direction: str  # "inbound" | "outbound"
    state: PeerState
    rtt_ms: float | None  # média móvel dos últimos 10 PING/PONG
    missed_pings: int

    async def send(self, msg: dict) -> bool:
        """Escreve uma mensagem. False se a conexão já caiu (nunca levanta)."""
        raise NotImplementedError("issue 01.3")

    async def close(self, reason: str = "shutdown") -> None:
        """BYE, espera BYE_OK por até 2 s, fecha o socket com ou sem resposta."""
        raise NotImplementedError("issue 01.4")


class PeerServer:
    """Aceita conexões de entrada e abre as de saída."""

    def __init__(self, cfg: Config, on_message: OnMessage, on_closed: OnClosed) -> None:
        self.cfg = cfg
        self.on_message = on_message
        self.on_closed = on_closed

    async def start(self) -> None:
        """Começa a escutar em cfg.listen_port."""
        raise NotImplementedError("issue 01.3")

    async def stop(self) -> None:
        raise NotImplementedError("issue 01.3")

    async def connect(self, ip: str, port: int) -> PeerConnection | None:
        """Abre conexão de saída e faz o HELLO. None se falhar."""
        raise NotImplementedError("issue 01.3")
