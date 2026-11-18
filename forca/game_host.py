# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
"""Máquina de estados do host: lobby, turnos, validação de jogadas, STATE.

Dono: Pessoa B. Issues 02.2 a 02.5. Logger: "Host". Mensagens `[Game]` para a
tela via logger "Game". Usa `hangman.Hangman` para as regras (nada de rede lá).

Regra de concorrência: todo `await` é um ponto em que outro handler pode rodar.
Por isso o estado muda ANTES do await (turno avança, partida encerra em `_close`)
e, depois de cada await, o código confere `self.status` antes de continuar.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Callable

from . import protocol as p
from .config import Config
from .hangman import Hangman, clean_text, normalize_word, word_hash
from .models import GameStatus, Sender
from .protocol import GuessRejectReason as Reject
from .protocol import JoinErrReason as JoinErr

log = logging.getLogger("Host")
game_log = logging.getLogger("Game")

FINISHED_TTL = 60.0  # decisão 7 do contrato: GAME_LIST_OK mostra FINISHED por 60 s


class GameHost:
    def __init__(self, cfg: Config, send: Sender, busy: Callable[[], bool] = lambda: False) -> None:
        """`busy()` diz se este peer já joga como jogador (exclusão mútua, contrato 5.8);
        quem liga os objetos passa `busy=lambda: player.active`."""
        self.cfg = cfg
        self.send = send
        self.busy = busy
        self._expire_task: asyncio.Task | None = None
        self._turn_task: asyncio.Task | None = None  # o timer mais recente
        # Todo timer vivo, inclusive o que já foi substituído mas ainda está difundindo:
        # é o que _reset/_close cancelam (toda tarefa é guardada e cancelada no stop()).
        self._turn_tasks: set[asyncio.Task] = set()
        self._turn_started = 0.0
        self._reset()

    def _reset(self) -> None:
        self._cancel_turn_timer()
        self.status = GameStatus.IDLE
        self.game_id: str | None = None
        self._game: Hangman | None = None
        self._players: list[str] = []
        self._max_players = self.cfg.max_players
        self._seq = 0
        self._turn: str | None = None
        self._scores: dict[str, int] = {}
        self._last_guess: dict | None = None

    @property
    def active(self) -> bool:
        """True em OPEN ou RUNNING (o peer não pode entrar em outra partida)."""
        return self.status in (GameStatus.OPEN, GameStatus.RUNNING)

    # --- envio ---
    async def _send(self, dst: str, type_: str, **fields) -> bool:
        return await self.send(dst, p.new_message(type_, src=self.cfg.peer_id, dst=dst, **fields))

    async def _reply(self, request: dict, type_: str, **fields) -> bool:
        return await self.send(request["src"], p.reply(request, type_, **fields))

    async def _invalid_state(self, request: dict, text: str) -> bool:
        """Mensagem válida em contexto errado: quem responde é o handler (contrato 5.4)."""
        err = p.make_error(request, p.ErrorCode.INVALID_STATE, text, src=self.cfg.peer_id)
        return await self.send(request["src"], err)

    def _cancel_expire(self) -> None:
        if self._expire_task is not None:
            self._expire_task.cancel()
            self._expire_task = None

    # --- comandos locais (CLI) ---
    async def create(self, word: str, max_players: int | None = None) -> str:
        """Normaliza a palavra, gera game_id `<host>/<8 hex>`, status OPEN.
        Devolve o game_id. ValueError se a palavra for inválida."""
        if self.active or self.busy():
            raise RuntimeError("already in a game")
        game = Hangman(word, self.cfg.lives)  # ValueError se inválida (regra 2)
        if max_players is not None and max_players < 1:
            raise ValueError("max_players must be >= 1")
        self._cancel_expire()
        self._reset()
        self._game = game
        self._max_players = max_players or self.cfg.max_players
        self.game_id = f"{self.cfg.peer_id}/{secrets.token_hex(4)}"
        self.status = GameStatus.OPEN
        log.info(
            "Game %s created (word_length=%d, lives=%d)",
            self.game_id, game.word_length, game.lives,
        )
        return self.game_id

    async def adopt(self, game_id: str, players: list[str], word: str, lives: int) -> None:
        """Bônus 05.1: assume a partida de um host que caiu. Mesmo `game_id`, palavra nova
        (a original só o host antigo conhecia) e as vidas do último STATE; já inicia."""
        if self.active or self.busy():
            raise RuntimeError("already in a game")
        game = Hangman(word, lives)
        self._cancel_expire()
        self._reset()
        self._game, self.game_id, self.status = game, game_id, GameStatus.OPEN
        self._players, self._max_players = list(players), max(len(players), 1)
        log.info("Game %s adopted as new host (word_length=%d, lives=%d, players=%d)",
                 game_id, game.word_length, game.lives, len(players))
        await self.start()

    async def start(self) -> None:
        """OPEN -> RUNNING. Exige >=1 jogador. Envia GAME_START e STATE seq=1."""
        if self.status != GameStatus.OPEN:
            raise RuntimeError("no open game to start")
        if not self._players:
            raise ValueError("need at least 1 player to start")
        g = self._game
        self.status = GameStatus.RUNNING
        self._scores = {pl: 0 for pl in self._players}
        self._turn = self._players[0]
        self._seq = 0
        self._last_guess = None
        for pl in list(self._players):
            await self._send(
                pl, "GAME_START", game_id=self.game_id, players=list(self._players),
                lives=g.lives, word_length=g.word_length,
                word_hash=word_hash(g.word), turn_timeout=self.cfg.turn_timeout,
            )
        if self.status != GameStatus.RUNNING:
            return  # o último jogador saiu durante os GAME_START
        await self._broadcast_state()
        self._log_turn()

    async def cancel(self) -> None:
        """GAME_OVER ABORTED reason='host_shutdown' a todos. Passa por FINISHED
        (60 s), como no diagrama da especificação."""
        if self.active:
            await self._finish("ABORTED", reason="host_shutdown")

    async def shutdown(self) -> None:
        """Chamado no /quit: igual a cancel() se houver partida ativa."""
        await self.cancel()
        self._cancel_expire()
        self._reset()

    def describe(self) -> dict | None:
        """Entrada de `games[]` do GAME_LIST_OK, ou None se não há partida."""
        if self.status == GameStatus.IDLE:
            return None
        return {
            "game_id": self.game_id, "host": self.cfg.peer_id,
            "status": self.status.value, "players": list(self._players),
            "max_players": self._max_players, "lives": self._game.lives,
            "word_length": self._game.word_length,
        }

    def status_lines(self) -> list[str]:
        """Linhas do /status do host, no formato mínimo da especificação ([] sem partida)."""
        if self.status == GameStatus.IDLE:
            return []
        g = self._game
        lines = [
            f"[Game] {self.game_id}  (host: {self.cfg.peer_id})  status: {self.status.value}",
            f"[Game] Palavra: {' '.join(g.masked)} (secreta: {g.word})     "
            f"Vidas: {g.lives} / {self.cfg.lives}     "
            f"Erradas: {', '.join(g.wrong_letters) or '-'}",
        ]
        who = f"[Game] Jogadores: {', '.join(self._players) or '-'}"
        if self.status == GameStatus.RUNNING:
            left = max(0, int(self.cfg.turn_timeout - (time.monotonic() - self._turn_started)))
            who += f"   Vez de: {self._turn}  — {left} s restantes"
        return lines + [who]

    # --- handlers de mensagens (registrados no MessageRouter) ---
    async def on_game_list(self, conn, msg: dict) -> None:
        game = self.describe()
        await self._reply(msg, "GAME_LIST_OK", games=[game] if game else [])

    async def on_join(self, conn, msg: dict) -> None:
        src, gid = msg["src"], msg["game_id"]

        async def err(reason: str) -> None:
            await self._reply(msg, "JOIN_ERR", game_id=gid, reason=reason)

        if self.status == GameStatus.IDLE or gid != self.game_id:
            return await err(JoinErr.UNKNOWN_GAME)
        if self.status == GameStatus.FINISHED:
            return await err(JoinErr.GAME_FINISHED)
        if src in self._players:
            if self.status != GameStatus.RUNNING:
                return await err(JoinErr.ALREADY_JOINED)
            # Já era jogador e ainda consta (o host não viu a queda): rejoin, sem mudar a
            # ordem e sem novo seq, só o STATE corrente para quem voltou.
            await self._reply(msg, "JOIN_OK", game_id=gid, players=list(self._players), rejoin=True)
            if self.status == GameStatus.RUNNING and src in self._players:
                await self._send(src, "STATE", **self._state_fields())
            return
        if self.status == GameStatus.RUNNING:
            if src not in self._scores:  # só quem já jogou pode voltar (rejoin)
                return await err(JoinErr.GAME_RUNNING)
            self._players.append(src)  # volta ao fim do rodízio (decisão 3)
            log.info("%s rejoined (%d/%d)", src, len(self._players), self._max_players)
            await self._reply(msg, "JOIN_OK", game_id=gid, players=list(self._players), rejoin=True)
            return await self._broadcast_state()
        if len(self._players) >= self._max_players:
            return await err(JoinErr.GAME_FULL)
        self._players.append(src)
        log.info("%s joined (%d/%d)", src, len(self._players), self._max_players)
        await self._reply(msg, "JOIN_OK", game_id=gid, players=list(self._players), rejoin=False)

    async def on_leave(self, conn, msg: dict) -> None:
        await self._reply(msg, "LEAVE_OK", game_id=msg["game_id"])
        if msg["game_id"] == self.game_id:
            await self._remove_player(msg["src"])

    async def on_guess(self, conn, msg: dict) -> None:
        """Rejeição não gera STATE nem consome o turno (regra do protocolo)."""
        src, gid = msg["src"], msg["game_id"]

        async def reject(reason: str) -> None:
            await self._reply(msg, "GUESS_RESULT", game_id=gid, accepted=False, reason=reason)

        # Decisão 15: sem partida, outra partida ou quem não é jogador -> ERROR invalid_state;
        # partida existente mas não RUNNING -> game_not_running.
        if self.status == GameStatus.IDLE or gid != self.game_id or src not in self._players:
            return await self._invalid_state(msg, "no such game or not a player")
        if self.status != GameStatus.RUNNING:
            return await reject(Reject.GAME_NOT_RUNNING)
        if src != self._turn:
            return await reject(Reject.NOT_YOUR_TURN)
        g = self._game
        if "letter" in msg:
            out = g.guess_letter(msg["letter"])
            shown = {"letter": msg["letter"].strip().lower()} if out.accepted else {}
        else:
            out = g.guess_word(msg["word"])
            shown = {"word": normalize_word(msg["word"])} if out.accepted else {}
        if not out.accepted:
            return await reject(out.reason)

        self._scores[src] = self._scores.get(src, 0) + out.revealed
        self._last_guess = {"player": src, **shown, "correct": out.correct}
        kind, value = next(iter(shown.items()))
        log.info(
            "GUESS %s %s=%s → %s, masked=%s",
            src, kind, value, "correct" if out.correct else "wrong", g.masked,
        )
        # Tudo que muda o estado acontece ANTES do primeiro await: um segundo GUESS
        # (do mesmo jogador ou de outro) já encontra o turno novo ou a partida encerrada.
        ending = None
        if g.is_won:
            ending = self._close("WON", winner=src)
        elif g.is_lost:
            ending = self._close("LOST")
        else:
            self._advance_turn()
        await self._reply(msg, "GUESS_RESULT", game_id=gid, accepted=True, correct=out.correct)
        if ending:  # a ordem GUESS_RESULT -> GAME_OVER se mantém
            return await self._send_game_over(*ending)
        if self.status == GameStatus.RUNNING:  # pode ter acabado durante o await
            await self._broadcast_state()
            self._log_turn()

    # --- chat (bônus 05.2) ---
    async def on_chat(self, conn, msg: dict) -> None:
        """CHAT de um jogador: mostra e repassa aos outros com `from` (o src do repasse é o host)."""
        src = msg["src"]
        if not self.active or msg["game_id"] != self.game_id or src not in self._players:
            await self._invalid_state(msg, "no such game or not a player")
            return
        await self._relay_chat(src, msg["text"], skip=src)

    async def chat(self, text: str) -> None:
        """O próprio host fala: vai a todos os jogadores."""
        if not self.active:
            game_log.warning("No game in progress")
            return
        await self._relay_chat(self.cfg.peer_id, text)

    async def _relay_chat(self, author: str, raw: str, skip: str | None = None) -> None:
        text = clean_text(raw, p.CHAT_MAX_LEN)
        if not text:
            return
        game_log.info("%s: %s", "você" if author == self.cfg.peer_id else author, text)
        for pl in list(self._players):
            if pl != skip:
                await self._send(pl, "CHAT", game_id=self.game_id, text=text, **{"from": author})

    # --- eventos da PeerTable ---
    async def on_peer_stale(self, peer_id: str) -> None:
        """Jogador caiu: remove, passa o turno se era a vez dele, difunde STATE."""
        if peer_id in self._players:
            log.warning("Player %s STALE — removed from game", peer_id)
            await self._remove_player(peer_id)

    # --- internos ---
    def _state_fields(self) -> dict:
        g = self._game
        return {
            "game_id": self.game_id, "seq": self._seq, "masked": g.masked,
            "wrong_letters": g.wrong_letters, "lives": g.lives, "turn": self._turn,
            "players": list(self._players), "last_guess": self._last_guess,
        }

    async def _broadcast_state(self) -> None:
        """Único lugar que incrementa o seq (1, 2, 3, ...). Nunca depois do GAME_OVER."""
        if self.status != GameStatus.RUNNING:
            return
        self._seq += 1
        self._restart_turn_timer()  # o relógio do turno recomeça a cada STATE
        fields = self._state_fields()
        for pl in list(self._players):
            if self.status != GameStatus.RUNNING:
                break  # a partida acabou no meio da difusão
            await self._send(pl, "STATE", **fields)

    def _cancel_turn_timer(self) -> None:
        self._turn_task = None
        # O timer que estourou chama _broadcast_state, que reinicia o timer: ele não pode
        # cancelar a si mesmo no meio da difusão. Se o shutdown chegar durante ela, quem
        # cancela é o outro lado (a tarefa atual então é a do shutdown, não a do timer).
        for task in list(self._turn_tasks):
            if task is not asyncio.current_task():
                task.cancel()

    def _restart_turn_timer(self) -> None:
        """Só o timer mais recente vale (`_turn_task`); todos ficam em `_turn_tasks`."""
        self._cancel_turn_timer()
        self._turn_started = time.monotonic()
        self._turn_task = task = asyncio.create_task(self._turn_timer(self._seq))
        self._turn_tasks.add(task)
        task.add_done_callback(self._turn_tasks.discard)

    async def _turn_timer(self, seq: int) -> None:
        """Regra 7: sem jogada em `turn_timeout` s, passa o turno (sem custar vida) e difunde
        STATE com last_guess {player, timeout: true}. Só age se nada mudou desde o `seq`."""
        await asyncio.sleep(self.cfg.turn_timeout)
        if self.status != GameStatus.RUNNING or self._seq != seq:
            return
        try:
            log.info("Turn timeout for %s — skipping", self._turn)
            self._last_guess = {"player": self._turn, "timeout": True}
            self._advance_turn()  # a mesma rotina de uma jogada aceita
            await self._broadcast_state()
            if self.status == GameStatus.RUNNING:  # pode ter acabado durante a difusão
                self._log_turn()
        except Exception:  # um timer morto travaria a partida em silêncio
            log.exception("turn timer failed")

    def _log_turn(self) -> None:
        log.info("Turn: %s (timeout %d s)", self._turn, self.cfg.turn_timeout)

    def _advance_turn(self) -> None:
        """Regra 4: round-robin, independente de acerto."""
        i = self._players.index(self._turn) if self._turn in self._players else -1
        self._turn = self._players[(i + 1) % len(self._players)]

    async def _remove_player(self, pid: str) -> None:
        """Regra 10. O score de quem saiu é mantido (decisão 6)."""
        if pid not in self._players:
            return
        i = self._players.index(pid)
        was_turn = self._turn == pid
        self._players.remove(pid)
        if self.status != GameStatus.RUNNING:
            return
        if not self._players:
            return await self._finish("ABORTED", reason="no_players")
        if was_turn:
            self._turn = self._players[i % len(self._players)]
        await self._broadcast_state()
        if was_turn and self.status == GameStatus.RUNNING:
            self._log_turn()

    def _close(self, result: str, winner: str | None = None, reason: str | None = None) -> tuple[list[str], dict]:
        """Encerra SEM await: a partir daqui nenhum handler vê RUNNING.
        Devolve (destinatários, campos do GAME_OVER) para `_send_game_over`."""
        g = self._game
        over = {
            "game_id": self.game_id, "result": result, "word": g.word,
            "winner": winner, "scores": dict(self._scores),
        }
        if reason:
            over["reason"] = reason
        players = list(self._players)
        log.info(
            "Game %s finished: %s%s", self.game_id, result,
            f" by {winner}" if winner else f" ({reason})" if reason else "",
        )
        self._turn = None
        self._cancel_turn_timer()
        self._cancel_expire()
        # Todo término, inclusive ABORTED, passa por FINISHED (60 s) e depois IDLE (decisão 19;
        # a 12 trata do caso no_players).
        self.status = GameStatus.FINISHED
        self._expire_task = asyncio.create_task(self._expire(self.game_id))
        return players, over

    async def _send_game_over(self, players: list[str], over: dict) -> None:
        for pl in players:
            await self._send(pl, "GAME_OVER", **over)

    async def _finish(self, result: str, winner: str | None = None, reason: str | None = None) -> None:
        await self._send_game_over(*self._close(result, winner, reason))

    async def _expire(self, game_id: str) -> None:
        await asyncio.sleep(FINISHED_TTL)
        if self.game_id == game_id and self.status == GameStatus.FINISHED:
            self._reset()
