"""Lógica pura do jogo da forca. NÃO importe nada de rede aqui (asyncio, socket...).

Dono: Pessoa B. Issue 02.1. Regras: especificação, seção "Regras do jogo".
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass

MIN_WORD, MAX_WORD = 3, 20


def normalize_word(raw: str) -> str:
    """Minúsculas e sem acentos. Levanta ValueError se sobrar algo fora de a-z
    ou se o tamanho não estiver entre 3 e 20. (Regra 2 do jogo)"""
    decomposed = unicodedata.normalize("NFKD", raw.strip().lower())
    word = "".join(c for c in decomposed if not unicodedata.combining(c))
    if not (word.isascii() and word.isalpha()):
        raise ValueError(f"invalid characters in word {raw!r}")
    if not MIN_WORD <= len(word) <= MAX_WORD:
        raise ValueError(f"word length must be {MIN_WORD}..{MAX_WORD}")
    return word


def word_hash(normalized_word: str) -> str:
    """SHA-256 hexadecimal minúsculo da palavra já normalizada."""
    return hashlib.sha256(normalized_word.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GuessOutcome:
    """Resultado de uma jogada. `accepted=False` não consome turno nem vida."""

    accepted: bool
    correct: bool = False
    reason: str | None = None  # letter_already_used | invalid_letter | invalid_word
    revealed: int = 0  # ocorrências reveladas (para a pontuação)


class Hangman:
    """Estado de UMA partida: palavra secreta, máscara, letras erradas, vidas."""

    def __init__(self, word: str, lives: int = 6) -> None:
        self._word = normalize_word(word)
        self._lives = lives
        self._revealed: set[str] = set()
        self._tried: set[str] = set()
        self._wrong: list[str] = []

    @property
    def word(self) -> str:
        """Palavra secreta (só o host usa; vai no GAME_OVER)."""
        return self._word

    @property
    def masked(self) -> str:
        """Ex.: 'b_n_n_'. Uma posição por caractere, '_' para as ocultas."""
        return "".join(c if c in self._revealed else "_" for c in self._word)

    @property
    def wrong_letters(self) -> list[str]:
        return list(self._wrong)

    @property
    def lives(self) -> int:
        return self._lives

    @property
    def word_length(self) -> int:
        return len(self._word)

    @property
    def is_won(self) -> bool:
        return "_" not in self.masked

    @property
    def is_lost(self) -> bool:
        return self._lives == 0

    def guess_letter(self, letter: str) -> GuessOutcome:
        """Regra 5: certa revela todas as ocorrências; errada custa 1 vida;
        repetida é rejeitada sem custo."""
        letter = letter.strip().lower() if isinstance(letter, str) else ""
        if len(letter) != 1 or not ("a" <= letter <= "z"):
            return GuessOutcome(False, reason="invalid_letter")
        if letter in self._tried:
            return GuessOutcome(False, reason="letter_already_used")
        self._tried.add(letter)
        if letter in self._word:
            self._revealed.add(letter)
            return GuessOutcome(True, correct=True, revealed=self._word.count(letter))
        self._wrong.append(letter)
        self._lives -= 1
        return GuessOutcome(True, correct=False)

    def guess_word(self, word: str) -> GuessOutcome:
        """Regra 6: palpite certo revela tudo (revealed = letras ainda ocultas).
        Errado custa 1 vida e não revela nada."""
        try:
            guess = normalize_word(word)
        except (ValueError, AttributeError):
            return GuessOutcome(False, reason="invalid_word")
        if guess == self._word:
            hidden = self.masked.count("_")
            self._revealed.update(self._word)
            return GuessOutcome(True, correct=True, revealed=hidden)
        self._lives -= 1
        return GuessOutcome(True, correct=False)
