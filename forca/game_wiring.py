"""Liga o jogo (parte B) à rede: roteador, eventos da PeerTable e a exclusão mútua.

Dono: Pessoa C. Issue 01.7 (parte de ligação). Quem chama é o P2PClient (parte A),
depois de criar a PeerTable e o MessageRouter.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .config import Config
from .game_host import GameHost
from .game_player import GamePlayer
from .hangman import choose_word
from .models import PeerState
from .peer_table import EVENT_CONNECTED, EVENT_GONE, EVENT_STALE

# Contrato, seção 5.4: quem trata cada tipo.
HOST_HANDLERS = {
    "GAME_LIST": "on_game_list",
    "JOIN": "on_join",
    "LEAVE": "on_leave",
    "GUESS": "on_guess",
}
PLAYER_HANDLERS = {
    "JOIN_OK": "on_join_ok",
    "JOIN_ERR": "on_join_err",
    "LEAVE_OK": "on_leave_ok",
    "GAME_START": "on_game_start",
    "STATE": "on_state",
    "GUESS_RESULT": "on_guess_result",
    "GAME_OVER": "on_game_over",
}


def wire_game(cfg: Config, table, router) -> tuple[GameHost, GamePlayer]:
    """Cria o GameHost e o GamePlayer e os liga ao roteador e à tabela de peers.

    - envio: `table.send_to` (é o `Sender`);
    - exclusão mútua (contrato 5.8): cada um recebe `busy` apontando para o outro;
    - `peer_stale` e `peer_gone` valem como queda (host remove o jogador; jogador
      aborta se era o host); `peer_connected` dispara o rejoin do jogador.
    """
    host: GameHost
    player: GamePlayer
    host = GameHost(cfg, table.send_to, busy=lambda: player.active)
    player = GamePlayer(cfg, table.send_to, busy=lambda: host.active,
                        host_alive=lambda pid: table.state_of(pid) == PeerState.CONNECTED)

    async def on_chat(conn, msg):  # bônus 05.2: um só tipo para os dois papéis (exclusão mútua)
        await (host.on_chat if host.active else player.on_chat)(conn, msg)

    router.register("CHAT", on_chat)

    async def take_over(game_id: str, players: list[str], lives: int) -> None:
        """Bônus 05.1: palavra nova sorteada de words.txt (o novo host não conhece a antiga)."""
        path = Path(cfg.words_file)
        word = await asyncio.to_thread(lambda: choose_word(path.read_text(encoding="utf-8").splitlines()))
        await host.adopt(game_id, players, word, lives)

    player.on_migrate = take_over
    for type_, name in HOST_HANDLERS.items():
        router.register(type_, getattr(host, name))
    for type_, name in PLAYER_HANDLERS.items():
        router.register(type_, getattr(player, name))

    for event in (EVENT_STALE, EVENT_GONE):
        table.subscribe(event, host.on_peer_stale)
        table.subscribe(event, player.on_peer_stale)
    table.subscribe(EVENT_CONNECTED, player.on_peer_connected)
    return host, player
