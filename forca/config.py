# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
"""Configuração do peer (config.json + sobrescrita por linha de comando)."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Config:
    rdv_host: str = "pyp2p.mfcaetano.cc"
    rdv_port: int = 8080
    namespace: str = "CIC"
    name: str = "alice"
    listen_port: int = 8081
    register_ttl: int = 7200
    discover_interval: int = 20
    ping_interval: int = 30
    ping_miss_limit: int = 3
    max_reconnect_attempts: int = 5
    base_backoff: float = 2
    max_backoff: float = 60
    lives: int = 6
    max_players: int = 4
    turn_timeout: int = 30
    words_file: str = "words.txt"
    log_file: str | None = None

    @property
    def peer_id(self) -> str:
        return f"{self.name}@{self.namespace}"


def load_config(path: str | Path | None, overrides: dict[str, Any] | None = None) -> Config:
    """Lê o JSON (se existir) e aplica `overrides` (valores None são ignorados).

    Chaves desconhecidas no arquivo geram ValueError, para pegar erro de digitação.
    """
    cfg = Config()
    known = {f.name for f in fields(Config)}

    if path is not None and Path(path).exists():
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        cfg = replace(cfg, **data)

    if overrides:
        cfg = replace(cfg, **{k: v for k, v in overrides.items() if v is not None and k in known})

    # O host manda turn_timeout no GAME_START, onde o protocolo exige inteiro; e 0 faria o
    # timer de turno estourar sem parar.
    t = cfg.turn_timeout
    if not isinstance(t, int) or isinstance(t, bool) or t < 1:
        raise ValueError(f"turn_timeout must be an integer >= 1, got {t!r}")

    # Estes dois alimentam laços que falam com o Rendezvous, que bloqueia o IP por 1 min
    # acima de 50 req/min: intervalo zero/negativo ou TTL minúsculo viram um laço sem pausa.
    d = cfg.discover_interval
    if isinstance(d, bool) or not isinstance(d, (int, float)) or d < 1:
        raise ValueError(f"discover_interval must be a number >= 1 (seconds), got {d!r}")
    ttl = cfg.register_ttl
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl < 2:
        raise ValueError(f"register_ttl must be a number >= 2 (seconds), got {ttl!r}")

    return cfg
