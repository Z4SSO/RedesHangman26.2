# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
"""Máquina de estados do jogador: JOIN, STATE com seq, GUESS, hash, host caiu.

Dono: Pessoa B. Issue 02.6. Logger: "Player" (linhas da especificação) e "Game"
(avisos para o usuário na tela).
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from . import protocol as p
from .config import Config
from .hangman import MAX_WORD, MIN_WORD, clean_text, word_hash
from .models import PlayerState, Sender

log = logging.getLogger("Player")
game_log = logging.getLogger("Game")

# shortcut: valor escolhido no olho (4 ciclos de PING de 30 s), não vem da especificação;
# ajustar se o cliente de referência demorar mais que isso para voltar.
REJOIN_WINDOW = 120.0


class GamePlayer:
    def __init__(self, cfg: Config, send: Sender, busy: Callable[[], bool] = lambda: False) -> None:
        """`busy()` diz se este peer já é host de uma partida (exclusão mútua, contrato 5.8);
        quem liga os objetos passa `busy=lambda: host.active`."""
        self.cfg = cfg
        self.send = send
        self.busy = busy
        # (host, game_id, campos do GAME_START, instante da queda) guardados para o rejoin
        self._last_game: tuple[str, str, dict, float] | None = None
        self._clear()

    def _clear(self) -> None:
        self.state = PlayerState.IDLE
        self.host_id: str | None = None
        self.game_id: str | None = None
        self.seq = 0
        self.word_hash: str | None = None
        self.lives_total = self.cfg.lives
        self.lives = self.cfg.lives
        self.masked = ""
        self.wrong: list[str] = []
        self.players: list[str] = []
        self.turn: str | None = None
        self.turn_timeout = self.cfg.turn_timeout
        self._turn_started = 0.0
        # shortcut: dois last_guess idênticos em seguida (mesma palavra errada duas vezes)
        # são anunciados uma vez só; o STATE não traz id da jogada para distinguir.
        self._shown_last: dict | None = None

    @property
    def active(self) -> bool:
        return self.state != PlayerState.IDLE

    def _mine(self, msg: dict) -> bool:
        """Só vale mensagem do host da partida atual."""
        ok = self.active and msg.get("src") == self.host_id and msg.get("game_id") == self.game_id
        if not ok:
            log.debug("ignored %s from %s (game %s)", msg.get("type"), msg.get("src"), msg.get("game_id"))
        return ok

    async def _invalid_state(self, msg: dict) -> None:
        """GAME_START/STATE de quem não é o host da partida atual (decisão 14)."""
        err = p.make_error(msg, p.ErrorCode.INVALID_STATE, "not the host of the current game",
                           src=self.cfg.peer_id)
        await self.send(msg["src"], err)

    async def _send(self, type_: str, **fields) -> bool:
        return await self.send(
            self.host_id, p.new_message(type_, src=self.cfg.peer_id, dst=self.host_id, **fields)
        )

    # --- comandos locais (CLI) ---
    async def join(self, host_peer_id: str, game_id: str) -> None:
        """Envia JOIN. O estado vira JOINED já aqui (ocupa o peer); JOIN_ERR desfaz."""
        await self._join(host_peer_id, game_id, None)

    async def _join(self, host_peer_id: str, game_id: str, restore: dict | None) -> None:
        """`restore` (só o rejoin): campos do GAME_START que o JOIN_OK/STATE não repetem."""
        if self.active or self.busy():
            raise RuntimeError("already in a game")
        self._clear()
        self._last_game = None  # um /join novo invalida o rejoin pendente
        self.host_id, self.game_id, self.state = host_peer_id, game_id, PlayerState.JOINED
        for key, value in (restore or {}).items():
            setattr(self, key, value)
        if not await self._send("JOIN", game_id=game_id):
            game_log.warning("Host %s is not connected", host_peer_id)
            self._clear()

    async def leave(self) -> None:
        """Sai sem esperar o LEAVE_OK (o /quit não pode travar se o host caiu)."""
        if not self.active:
            return
        await self._send("LEAVE", game_id=self.game_id)
        self._last_game = None
        self._clear()

    async def guess_letter(self, letter: str) -> None:
        await self._guess(letter=letter)

    async def guess_word(self, word: str) -> None:
        await self._guess(word=word)

    async def _guess(self, **what) -> None:
        # Não checa a vez: o host responde not_your_turn (cenário 4).
        if self.state != PlayerState.PLAYING:
            game_log.warning("No game in progress")
        elif not await self._send("GUESS", game_id=self.game_id, **what):
            game_log.warning("Host %s is not connected", self.host_id)

    # --- chat (bônus 05.2) ---
    async def on_chat(self, conn, msg: dict) -> None:
        """CHAT repassado pelo host da partida atual; de qualquer outro é ignorado."""
        if not self._mine(msg):
            return
        text = clean_text(msg["text"], p.CHAT_MAX_LEN)
        if text:
            game_log.info("%s: %s", clean_text(msg.get("from") or msg["src"], 40), text)

    async def chat(self, text: str) -> None:
        """Envia ao host, que difunde aos demais."""
        text = clean_text(text, p.CHAT_MAX_LEN)
        if not self.active:
            game_log.warning("No game in progress")
        elif not text:
            return
        elif await self._send("CHAT", game_id=self.game_id, text=text):
            game_log.info("%s: %s", "você", text)
        else:
            game_log.warning("Host %s is not connected", self.host_id)

    def status_lines(self) -> list[str]:
        """Linhas do /status (formato mínimo da especificação)."""
        if not self.active:
            return ["[Game] Você não está em uma partida."]
        running = self.state == PlayerState.PLAYING
        lines = [
            f"[Game] {self.game_id}  (host: {self.host_id})  "
            f"status: {'RUNNING' if running else 'OPEN'}"
        ]
        if not running:
            return lines + [f"[Game] Aguardando o host iniciar. Jogadores: {', '.join(self.players)}"]
        lines.append(
            f"[Game] Palavra: {' '.join(self.masked)}     "
            f"Vidas: {self.lives} / {self.lives_total}     "
            f"Erradas: {', '.join(self.wrong) or '-'}"
        )
        turn = f"{self.turn} (você)" if self.turn == self.cfg.peer_id else str(self.turn)
        left = max(0, int(self.turn_timeout - (time.monotonic() - self._turn_started)))
        lines.append(
            f"[Game] Jogadores: {', '.join(self.players)}   Vez de: {turn}  — {left} s restantes"
        )
        return lines

    # --- handlers de mensagens ---
    async def on_join_ok(self, conn, msg: dict) -> None:
        if self._mine(msg):
            self.players = list(msg["players"])
            game_log.info(
                "Joined %s (%s)", self.game_id, "rejoin" if msg["rejoin"] else f"players: {', '.join(self.players)}"
            )

    async def on_join_err(self, conn, msg: dict) -> None:
        if self._mine(msg):
            game_log.warning("Cannot join %s: %s", self.game_id, msg["reason"])
            self._clear()

    async def on_leave_ok(self, conn, msg: dict) -> None:
        log.debug("LEAVE_OK from %s", msg.get("src"))

    async def on_game_start(self, conn, msg: dict) -> None:
        if not self._mine(msg):
            return await self._invalid_state(msg)
        length = msg["word_length"]
        if not (isinstance(length, int) and MIN_WORD <= length <= MAX_WORD):
            log.warning("GAME_START ignored: word_length=%r out of range", length)
            return
        self.word_hash = msg["word_hash"]
        self.lives = self.lives_total = msg["lives"]
        self.players = list(msg["players"])
        self.turn_timeout = msg["turn_timeout"]
        self.masked = "_" * msg["word_length"]
        self.wrong, self.seq, self.state = [], 0, PlayerState.PLAYING
        game_log.info("Game started: %d letters, %d lives", msg["word_length"], self.lives)

    async def on_state(self, conn, msg: dict) -> None:
        """Descarta se seq <= último aplicado (log DEBUG)."""
        if not self._mine(msg):
            return await self._invalid_state(msg)
        seq = msg["seq"]
        if not isinstance(seq, int) or seq <= self.seq:
            log.debug("STATE seq=%s ignored (already at seq=%d)", seq, self.seq)
            return
        self.seq = seq
        self.masked, self.wrong = msg["masked"], list(msg["wrong_letters"])
        self.lives, self.turn, self.players = msg["lives"], msg["turn"], list(msg["players"])
        self.state = PlayerState.PLAYING  # cobre o rejoin, que chega sem GAME_START
        self._turn_started = time.monotonic()
        mine = self.turn == self.cfg.peer_id
        log.info("STATE seq=%d applied: %s lives=%d turn=%s%s", seq, self.masked, self.lives,
                 self.turn, " (você)" if mine else "")  # Exemplo de Sessão da especificação
        last = msg.get("last_guess")
        if isinstance(last, dict) and last != self._shown_last:  # LEAVE/queda repetem o último
            self._shown_last = last
            what =f"letter={last['letter']}" if "letter" in last else (
                f"word={last['word']}" if "word" in last else "timeout")
            game_log.info("%s: %s", last.get("player"), what)
        if mine and self.lives > 0 and "_" in self.masked:  # STATE final (host de terceiros): GAME_OVER vem a seguir
            game_log.info("É a sua vez! Use /guess <letra> ou /word <palavra>")

    async def on_guess_result(self, conn, msg: dict) -> None:
        if not self._mine(msg):
            return
        if msg["accepted"]:
            game_log.info("Jogada aceita: %s", "correta" if msg.get("correct") else "errada")
        else:
            game_log.warning("Jogada recusada: %s", msg.get("reason"))

    async def on_game_over(self, conn, msg: dict) -> None:
        """Confere sha256(word) == word_hash; divergência -> WARNING
        'host cheated: hash mismatch'."""
        if not self._mine(msg):
            return
        word = msg.get("word")
        if not isinstance(word, str) or self.word_hash is None:
            check = "hash not verified"
        elif word_hash(word) == self.word_hash:
            check = "hash OK"
        else:
            check = "hash MISMATCH"
            log.warning("host cheated: hash mismatch")
        log.info(
            "GAME_OVER %s word=%s winner=%s — %s", msg["result"], word, msg.get("winner"), check
        )
        if msg.get("scores"):
            game_log.info("Placar: %s", ", ".join(f"{k}={v}" for k, v in msg["scores"].items()))
        if msg["result"] == "ABORTED":
            game_log.info("Partida abortada pelo host (%s)", msg.get("reason", "-"))
        self._last_game = None
        self._clear()

    # --- eventos da PeerTable ---
    async def on_peer_stale(self, peer_id: str) -> None:
        """Se for o host: '[Game] Host X unreachable — game aborted', volta a IDLE."""
        if not self.active or peer_id != self.host_id:
            return
        if self.state == PlayerState.PLAYING:
            self._last_game = (self.host_id, self.game_id, {  # rejoin se o host voltar
                "word_hash": self.word_hash, "lives_total": self.lives_total,
                "turn_timeout": self.turn_timeout, "_shown_last": self._shown_last,
            }, time.monotonic())
        log.warning("Host %s unreachable — game aborted", peer_id)
        game_log.warning("Host %s unreachable — game aborted", peer_id)
        self._clear()

    async def on_peer_connected(self, peer_id: str) -> None:
        """Reenvia JOIN ao host que voltou numa partida em andamento (rejoin)."""
        if not self._last_game or peer_id != self._last_game[0]:
            return
        host, gid, restore, since = self._last_game
        if self.active or self.busy() or time.monotonic() - since > REJOIN_WINDOW:
            self._last_game = None  # virou host/jogador de outra partida, ou passou da janela
            log.debug("rejoin to %s dropped", host)
            return
        await self._join(host, gid, restore)
