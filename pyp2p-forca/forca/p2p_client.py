"""Orquestra tudo: registro, tarefas periódicas, encerramento limpo.

Dono: Pessoa A (ciclo de vida) com Pessoa C (ligação dos handlers). Issue 01.7.
"""

from __future__ import annotations

import logging

from .config import Config

log = logging.getLogger("Client")


class P2PClient:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    async def start(self) -> None:
        """Ordem: PeerServer.start -> REGISTER -> tarefas (discover a cada
        discover_interval, refresh do registro na metade do TTL) -> router e
        eventos ligados."""
        raise NotImplementedError("issue 01.7")

    async def stop(self) -> None:
        """Ordem do /quit (cenário 10): GAME_OVER ABORTED (se host) ou LEAVE
        (se jogador) -> BYE/BYE_OK a todos -> UNREGISTER -> cancelar tarefas."""
        raise NotImplementedError("issue 01.7")
