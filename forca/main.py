"""Ponto de entrada: argumentos, config.json, logging, inicialização.

Dono: Pessoa C. Issue 03.1.   Uso: python -m forca.main --name alice --port 8081
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Callable

from .cli import CLI
from .config import Config, load_config
from .p2p_client import P2PClient
from .rendezvous_connection import RendezvousError

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
SCREEN_ALWAYS = frozenset({"CLI", "Game"})  # mensagens ao usuário: aparecem em qualquer nível
LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

log = logging.getLogger("CLI")


def parse_level(name: str) -> int:
    """'debug' -> logging.DEBUG. ValueError se não for um dos quatro níveis."""
    if name.upper() not in LEVELS:
        raise ValueError(f"nível inválido {name!r}; use {', '.join(LEVELS)}")
    return getattr(logging, name.upper())


def _level_arg(name: str) -> str:
    try:
        parse_level(name)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    return name.upper()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="forca", description="PyP2P-Forca")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--name")
    ap.add_argument("--namespace")
    ap.add_argument("--port", type=int, dest="listen_port")
    ap.add_argument("--rdv-host", dest="rdv_host")
    ap.add_argument("--rdv-port", type=int, dest="rdv_port")
    ap.add_argument("--log-file", dest="log_file")
    ap.add_argument("--host-migration", action="store_true", default=None, dest="host_migration",
                    help="bônus: se o host cair, o menor peer_id assume a partida")
    ap.add_argument("--log-level", default="INFO", type=_level_arg, help="nível mostrado na tela")
    return ap.parse_args(argv)


# --- configuração ---


def build_config(args: argparse.Namespace) -> Config:
    """Linha de comando > config.json > padrão. ValueError se algo for inválido."""
    if not Path(args.config).exists():  # um erro de digitação no caminho não pode passar em silêncio
        log.warning("arquivo de configuração %s não encontrado; usando os padrões", args.config)
    cfg = load_config(
        args.config,
        {k: getattr(args, k) for k in
         ("name", "namespace", "listen_port", "rdv_host", "rdv_port", "log_file", "host_migration")},
    )
    for field in ("listen_port", "rdv_port"):
        port = getattr(cfg, field)
        if not (isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535):
            raise ValueError(f"{field} deve estar entre 1 e 65535, recebi {port!r}")
    return cfg


# --- logging ---


class ScreenFilter(logging.Filter):
    """Tela: o nível escolhido ou acima, mais tudo de [CLI] e [Game] (contrato, seção 7)."""

    def __init__(self, level: int = logging.INFO) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.level or record.name in SCREEN_ALWAYS

    def set_level(self, name: str) -> None:
        """Troca o nível da tela em tempo de execução (o `/log` da CLI chama isto)."""
        self.level = parse_level(name)


def setup_logging(screen_level: str = "INFO") -> ScreenFilter:
    """Raiz em DEBUG; a tela filtra. O arquivo (`add_log_file`) recebe tudo."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    screen = ScreenFilter(parse_level(screen_level))
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(screen)
    root.addHandler(handler)
    return screen


def add_log_file(path: str) -> logging.Handler:
    """Arquivo com TUDO: DEBUG e o logger Wire com o JSON bruto. OSError se não abrir."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logging.getLogger().addHandler(handler)
    return handler


# --- execução ---


def _force_exit() -> None:
    """Segundo Ctrl+C durante o encerramento: sai agora, sem esperar o BYE de cada vizinho."""
    logging.shutdown()  # descarrega os handlers antes de matar o processo
    os._exit(130)


async def run(cfg: Config, screen: ScreenFilter, force_exit: Callable[[], None] = _force_exit) -> None:
    """Sobe o cliente e a CLI. Ctrl+C e SIGTERM seguem o mesmo caminho do /quit, inclusive
    durante o `client.start()` (Rendezvous fora do ar); o segundo sinal força a saída."""
    client = P2PClient(cfg)
    cli = CLI(client, screen.set_level)
    loop = asyncio.get_running_loop()
    starting = asyncio.ensure_future(client.start())
    signals = 0

    def on_signal() -> None:
        nonlocal signals
        signals += 1
        if signals >= 2:  # o usuário já pediu para sair e continua esperando
            log.warning("saída forçada")
            force_exit()
            return
        cli.request_quit()
        if not starting.done():
            starting.cancel()  # o start() pendurado não deixa a CLI nem começar

    registered = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, on_signal)
            registered.append(sig)
        except NotImplementedError:  # Windows
            pass
    try:
        try:
            await starting
        except asyncio.CancelledError:
            if not signals:  # cancelamento de fora, não do Ctrl+C
                raise
            log.info("Início interrompido.")
        else:
            await cli.run()
    finally:
        try:
            await client.stop()  # sempre: o start() pode ter falhado ou sido cancelado no meio
        except Exception:
            log.exception("erro ao encerrar")
        for sig in registered:
            loop.remove_signal_handler(sig)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    screen = setup_logging(args.log_level)
    try:
        cfg = build_config(args)
        if cfg.log_file:
            add_log_file(cfg.log_file)
    except (ValueError, OSError) as exc:  # JSONDecodeError é ValueError
        log.error("configuração inválida: %s", exc)
        raise SystemExit(2) from None
    try:
        asyncio.run(run(cfg, screen))
    except (OSError, RendezvousError) as exc:  # ex.: porta em uso, nome já registrado
        log.error("não foi possível iniciar: %s", exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
