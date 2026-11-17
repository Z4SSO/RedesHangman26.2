"""Interface de comandos do usuário (/peers, /games, /create, ...).

Dono: Pessoa C. Issues 03.3 e 03.4. Logger: "CLI". A leitura do teclado NÃO pode
bloquear o event loop: uma thread lê o stdin e entrega as linhas por uma fila.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
from typing import Awaitable, Callable

from .rendezvous_connection import RendezvousError

log = logging.getLogger("CLI")

COMMANDS = (
    "/peers", "/conn", "/rtt", "/reconnect", "/games", "/create", "/start",
    "/cancel", "/join", "/leave", "/guess", "/word", "/status", "/log",
    "/help", "/quit",
)

# Os 17 comandos da especificação (seção "Interface de Usuário"): /create tem duas formas.
HELP = (
    ("/peers [* | #namespace]", "descobre e lista peers (padrão: namespace local)"),
    ("/conn", "lista as conexões ativas (entrada/saída, estado, RTT)"),
    ("/rtt", "mostra o RTT médio por peer"),
    ("/reconnect", "força a reconciliação imediata com o Rendezvous"),
    ("/games", "pergunta a todos os vizinhos e lista as partidas abertas"),
    ("/create <palavra> [max_players]", "cria uma partida com a palavra e vira host"),
    ("/create --random [max_players]", "cria uma partida com palavra sorteada de words.txt"),
    ("/start", "inicia a partida hospedada (exige pelo menos 1 jogador)"),
    ("/cancel", "cancela a partida hospedada"),
    ("/join <host_peer_id>", "entra na partida hospedada pelo peer"),
    ("/leave", "sai da partida atual"),
    ("/guess <letra>", "palpite de uma letra"),
    ("/word <palavra>", "palpite da palavra inteira"),
    ("/status", "mostra o estado local da partida"),
    ("/log <nível>", "ajusta o nível de log da tela (DEBUG, INFO, WARNING, ERROR)"),
    ("/help", "lista os comandos"),
    ("/quit", "encerra (LEAVE/GAME_OVER conforme o papel, BYE a todos, UNREGISTER)"),
)

MIN_DISCOVER_GAP = 2.0  # s entre DISCOVERs: o Rendezvous bloqueia acima de 50 req/min
_STDIN = object()  # "use sys.stdin" (resolvido na hora de rodar, para os testes poderem trocá-lo)


class UsageError(Exception):
    """Argumentos errados: a mensagem é mostrada ao usuário e o programa segue."""


class CLI:
    def __init__(self, client, set_log_level=None, stdin=_STDIN, clock=time.monotonic) -> None:
        """`set_log_level(nome)` troca o nível da tela (injetado pelo main). `stdin=None`
        desliga a thread de leitura (testes, que usam `feed()`)."""
        self.client = client
        self.set_log_level = set_log_level
        self._stdin = stdin
        self._clock = clock
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._quit = False
        self._last_discover = float("-inf")
        self._commands: dict[str, Callable[[list[str]], Awaitable[None]]] = {
            "/peers": self.cmd_peers, "/conn": self.cmd_conn, "/rtt": self.cmd_rtt,
            "/reconnect": self.cmd_reconnect, "/log": self.cmd_log, "/help": self.cmd_help,
            "/quit": self.cmd_quit,
        }

    # --- entrada ---
    def feed(self, line: str) -> None:
        """Entrega uma linha ao laço (usado pela thread do teclado e pelos testes)."""
        self._queue.put_nowait(line)

    def request_quit(self) -> None:
        """Ctrl+C / SIGTERM: mesmo caminho do /quit."""
        self.feed("/quit")

    def _read_stdin(self, stream, loop: asyncio.AbstractEventLoop) -> None:
        """Thread daemon: lê o teclado sem bloquear o event loop. EOF vale como /quit."""
        for line in stream:
            loop.call_soon_threadsafe(self.feed, line.rstrip("\n"))
        loop.call_soon_threadsafe(self.feed, "/quit")

    async def run(self) -> None:
        """Laço de leitura e despacho dos comandos até /quit."""
        stream = sys.stdin if self._stdin is _STDIN else self._stdin
        if stream is not None:
            loop = asyncio.get_running_loop()
            threading.Thread(target=self._read_stdin, args=(stream, loop), daemon=True).start()
        log.info("Digite /help para ver os comandos.")
        while not self._quit:
            await self.execute(await self._queue.get())

    async def execute(self, line: str) -> None:
        """Interpreta uma linha. Nada aqui derruba o programa."""
        line = line.strip()
        if not line:
            return
        if not line.startswith("/"):
            log.warning("Comandos começam com '/'. Digite /help.")
            return
        cmd, *args = line.split()
        handler = self._commands.get(cmd.lower())
        if handler is None:
            log.warning("Comando desconhecido: %s. Digite /help.", cmd)
            return
        try:
            await handler(args)
        except UsageError as exc:
            log.warning("%s", exc)
        except Exception:
            log.exception("erro ao executar %s", cmd)

    # --- comandos de rede ---
    async def cmd_peers(self, args: list[str]) -> None:
        """/peers [* | #namespace]: DISCOVER e lista (respeita o limite do Rendezvous)."""
        if len(args) > 1:
            raise UsageError("uso: /peers [* | #namespace]")
        if not args:
            ns = self.client.cfg.namespace
        elif args[0] == "*":
            ns = None  # todos os namespaces
        elif args[0].startswith("#") and len(args[0]) > 1:
            ns = args[0][1:]
        else:
            raise UsageError("uso: /peers [* | #namespace]")
        wait = MIN_DISCOVER_GAP - (self._clock() - self._last_discover)
        if wait > 0:
            raise UsageError(f"aguarde {wait:.0f} s entre consultas ao Rendezvous")
        self._last_discover = self._clock()
        try:
            peers = await self.client.rdv.discover(ns)
        except RendezvousError as exc:
            log.error("Rendezvous recusou o DISCOVER: %s", exc)
            return
        connected = {c.peer_id for c in self.client.table.connected()}
        where = "todos os namespaces" if ns is None else f"namespace {ns}"
        log.info("Peers em %s (%d):", where, len(peers))
        for peer in sorted(peers, key=lambda x: (x["namespace"], x["name"])):
            pid = f"{peer['name']}@{peer['namespace']}"
            state = "conectado" if pid in connected else "-"
            log.info("  %-24s %s:%s  %s", pid, peer["ip"], peer["port"], state)

    async def cmd_conn(self, args: list[str]) -> None:
        """/conn: uma linha por vizinho conectado."""
        conns = sorted(self.client.table.connected(), key=lambda c: c.peer_id)
        log.info("Conexões ativas (%d):", len(conns))
        for c in conns:
            log.info("  %-24s %-8s %-9s RTT %s", c.peer_id, c.direction, c.state.value, _rtt(c))

    async def cmd_rtt(self, args: list[str]) -> None:
        """/rtt: RTT médio (últimos 10 PINGs) por peer."""
        conns = sorted(self.client.table.connected(), key=lambda c: c.peer_id)
        if not conns:
            log.info("Nenhum peer conectado.")
        for c in conns:
            log.info("  %-24s RTT médio %s", c.peer_id, _rtt(c))

    async def cmd_reconnect(self, args: list[str]) -> None:
        """/reconnect: reconciliação imediata com o Rendezvous."""
        log.info("Reconciliando com o Rendezvous...")
        await self.client.reconcile_now()
        log.info("Reconciliação concluída.")

    async def cmd_log(self, args: list[str]) -> None:
        """/log <nível>: troca o nível da tela sem reiniciar."""
        if len(args) != 1:
            raise UsageError("uso: /log <DEBUG|INFO|WARNING|ERROR>")
        if self.set_log_level is None:
            raise UsageError("troca de nível indisponível")
        try:
            self.set_log_level(args[0])
        except ValueError as exc:
            raise UsageError(str(exc)) from None
        log.info("Nível da tela: %s", args[0].upper())

    async def cmd_help(self, args: list[str]) -> None:
        log.info("Comandos:")
        for usage, text in HELP:
            log.info("  %-34s %s", usage, text)

    async def cmd_quit(self, args: list[str]) -> None:
        """/quit: sai do laço; quem chama o `run` encerra o cliente (main.run, no finally)."""
        log.info("Encerrando...")
        self._quit = True


def _rtt(conn) -> str:
    return "-" if conn.rtt_ms is None else f"{conn.rtt_ms:.1f} ms"
