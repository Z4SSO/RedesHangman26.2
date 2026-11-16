"""Máquina de estados do host: lobby, turnos, validação de jogadas, STATE.

Dono: Pessoa B. Issues 02.2 a 02.5. Logger: "Host". Mensagens `[Game]` para a
tela via logger "Game". Usa `hangman.Hangman` para as regras (nada de rede lá).
"""

from __future__ import annotations

import logging

from .config import Config
from .models import GameStatus, Sender

log = logging.getLogger("Host")


class GameHost:
    def __init__(self, cfg: Config, send: Sender) -> None:
        self.cfg = cfg
        self.send = send
        self.status = GameStatus.IDLE
        self.game_id: str | None = None

    @property
    def active(self) -> bool:
        """True em OPEN ou RUNNING (o peer não pode entrar em outra partida)."""
        return self.status in (GameStatus.OPEN, GameStatus.RUNNING)

    # --- comandos locais (CLI) ---
    async def create(self, word: str, max_players: int | None = None) -> str:
        """Normaliza a palavra, gera game_id `<host>/<8 hex>`, status OPEN.
        Devolve o game_id. ValueError se a palavra for inválida."""
        raise NotImplementedError("issue 02.2")

    async def start(self) -> None:
        """OPEN -> RUNNING. Exige >=1 jogador. Envia GAME_START e STATE seq=1."""
        raise NotImplementedError("issue 02.3")

    async def cancel(self) -> None:
        """GAME_OVER ABORTED reason='host_shutdown' a todos; volta a IDLE."""
        raise NotImplementedError("issue 02.4")

    async def shutdown(self) -> None:
        """Chamado no /quit: igual a cancel() se houver partida ativa."""
        raise NotImplementedError("issue 02.4")

    def describe(self) -> dict | None:
        """Entrada de `games[]` do GAME_LIST_OK, ou None se não há partida."""
        raise NotImplementedError("issue 02.2")

    # --- handlers de mensagens (registrados no MessageRouter) ---
    async def on_game_list(self, conn, msg: dict) -> None:
        raise NotImplementedError("issue 02.2")

    async def on_join(self, conn, msg: dict) -> None:
        raise NotImplementedError("issue 02.2")

    async def on_leave(self, conn, msg: dict) -> None:
        raise NotImplementedError("issue 02.2")

    async def on_guess(self, conn, msg: dict) -> None:
        raise NotImplementedError("issue 02.4")

    # --- eventos da PeerTable ---
    async def on_peer_stale(self, peer_id: str) -> None:
        """Jogador caiu: remove, passa o turno se era a vez dele, difunde STATE."""
        raise NotImplementedError("issue 02.5")
