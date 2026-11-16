"""Cliente do servidor Rendezvous: REGISTER / DISCOVER / UNREGISTER.

Dono: Pessoa A. Issue 01.1. Uma conexão TCP NOVA por comando (o servidor fecha
depois de responder). Logger: "RDV".
"""

from __future__ import annotations

import logging

from .config import Config

log = logging.getLogger("RDV")


class RendezvousError(Exception):
    """Servidor respondeu status=ERROR. `message` traz o código do servidor."""


class RendezvousConnection:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.public_ip: str | None = None  # preenchido pelo REGISTER

    async def register(self) -> dict:
        """REGISTER (também serve de refresh). Guarda `ip` em self.public_ip e
        registra no log: '[RDV] registered alice@CIC as IP:PORT (ttl=7200)'."""
        raise NotImplementedError("issue 01.1")

    async def discover(self, namespace: str | None = None) -> list[dict]:
        """Lista de peers do namespace (padrão: o local), JÁ SEM o próprio peer
        (filtrar por name+namespace). Cada item: ip, port, name, namespace,
        ttl, expires_in."""
        raise NotImplementedError("issue 01.1")

    async def unregister(self) -> None:
        raise NotImplementedError("issue 01.1")
