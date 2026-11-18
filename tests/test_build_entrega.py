# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
"""Relatório em LaTeX: escape dos dados do grupo, quebra de linhas e template sem marcadores sobrando."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import build_entrega as b  # noqa: E402


def test_tex_escape_neutralizes_latex_special_characters():
    assert b.tex_escape("Luís & Caio_2 50% #1 {x} ~^\\") == (
        r"Luís \& Caio\_2 50\% \#1 \{x\} \textasciitilde{}\textasciicircum{}\textbackslash{}")


def test_wrap_lines_keeps_short_lines_and_indents_continuations():
    text = '{\n  "peers": [' + ", ".join(['{"ip": "127.0.0.1"}'] * 10) + "]\n}"
    out = b.wrap_lines(text, 60).splitlines()
    assert out[0] == "{" and out[-1] == "}"
    assert all(len(line) <= 60 for line in out)
    assert out[2].startswith("      ")  # recuo original (2) + 4


def test_template_fills_every_marker_and_every_example_exists():
    values = {"GRUPO": "2", "NOME_A": "A", "MAT_A": "1", "NOME_B": "B", "MAT_B": "2"}
    tex = b.build_tex(values, {"testes": 1, "cenarios": 1})
    assert not re.findall(r"\{\{[A-Za-z_:]+\}\}", tex)
    assert tex.count(r"\begin{codigo}") == tex.count(r"\end{codigo}")
