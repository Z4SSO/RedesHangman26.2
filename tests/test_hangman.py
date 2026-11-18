# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
import hashlib

import pytest

from forca.hangman import Hangman, clean_text, normalize_word, word_hash


def test_normalize_removes_accents_and_lowercases():
    assert normalize_word("Açaí") == "acai"
    assert normalize_word("  BANANA ") == "banana"


@pytest.mark.parametrize("bad", ["ab", "co-op", "a" * 21, "dois nomes", "abc1", ""])
def test_normalize_rejects_invalid(bad):
    with pytest.raises(ValueError):
        normalize_word(bad)


def test_hash_known_values():
    assert word_hash("casa") == hashlib.sha256(b"casa").hexdigest()
    # exemplo do GAME_START da especificação
    assert word_hash("banana") == "b493d48364afe44d11c0165cf470a4164d1e2609911ef998be868d46ade3de4e"


def test_correct_letter_reveals_all_occurrences():
    g = Hangman("banana")
    out = g.guess_letter("a")
    assert (out.accepted, out.correct, out.revealed) == (True, True, 3)
    assert g.masked == "_a_a_a"
    assert g.lives == 6


def test_wrong_letter_costs_life_and_is_listed_in_order():
    g = Hangman("banana")
    g.guess_letter("z")
    g.guess_letter("e")
    assert g.wrong_letters == ["z", "e"]
    assert g.lives == 4


def test_repeated_letter_rejected_without_cost():
    g = Hangman("banana")
    g.guess_letter("a")
    g.guess_letter("z")
    for letter in ("a", "z"):
        out = g.guess_letter(letter)
        assert (out.accepted, out.reason) == (False, "letter_already_used")
    assert g.lives == 5


@pytest.mark.parametrize("bad", ["1", "ab", "", "-", "é"])
def test_invalid_letter(bad):
    g = Hangman("banana")
    out = g.guess_letter(bad)
    assert (out.accepted, out.reason) == (False, "invalid_letter")
    assert g.lives == 6


def test_win_by_letters():
    g = Hangman("casa")
    for letter in "cas":
        g.guess_letter(letter)
    assert g.is_won and not g.is_lost
    assert g.masked == "casa"


def test_win_by_word_reveals_remaining():
    g = Hangman("banana")
    g.guess_letter("a")
    out = g.guess_word("Banana")
    assert (out.accepted, out.correct, out.revealed) == (True, True, 3)
    assert g.is_won


def test_wrong_word_costs_life_and_reveals_nothing():
    g = Hangman("banana")
    out = g.guess_word("bananas")
    assert (out.accepted, out.correct, out.revealed) == (True, False, 0)
    assert g.lives == 5 and g.masked == "______"


def test_invalid_word_is_free():
    g = Hangman("banana")
    out = g.guess_word("co-op")
    assert (out.accepted, out.reason) == (False, "invalid_word")
    assert g.lives == 6


def test_lost_exactly_when_lives_hit_zero():
    g = Hangman("banana", lives=2)
    g.guess_letter("z")
    assert not g.is_lost
    g.guess_letter("y")
    assert g.is_lost and g.lives == 0


def test_secret_word_is_normalized():
    g = Hangman("Açaí")
    assert g.word == "acai" and g.word_length == 4


def test_clean_text_neutralizes_control_characters_and_truncates():
    assert clean_text("oi\n[Host] falso\r\x1b[31m!") == "oi [Host] falso  [31m!"
    assert clean_text("   ola  ") == "ola"
    assert clean_text("x" * 300, 200) == "x" * 200
    assert clean_text("\n\t ") == ""
    assert clean_text("Olá, ação ✓") == "Olá, ação ✓"  # acentos e símbolos passam
