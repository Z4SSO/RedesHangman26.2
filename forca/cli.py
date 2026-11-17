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
    def __init__(self, client, set_log_level=None) -> None:
        """`set_log_level(nome)` troca o nível da tela (injetado pelo main)."""
        self.client = client
        self.set_log_level = set_log_level

    def request_quit(self) -> None:
        """Ctrl+C / SIGTERM: mesmo caminho do /quit."""
        raise NotImplementedError("issue 03.3")

    async def run(self) -> None:
        """Laço de leitura e despacho dos comandos até /quit."""
        raise NotImplementedError("issue 03.3")
