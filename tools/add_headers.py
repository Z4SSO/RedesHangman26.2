#!/usr/bin/env python3
# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
"""Coloca (ou confere) o cabeçalho de identificação do grupo em todos os arquivos .py.

    python tools/add_headers.py            # insere onde falta e atualiza onde mudou (idempotente)
    python tools/add_headers.py --check    # só confere; código de saída 1 se faltar em algum

O enunciado da entrega pede que cada arquivo de código tenha "um cabeçalho com a identificação
completa dos membros da equipe". Os dados vêm de docs/entrega.json. O cabeçalho é um bloco de
comentários `#` colocado ANTES da docstring do módulo (e depois de um eventual `#!`), então a
docstring continua sendo a primeira instrução e `ast.get_docstring` segue funcionando.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FOLDERS = ("forca", "tools", "tests")
MARK = "# Trabalho de Programação — PyP2P-Forca"


def header_lines() -> list[str]:
    data = json.loads((ROOT / "docs" / "entrega.json").read_text(encoding="utf-8"))
    names = [f"{m['nome']} ({m['matricula']})" for m in data["integrantes"]]
    people = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1]
    return [f"{MARK} (CIC0124 Redes de Computadores, 2026/2)",
            f"# Grupo {data['grupo']}: {people}"]


def python_files() -> list[Path]:
    files = []
    for folder in FOLDERS:
        files += sorted(p for p in (ROOT / folder).rglob("*.py") if "__pycache__" not in p.parts)
    return files


def with_header(text: str, header: list[str]) -> str:
    """Devolve o texto com o cabeçalho certo (insere ou substitui o que já existia)."""
    lines = text.splitlines(keepends=True)
    shebang = [lines.pop(0)] if lines and lines[0].startswith("#!") else []
    if lines and lines[0].startswith(MARK):  # já tinha: remove o bloco antigo (2 linhas) e recoloca
        lines = lines[2:] if len(lines) > 1 and lines[1].startswith("# Grupo") else lines[1:]
    block = [h + "\n" for h in header]
    return "".join(shebang + block + lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Cabeçalho de identificação do grupo nos .py")
    ap.add_argument("--check", action="store_true", help="só confere, não escreve")
    args = ap.parse_args()
    header = header_lines()
    wrong = []
    for path in python_files():
        text = path.read_text(encoding="utf-8")
        new = with_header(text, header)
        if new == text:
            continue
        wrong.append(path)
        if not args.check:
            # a docstring (se houver) tem de continuar a mesma depois da mudança
            before, after = ast.get_docstring(ast.parse(text)), ast.get_docstring(ast.parse(new))
            if before != after:
                raise SystemExit(f"a docstring de {path} mudou: abortando")
            path.write_text(new, encoding="utf-8")
    rel = [str(p.relative_to(ROOT)) for p in wrong]
    if args.check:
        print("sem cabeçalho correto:", ", ".join(rel) if rel else "nenhum")
        return 1 if rel else 0
    print(f"{len(rel)} arquivo(s) atualizado(s); {len(python_files()) - len(rel)} já estavam certos")
    return 0


if __name__ == "__main__":
    sys.exit(main())
