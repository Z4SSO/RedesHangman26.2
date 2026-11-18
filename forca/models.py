# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
"""Tipos compartilhados entre os módulos (parte do CONTRATO.md, seção 3).

Qualquer mudança aqui afeta as três pessoas: combine antes no grupo.
"""

from __future__ import annotations

from enum import Enum
from typing import Awaitable, Callable


class PeerState(str, Enum):
    """Estados de um peer na PeerTable."""

    DISCOVERED = "DISCOVERED"  # visto no Rendezvous, sem conexão
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"  # após HELLO_OK
    STALE = "STALE"  # conexão perdida
    GONE = "GONE"  # sumiu do Rendezvous ou estourou tentativas


class GameStatus(str, Enum):
    """Estado da partida hospedada localmente (GameHost)."""

    IDLE = "IDLE"
    OPEN = "OPEN"
    RUNNING = "RUNNING"
    FINISHED = "FINISHED"


class PlayerState(str, Enum):
    """Estado do jogador local (GamePlayer)."""

    IDLE = "IDLE"
    JOINED = "JOINED"
    PLAYING = "PLAYING"


# Função injetada nos módulos de jogo para enviar uma mensagem a um peer pelo
# peer_id. Retorna True se a mensagem foi escrita no socket, False se o peer
# não está conectado. Nunca levanta exceção por peer ausente.
Sender = Callable[[str, dict], Awaitable[bool]]
