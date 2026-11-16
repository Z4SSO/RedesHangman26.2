"""Ponto de entrada: argumentos, config.json, logging, inicialização.

Dono: Pessoa C. Issue 03.1.   Uso: python -m forca.main --name alice --port 8081
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from .config import load_config

LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="forca", description="PyP2P-Forca")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--name")
    ap.add_argument("--namespace")
    ap.add_argument("--port", type=int, dest="listen_port")
    ap.add_argument("--rdv-host", dest="rdv_host")
    ap.add_argument("--rdv-port", type=int, dest="rdv_port")
    ap.add_argument("--log-file", dest="log_file")
    ap.add_argument("--log-level", default="INFO")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    cfg = load_config(
        args.config,
        {k: getattr(args, k) for k in
         ("name", "namespace", "listen_port", "rdv_host", "rdv_port", "log_file")},
    )
    # TODO(issue 03.1): configurar logging (tela: INFO, [CLI] e [Game];
    # arquivo: tudo, incluindo DEBUG), criar P2PClient + CLI e rodar o loop.
    logging.basicConfig(level=args.log_level, format=LOG_FORMAT)
    raise NotImplementedError(f"issue 03.1 (peer {cfg.peer_id})")


if __name__ == "__main__":
    main()
