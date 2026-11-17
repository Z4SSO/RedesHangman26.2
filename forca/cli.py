"""Interface de comandos do usuário (/peers, /games, /create, ...).

Dono: Pessoa C. Issues 03.3 e 03.4. Logger: "CLI". A leitura do teclado NÃO pode
bloquear o event loop: uma thread lê o stdin e entrega as linhas por uma fila.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Awaitable, Callable

from . import protocol as p
from .hangman import normalize_word
from .models import PlayerState
from .rendezvous_connection import RendezvousError

log = logging.getLogger("CLI")
game_log = logging.getLogger("Game")

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

# s entre consultas manuais ao Rendezvous (/peers e /reconnect). O limite é de 50 req/min POR IP,
# e os peers do run_local saem todos pelo mesmo IP: 5 s dá no máximo 12/min por peer.
MIN_DISCOVER_GAP = 5.0
GAMES_TIMEOUT = 3.0  # s que o /games espera cada vizinho; quem não responde não trava o comando
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
        self._current: asyncio.Future | None = None  # o comando em andamento
        self._last_discover = float("-inf")
        self.games_timeout = GAMES_TIMEOUT
        self._commands: dict[str, Callable[[list[str]], Awaitable[None]]] = {
            "/peers": self.cmd_peers, "/conn": self.cmd_conn, "/rtt": self.cmd_rtt,
            "/reconnect": self.cmd_reconnect, "/log": self.cmd_log, "/help": self.cmd_help,
            "/quit": self.cmd_quit,
            "/games": self.cmd_games, "/create": self.cmd_create, "/start": self.cmd_start,
            "/cancel": self.cmd_cancel, "/join": self.cmd_join, "/leave": self.cmd_leave,
            "/guess": self.cmd_guess, "/word": self.cmd_word, "/status": self.cmd_status,
        }

    # --- entrada ---
    def feed(self, line: str) -> None:
        """Entrega uma linha ao laço (usado pela thread do teclado e pelos testes)."""
        self._queue.put_nowait(line)

    def request_quit(self) -> None:
        """Ctrl+C / SIGTERM: mesmo caminho do /quit, e interrompe um comando que esteja
        pendurado na rede (senão o Ctrl+C só seria lido depois dele)."""
        self._quit = True
        if self._current is not None and not self._current.done():
            self._current.cancel()
        self.feed("/quit")  # acorda o laço se ele estiver esperando uma linha

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
            line = await self._queue.get()
            self._current = asyncio.ensure_future(self.execute(line))
            try:
                await self._current
            except asyncio.CancelledError:
                if not self._quit:  # cancelamento de fora, não do request_quit
                    raise
            finally:
                self._current = None

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
    def _rendezvous_gap(self) -> None:
        """Intervalo mínimo entre consultas manuais ao Rendezvous (/peers e /reconnect)."""
        wait = MIN_DISCOVER_GAP - (self._clock() - self._last_discover)
        if wait > 0:
            raise UsageError(f"aguarde {math.ceil(wait)} s entre consultas ao Rendezvous")
        self._last_discover = self._clock()

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
        self._rendezvous_gap()
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
        """/reconnect: reconciliação imediata com o Rendezvous (mesmo limite do /peers)."""
        self._rendezvous_gap()
        log.info("Reconciliando com o Rendezvous...")
        if await self.client.reconcile_now():
            log.info("Reconciliação concluída.")
        else:  # intervalo de 5 s do cliente ou DISCOVER que falhou
            log.warning("Reconciliação não feita (muito cedo ou o Rendezvous não respondeu).")

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


    # --- comandos de jogo ---
    def _require_idle(self) -> None:
        """Uma partida por vez (contrato 5.8); a parte B repete a checagem."""
        if self.client.host.active or self.client.player.active:
            raise UsageError("Você já está em uma partida (use /leave ou /cancel antes).")

    def _hangman_peers(self) -> list[str]:
        return [c.peer_id for c in self.client.table.connected() if p.FEATURE_HANGMAN in (c.features or [])]

    async def _game_lists(self, peer_ids: list[str]) -> dict[str, list[dict]]:
        """GAME_LIST a todos em paralelo; quem não responde (timeout) fica de fora."""
        me = self.client.cfg.peer_id

        async def ask(pid: str):
            msg = p.new_message("GAME_LIST", src=me, dst=pid)
            return await self.client.router.request(pid, msg, timeout=self.games_timeout)

        replies = await asyncio.gather(*(ask(pid) for pid in peer_ids))
        # r pode ser um ERROR (o vizinho recusou): trata como sem resposta
        return {pid: [g for g in r["games"] if isinstance(g, dict)]
                for pid, r in zip(peer_ids, replies) if r is not None and r.get("type") == "GAME_LIST_OK"}

    async def cmd_games(self, args: list[str]) -> None:
        """/games: GAME_LIST a todos os vizinhos com hangman e consolida as respostas."""
        peers = self._hangman_peers()
        if not peers:
            log.info("Nenhum vizinho conectado com a feature hangman.")
            return
        found = [g for games in (await self._game_lists(peers)).values() for g in games]
        open_games = [g for g in found if g.get("status") == "OPEN"]
        hidden = len(found) - len(open_games)  # RUNNING/FINISHED: a especificação lista só as abertas
        note = f"; {hidden} em andamento ou encerrada(s)" if hidden else ""
        if not open_games:
            log.info("Nenhuma partida aberta (%d vizinho(s) consultado(s)%s).", len(peers), note)
            return
        log.info("Partidas abertas:")
        for g in sorted(open_games, key=lambda g: str(g.get("game_id"))):
            log.info("  %s  host=%s  %d/%s jogadores  %s letras  %s vidas", g.get("game_id"), g.get("host"),
                     len(g.get("players") or []), g.get("max_players"), g.get("word_length"), g.get("lives"))
        if hidden:
            log.info("(%d em andamento ou encerrada(s) não listada(s))", hidden)

    async def _random_word(self) -> str:
        path = Path(self.client.cfg.words_file)

        def pick() -> str:
            words = []
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    words.append(normalize_word(line))
                except ValueError:
                    continue  # linha vazia ou palavra fora da regra 2
            if not words:
                raise UsageError(f"{path} não tem palavras válidas (a-z, 3 a 20 letras).")
            return random.choice(words)

        try:
            return await asyncio.to_thread(pick)
        except OSError as exc:
            raise UsageError(f"não consegui ler {path}: {exc.strerror}") from None

    async def cmd_create(self, args: list[str]) -> None:
        """/create <palavra> [max_players]  |  /create --random [max_players]"""
        usage = "uso: /create <palavra> [max_players]  ou  /create --random [max_players]"
        if not args:
            raise UsageError(usage)
        rest = args[1:]
        if len(rest) > 1:
            raise UsageError(usage)
        max_players = None
        if rest:
            if not (rest[0].isascii() and rest[0].isdigit()):  # "²" é isdigit() mas não vira int
                raise UsageError(usage)
            max_players = int(rest[0])
        self._require_idle()
        word = await self._random_word() if args[0] == "--random" else args[0]
        try:
            game_id = await self.client.host.create(word, max_players)
        except ValueError as exc:
            raise UsageError(f"não foi possível criar a partida: {exc}") from None
        except RuntimeError:
            raise UsageError("Você já está em uma partida (use /leave ou /cancel antes).") from None
        log.info("Partida criada: %s. Aguardando jogadores; use /start quando houver pelo menos um.", game_id)

    async def cmd_start(self, args: list[str]) -> None:
        try:
            await self.client.host.start()
        except ValueError:
            raise UsageError("A partida precisa de pelo menos 1 jogador para começar.") from None
        except RuntimeError:
            raise UsageError("Você não tem uma partida aberta para iniciar (use /create).") from None

    async def cmd_cancel(self, args: list[str]) -> None:
        if not self.client.host.active:
            raise UsageError("Você não está hospedando uma partida.")
        await self.client.host.cancel()
        log.info("Partida cancelada.")

    async def cmd_join(self, args: list[str]) -> None:
        """/join <host_peer_id>: acha o game_id com um GAME_LIST e manda só o JOIN.
        O JOIN não usa request(): o JOIN_ERR precisa chegar ao GamePlayer (contrato 5.4)."""
        if len(args) != 1:
            raise UsageError("uso: /join <host_peer_id>   (ex.: /join alice@CIC)")
        host_id = args[0] if "@" in args[0] else f"{args[0]}@{self.client.cfg.namespace}"
        self._require_idle()
        if host_id not in self._hangman_peers():
            raise UsageError(f"{host_id} não está conectado (veja /conn).")
        games = (await self._game_lists([host_id])).get(host_id)
        if games is None:
            raise UsageError(f"{host_id} não respondeu ao GAME_LIST.")
        # OPEN para entrar; RUNNING só adianta a quem volta (rejoin): o host decide.
        game = next((g for status in ("OPEN", "RUNNING") for g in games if g.get("status") == status), None)
        if game is None or not isinstance(game.get("game_id"), str):
            raise UsageError(f"{host_id} não tem partida aberta.")
        try:
            await self.client.player.join(host_id, game["game_id"])
        except RuntimeError:
            raise UsageError("Você já está em uma partida (use /leave ou /cancel antes).") from None
        log.info("Entrando na partida %s...", game["game_id"])

    async def cmd_leave(self, args: list[str]) -> None:
        if not self.client.player.active:
            if self.client.host.active:
                raise UsageError("Você é o host desta partida: use /cancel para encerrá-la.")
            raise UsageError("Você não está em uma partida como jogador.")
        await self.client.player.leave()
        log.info("Você saiu da partida.")

    async def cmd_guess(self, args: list[str]) -> None:
        """/guess <letra>: valida uma letra a-z (acento é tirado) antes de enviar."""
        if len(args) != 1:
            raise UsageError("uso: /guess <letra>")
        letter = "".join(c for c in unicodedata.normalize("NFKD", args[0].lower()) if not unicodedata.combining(c))
        if len(letter) != 1 or not ("a" <= letter <= "z"):
            raise UsageError("Letra inválida: use uma única letra de a a z.")
        self._require_playing()
        await self.client.player.guess_letter(letter)

    async def cmd_word(self, args: list[str]) -> None:
        """/word <palavra>: valida como a palavra secreta (a-z, 3 a 20) antes de enviar."""
        if len(args) != 1:
            raise UsageError("uso: /word <palavra>")
        try:
            word = normalize_word(args[0])
        except ValueError:
            raise UsageError("Palavra inválida: use só letras a-z, de 3 a 20.") from None
        self._require_playing()
        await self.client.player.guess_word(word)

    def _require_playing(self) -> None:
        if self.client.player.state != PlayerState.PLAYING:
            raise UsageError("Você não está em uma partida em andamento.")

    async def cmd_status(self, args: list[str]) -> None:
        """/status: quem está jogando vê a partida em que joga (o host pode ainda estar em FINISHED
        por 60 s); senão, a hospedada; senão, o texto "não está em uma partida"."""
        host, player = self.client.host, self.client.player
        for line in player.status_lines() if player.active else (host.status_lines() or player.status_lines()):
            game_log.info("%s", line.removeprefix("[Game] "))  # o logger já escreve [Game]


def _rtt(conn) -> str:
    return "-" if conn.rtt_ms is None else f"{conn.rtt_ms:.1f} ms"
