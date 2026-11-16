"""Máquina de estados do jogador: JOIN, STATE com seq, GUESS, hash, host caiu.

Dono: Pessoa B. Issue 02.6. Logger: "Player".
"""

from __future__ import annotations

import logging

from .config import Config
from .models import PlayerState, Sender

log = logging.getLogger("Player")


class GamePlayer:
    def __init__(self, cfg: Config, send: Sender) -> None:
        self.cfg = cfg
        self.send = send
        self.state = PlayerState.IDLE
        self.host_id: str | None = None
        self.game_id: str | None = None

    @property
    def active(self) -> bool:
        return self.state != PlayerState.IDLE

    # --- comandos locais (CLI) ---
    async def join(self, host_peer_id: str, game_id: str) -> None:
        raise NotImplementedError("issue 02.6")

    async def leave(self) -> None:
        raise NotImplementedError("issue 02.6")

    async def guess_letter(self, letter: str) -> None:
        raise NotImplementedError("issue 02.6")

    async def guess_word(self, word: str) -> None:
        raise NotImplementedError("issue 02.6")

    def status_lines(self) -> list[str]:
        """Linhas do /status (formato mínimo da especificação)."""
        raise NotImplementedError("issue 02.6")

    # --- handlers de mensagens ---
    async def on_join_ok(self, conn, msg: dict) -> None: ...
    async def on_join_err(self, conn, msg: dict) -> None: ...
    async def on_leave_ok(self, conn, msg: dict) -> None: ...
    async def on_game_start(self, conn, msg: dict) -> None: ...
    async def on_state(self, conn, msg: dict) -> None:
        """Descarta se seq <= último aplicado (log DEBUG)."""
        raise NotImplementedError("issue 02.6")

    async def on_guess_result(self, conn, msg: dict) -> None: ...
    async def on_game_over(self, conn, msg: dict) -> None:
        """Confere sha256(word) == word_hash; divergência -> WARNING
        'host cheated: hash mismatch'."""
        raise NotImplementedError("issue 02.6")

    # --- eventos da PeerTable ---
    async def on_peer_stale(self, peer_id: str) -> None:
        """Se for o host: '[Game] Host X unreachable — game aborted', volta a IDLE."""
        raise NotImplementedError("issue 02.6")
