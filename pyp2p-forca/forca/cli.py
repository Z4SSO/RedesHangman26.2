"""Interface de comandos do usuário (/peers, /games, /create, ...).

Dono: Pessoa C. Issues 03.3 e 03.4. Logger: "CLI". A leitura do teclado NÃO pode
bloquear o event loop (use run_in_executor ou asyncio.to_thread).
"""

from __future__ import annotations

import logging

log = logging.getLogger("CLI")

COMMANDS = (
    "/peers", "/conn", "/rtt", "/reconnect", "/games", "/create", "/start",
    "/cancel", "/join", "/leave", "/guess", "/word", "/status", "/log",
    "/help", "/quit",
)


class CLI:
    def __init__(self, client) -> None:
        self.client = client

    async def run(self) -> None:
        """Laço de leitura e despacho dos comandos até /quit."""
        raise NotImplementedError("issue 03.3")
