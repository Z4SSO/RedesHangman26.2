#!/usr/bin/env python3
# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
"""Gera os arquivos da entrega: o relatório em PDF e o zip só com o código-fonte.

    python tools/build_entrega.py                 # rascunho: marcadores {{...}} podem sobrar
    python tools/build_entrega.py --final         # falha se faltar algum dado do grupo
    python tools/build_entrega.py --verify-zip    # extrai o zip num diretório novo e roda tudo de lá
    python tools/build_entrega.py --no-run        # reaproveita os números do último build

Dados do grupo: docs/entrega.json (veja docs/entrega.exemplo.json). O relatório vem de
docs/relatorio/relatorio.template.tex + docs/relatorio/exemplos.json (mensagens reais
capturadas dos logs). Os números de testes e de cenários são MEDIDOS a cada build, não
digitados. O PDF é compilado com pdflatex (no Ubuntu: texlive-latex-recommended,
texlive-latex-extra e texlive-lang-portuguese). Saída em dist/: o .tex preenchido, o PDF e o zip.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
TEMPLATE = ROOT / "docs" / "relatorio" / "relatorio.template.tex"
EXAMPLES = ROOT / "docs" / "relatorio" / "exemplos.json"
DATA_FILE = ROOT / "docs" / "entrega.json"
METRICS = DIST / "metricas.json"

# Só o que é código-fonte do projeto (o enunciado pede "somente os códigos-fonte").
ZIP_INCLUDE = [
    "forca", "tools", "tests", "config.json", "words.txt", "requirements-dev.txt",
    "pytest.ini", "README.md", "docs/CONTRATO.md", "docs/testes.md", "docs/entrega.json",
    "docs/relatorio",
]
ZIP_SKIP_PARTS = {"__pycache__", ".pytest_cache", ".venv", ".git", "logs", "dist"}
ZIP_SKIP_SUFFIX = {".pyc", ".log"}


# --- dados e métricas ---------------------------------------------------------


def load_group() -> dict:
    if not DATA_FILE.exists():
        return {}
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def group_values(data: dict) -> dict[str, str]:
    """Marcadores de identificação -> valores (só os que foram preenchidos)."""
    values = {}
    if data.get("grupo"):
        values["GRUPO"] = str(data["grupo"])
    for letter, member in zip("ABC", data.get("integrantes", [])):
        if member.get("nome"):
            values[f"NOME_{letter}"] = member["nome"]
        if member.get("matricula"):
            values[f"MAT_{letter}"] = str(member["matricula"])
    return values


def measure() -> dict:
    """Roda a suíte e os cenários e devolve os números (nada digitado à mão)."""
    py = sys.executable
    out = subprocess.run([py, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True).stdout
    m = re.search(r"(\d+) passed", out)
    failed = re.search(r"(\d+) failed", out)
    if not m or failed:
        raise SystemExit(f"os testes não estão todos passando:\n{out[-800:]}")
    sc = subprocess.run([py, "tools/scenarios.py"], cwd=ROOT, capture_output=True, text=True)
    s = re.search(r"(\d+)/(\d+) cenários passaram", sc.stdout)
    if sc.returncode != 0 or not s or s.group(1) != s.group(2):
        raise SystemExit(f"os cenários não estão todos passando:\n{sc.stdout[-800:]}")
    metrics = {"testes": int(m.group(1)), "cenarios": int(s.group(2))}
    DIST.mkdir(exist_ok=True)
    METRICS.write_text(json.dumps(metrics))
    return metrics


def cached_metrics() -> dict:
    return json.loads(METRICS.read_text()) if METRICS.exists() else {}


# --- relatório ------------------------------------------------------------------


def render_json(obj: dict) -> str:
    """Um campo de nível superior por linha; valores aninhados em uma linha só."""
    lines = [f'  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}' for k, v in obj.items()]
    return "{\n" + ",\n".join(lines) + "\n}"


TEX_SPECIAL = {c: "\\" + c for c in "&%$#_{}"} | {"~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
                                                  "\\": r"\textbackslash{}"}


def tex_escape(value: str) -> str:
    """Texto do usuário (nomes, matrículas) -> LaTeX seguro."""
    return "".join(TEX_SPECIAL.get(c, c) for c in value)


def wrap_lines(text: str, width: int = 100) -> str:
    """Quebra linhas longas de um bloco Verbatim (que não quebra sozinho) com recuo de continuação."""
    out = []
    for line in text.splitlines():
        if len(line) <= width:
            out.append(line)
            continue
        indent = " " * (len(line) - len(line.lstrip()) + 4)
        out.extend(textwrap.wrap(line, width, subsequent_indent=indent, break_on_hyphens=False))
    return "\n".join(out)


def build_tex(values: dict[str, str], metrics: dict) -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))

    def example(match: re.Match) -> str:
        name = match.group(1)
        if name not in examples:
            raise SystemExit(f"exemplo desconhecido no template: {name}")
        return "\\begin{codigo}\n" + wrap_lines(render_json(examples[name])) + "\n\\end{codigo}"

    text = re.sub(r"\{\{EX:(\w+)\}\}", example, text)
    values = dict(values)
    values["DATA"] = datetime.date.today().strftime("%d/%m/%Y")
    if "testes" in metrics:
        values["N_TESTES"] = str(metrics["testes"])
    if "cenarios" in metrics:
        values["N_CENARIOS"] = f"{metrics['cenarios']}/{metrics['cenarios']}"
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", tex_escape(value))
    return text


def to_pdf(tex_path: Path) -> Path:
    """.tex -> PDF com pdflatex (duas passadas, para as referências \\ref)."""
    pdflatex = shutil.which("pdflatex")
    if pdflatex is None:
        raise SystemExit("pdflatex não encontrado. No Ubuntu: sudo apt install texlive-latex-recommended "
                         "texlive-latex-extra texlive-lang-portuguese")
    pdf = tex_path.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as build:  # .aux/.log/.out ficam fora do dist/
        for _ in range(2):
            r = subprocess.run([pdflatex, "-interaction=nonstopmode", "-halt-on-error",
                                f"-output-directory={build}", str(tex_path)],
                               cwd=tex_path.parent, capture_output=True, text=True, errors="replace",
                               timeout=180)  # o log do pdflatex sai em latin-1
            if r.returncode != 0:
                raise SystemExit(f"pdflatex falhou:\n{r.stdout[-2000:]}")
        shutil.move(str(Path(build) / pdf.name), pdf)
    return pdf


# --- zip --------------------------------------------------------------------------


def iter_zip_files() -> list[Path]:
    files = []
    for entry in ZIP_INCLUDE:
        path = ROOT / entry
        if not path.exists():
            continue
        candidates = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        for f in candidates:
            parts = set(f.relative_to(ROOT).parts)
            if parts & ZIP_SKIP_PARTS or f.suffix in ZIP_SKIP_SUFFIX:
                continue
            files.append(f)
    return files


def build_zip(zip_path: Path, folder: str) -> int:
    files = iter_zip_files()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f"{folder}/{f.relative_to(ROOT).as_posix()}")
    return len(files)


def verify_zip(zip_path: Path) -> None:
    """Extrai num diretório novo, cria um venv e roda testes e cenários de lá."""
    with tempfile.TemporaryDirectory(prefix="forca-zip-") as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        (root,) = [p for p in Path(tmp).iterdir() if p.is_dir()]
        print(f"verificando {zip_path.name} em {root} ...")
        subprocess.run([sys.executable, "-m", "venv", ".venv"], cwd=root, check=True)
        py = str(root / ".venv" / "bin" / "python")
        subprocess.run([py, "-m", "pip", "install", "-q", "-r", "requirements-dev.txt"], cwd=root, check=True)
        t = subprocess.run([py, "-m", "pytest", "-q"], cwd=root, capture_output=True, text=True)
        print("  pytest:", t.stdout.strip().splitlines()[-1] if t.stdout.strip() else t.stderr[-300:])
        s = subprocess.run([py, "tools/scenarios.py"], cwd=root, capture_output=True, text=True)
        print("  cenários:", [ln for ln in s.stdout.splitlines() if "cenários passaram" in ln])
        if t.returncode != 0 or s.returncode != 0:
            raise SystemExit("o zip extraído NÃO passa nos testes/cenários")


# --- principal ---------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="Gera o PDF do relatório e o zip do código")
    ap.add_argument("--final", action="store_true", help="falha se sobrar algum marcador {{...}}")
    ap.add_argument("--no-run", action="store_true", help="não roda testes/cenários; usa dist/metricas.json")
    ap.add_argument("--verify-zip", action="store_true", help="extrai o zip e roda testes e cenários")
    args = ap.parse_args()

    if args.final:  # todo .py precisa do cabeçalho de identificação do grupo
        chk = subprocess.run([sys.executable, "tools/add_headers.py", "--check"], cwd=ROOT,
                             capture_output=True, text=True)
        if chk.returncode != 0:
            print("FALHOU:", chk.stdout.strip(), "\nrode: python tools/add_headers.py")
            return 1
    data = load_group()
    values = group_values(data)
    DIST.mkdir(exist_ok=True)
    metrics = cached_metrics() if args.no_run else measure()
    print("métricas:", metrics)

    tex_text = build_tex(values, metrics)
    leftovers = sorted(set(re.findall(r"\{\{[A-Z_]+\}\}", tex_text)))
    if leftovers:
        print("marcadores sem valor:", ", ".join(leftovers))
        if args.final:
            print("FALHOU: preencha docs/entrega.json (modelo em docs/entrega.exemplo.json)")
            return 1
    tex_path = DIST / "relatorio.tex"
    tex_path.write_text(tex_text, encoding="utf-8")
    pdf = to_pdf(tex_path)

    tag = str(data.get("grupo") or "X")
    final_pdf = DIST / f"grupo-{tag}-relatorio.pdf"
    final_zip = DIST / f"grupo-{tag}-codigo.zip"
    pdf.replace(final_pdf)
    n = build_zip(final_zip, f"grupo-{tag}-pyp2p-forca")
    print(f"PDF: {final_pdf} ({final_pdf.stat().st_size // 1024} KiB)")
    print(f"ZIP: {final_zip} ({n} arquivos, {final_zip.stat().st_size // 1024} KiB)")
    if args.verify_zip:
        verify_zip(final_zip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
