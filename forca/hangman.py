"""Lógica pura do jogo da forca. NÃO importe nada de rede aqui (asyncio, socket...).

Dono: Pessoa B. Issue 02.1. Regras: especificação, seção "Regras do jogo".
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


def normalize_word(raw: str) -> str:
    """Minúsculas e sem acentos. Levanta ValueError se sobrar algo fora de a-z
    ou se o tamanho não estiver entre 3 e 20. (Issue 02.1)"""
    raise NotImplementedError("issue 02.1")


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
        raise NotImplementedError("issue 02.1")

    @property
    def masked(self) -> str:
        """Ex.: 'b_n_n_'. Uma posição por caractere, '_' para as ocultas."""
        raise NotImplementedError("issue 02.1")

    @property
    def wrong_letters(self) -> list[str]:
        raise NotImplementedError("issue 02.1")

    @property
    def lives(self) -> int:
        raise NotImplementedError("issue 02.1")

    @property
    def word_length(self) -> int:
        raise NotImplementedError("issue 02.1")

    @property
    def is_won(self) -> bool:
        raise NotImplementedError("issue 02.1")

    @property
    def is_lost(self) -> bool:
        raise NotImplementedError("issue 02.1")

    def guess_letter(self, letter: str) -> GuessOutcome:
        raise NotImplementedError("issue 02.1")

    def guess_word(self, word: str) -> GuessOutcome:
        """Palpite certo revela tudo (revealed = letras ainda ocultas).
        Errado custa 1 vida e não revela nada."""
        raise NotImplementedError("issue 02.1")
