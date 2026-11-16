"""PING/PONG periódico, RTT e detecção de STALE.

Dono: Pessoa A. Issue 01.5. Logger: "KeepAlive".
"""

from __future__ import annotations

import logging

from .config import Config
from .peer_connection import PeerConnection

log = logging.getLogger("KeepAlive")


class KeepAlive:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def watch(self, conn: PeerConnection) -> None:
        """Começa a enviar PING a cada cfg.ping_interval nesta conexão. Após
        cfg.ping_miss_limit sem PONG: log '[KeepAlive] X missed 3 PINGs —
        marking STALE', estado STALE e fechamento da conexão."""
        raise NotImplementedError("issue 01.5")

    def on_pong(self, conn: PeerConnection, msg: dict) -> None:
        """RTT = agora - timestamp do PING casado pelo msg_id."""
        raise NotImplementedError("issue 01.5")

    def unwatch(self, conn: PeerConnection) -> None:
        raise NotImplementedError("issue 01.5")
