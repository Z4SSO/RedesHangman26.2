"""Comandos de jogo da CLI com roteador, GameHost e GamePlayer reais (rede em memória)."""

import logging
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from forca.cli import CLI
from forca.models import GameStatus, PlayerState
from test_game_wiring import FakeConn, Net, Node


def make_world(net, names, *, silent=(), no_hangman=()):
    """Um CLI por nó; cada nó vê os outros como vizinhos conectados."""
    world = {}
    for name in names:
        node = Node(net, name, features=() if name in no_hangman else ("hangman",))
        if name in silent:
            node.router._handlers.pop("GAME_LIST")  # recebe e não responde
        world[name] = node

    for name, node in world.items():
        def connected(me=node):
            return [FakeConn(pid, net[pid].features_of_sender) for pid in net if pid != me.id and pid not in net.down]

        client = SimpleNamespace(cfg=node.cfg, router=node.router, host=node.host,
                                 player=node.player, table=SimpleNamespace(connected=connected))
        node.cli = CLI(client, None, stdin=None)
        node.cli.games_timeout = 0.2
    return world


@pytest.fixture
def net():
    n = Net()
    n.down = set()
    return n


@pytest.fixture
async def w(net):
    world = make_world(net, ["alice", "bob", "carol"])
    yield SimpleNamespace(**world)
    for node in world.values():
        await node.host.shutdown()


@pytest.fixture(autouse=True)
def logs(caplog):
    caplog.set_level(logging.DEBUG)


def out(caplog, logger="CLI"):
    return [r.getMessage() for r in caplog.records if r.name == logger]


async def run(node, *commands):
    for c in commands:
        await node.cli.execute(c)


# --- /games ---


async def test_games_lists_only_the_open_game_and_a_silent_neighbor_does_not_block(net, caplog):
    world = make_world(net, ["alice", "bob", "carol", "dave"], silent=["dave"])
    await world["alice"].host.create("casa")
    started = time.monotonic()
    await run(world["bob"], "/games")
    assert time.monotonic() - started < 1.5  # dave estourou o timeout de 0,2 s, nada travou
    shown = [m for m in out(caplog) if m.startswith("  ")]
    assert len(shown) == 1
    assert world["alice"].host.game_id in shown[0] and "host=alice@CIC" in shown[0]
    assert "0/4 jogadores" in shown[0] and "4 letras" in shown[0] and "6 vidas" in shown[0]
    await world["alice"].host.shutdown()


async def test_games_without_games_or_without_hangman_neighbors(net, caplog):
    world = make_world(net, ["alice", "bob", "carol"], no_hangman=["alice", "carol"])
    await run(world["bob"], "/games")
    assert any("Nenhum vizinho conectado" in m for m in out(caplog))
    caplog.clear()
    world = make_world(Net(), ["alice", "bob"])
    world["bob"].cli.client.table = SimpleNamespace(connected=lambda: [FakeConn("alice@CIC")])
    await run(world["bob"], "/games")
    assert any("Nenhuma partida aberta" in m for m in out(caplog))


# --- /create ---


async def test_create_with_and_without_max_players(w, caplog):
    await run(w.alice, "/create casa 2")
    assert w.alice.host.status == GameStatus.OPEN and w.alice.host.describe()["max_players"] == 2
    assert any("Partida criada" in m for m in out(caplog))


async def test_create_validation_messages(w, caplog):
    await run(w.alice, "/create", "/create casa x", "/create casa 2 3", "/create co-op", "/create ab")
    assert w.alice.host.status == GameStatus.IDLE
    msgs = out(caplog)
    assert sum("uso: /create" in m for m in msgs) == 3
    assert sum("não foi possível criar" in m for m in msgs) == 2


async def test_create_random_draws_a_valid_word_from_the_words_file(w, tmp_path, caplog):
    words = tmp_path / "words.txt"
    words.write_text("banana\nxx\nco-op\n\nÇaça\n", encoding="utf-8")
    w.alice.cli.client.cfg = replace(w.alice.cfg, words_file=str(words))
    await run(w.alice, "/create --random 3")
    assert w.alice.host._game.word in {"banana", "caca"}  # "Çaça" vira "caca"; "xx" e "co-op" são ignoradas
    assert w.alice.host.describe()["max_players"] == 3


async def test_create_random_with_a_missing_or_useless_file(w, tmp_path, caplog):
    w.alice.cli.client.cfg = replace(w.alice.cfg, words_file=str(tmp_path / "nope.txt"))
    await run(w.alice, "/create --random")
    (tmp_path / "bad.txt").write_text("ab\nco-op\n")
    w.alice.cli.client.cfg = replace(w.alice.cfg, words_file=str(tmp_path / "bad.txt"))
    await run(w.alice, "/create --random")
    assert w.alice.host.status == GameStatus.IDLE
    assert any("não consegui ler" in m for m in out(caplog)) and any("não tem palavras válidas" in m for m in out(caplog))


# --- exclusão mútua ---


async def test_one_game_at_a_time(w, caplog):
    await run(w.alice, "/create casa")
    await run(w.alice, "/create gato")  # já hospeda
    await run(w.alice, "/join bob")  # host ativo não entra como jogador
    await run(w.bob, "/join alice")
    await run(w.bob, "/create gato")  # jogador ativo não cria
    await run(w.bob, "/join alice")  # nem entra de novo
    assert sum("já está em uma partida" in m for m in out(caplog)) == 4
    assert w.alice.host._players == [w.bob.id] and w.bob.host.status == GameStatus.IDLE


# --- /start, /join ---


async def test_start_without_players_is_a_local_error_and_with_a_player_starts(w, caplog):
    await run(w.alice, "/start")  # sem partida
    await run(w.alice, "/create casa", "/start")  # sem jogadores
    assert w.alice.host.status == GameStatus.OPEN
    assert any("Você não tem uma partida aberta" in m for m in out(caplog))
    assert any("pelo menos 1 jogador" in m for m in out(caplog))
    await run(w.bob, "/join alice@CIC")
    await run(w.alice, "/start")
    assert w.alice.host.status == GameStatus.RUNNING and w.bob.player.state == PlayerState.PLAYING


async def test_join_finds_the_game_id_and_accepts_a_bare_name(w):
    await run(w.alice, "/create casa")
    await run(w.bob, "/join alice")  # sem @namespace: usa o local
    assert w.bob.player.state == PlayerState.JOINED and w.bob.player.game_id == w.alice.host.game_id
    assert w.alice.host._players == [w.bob.id]


async def test_join_error_messages(net, caplog):
    world = make_world(net, ["alice", "bob", "carol"], silent=["carol"])
    bob = world["bob"]
    await run(bob, "/join", "/join zed", "/join alice")  # sem args; desconhecido; sem partida
    await run(bob, "/join carol")  # não responde ao GAME_LIST
    msgs = out(caplog)
    assert any("uso: /join" in m for m in msgs) and any("zed@CIC não está conectado" in m for m in msgs)
    assert any("alice@CIC não tem partida aberta" in m for m in msgs) and any("não respondeu" in m for m in msgs)
    assert not bob.player.active


async def test_join_error_from_the_host_reaches_the_player(w, caplog):
    await run(w.alice, "/create casa 1")
    await run(w.bob, "/join alice")
    await run(w.carol, "/join alice")  # game_full: o JOIN_ERR chega ao GamePlayer e libera o peer
    assert "game_full" in caplog.text and not w.carol.player.active


# --- jogar ---


async def test_play_a_whole_game_through_the_cli(w, caplog):
    await run(w.alice, "/create casa")
    await run(w.bob, "/join alice")
    await run(w.carol, "/join alice")
    await run(w.alice, "/start")
    await run(w.bob, "/guess c")
    await run(w.carol, "/guess Á")  # acento é tirado
    await run(w.bob, "/guess s")
    assert not w.bob.player.active and not w.carol.player.active
    assert w.alice.host.status == GameStatus.FINISHED
    assert "winner=bob@CIC" in caplog.text


async def test_guess_and_word_validate_before_sending(w, caplog):
    await run(w.bob, "/guess a", "/word casa")  # fora de partida
    assert sum("não está em uma partida em andamento" in m for m in out(caplog)) == 2
    await run(w.alice, "/create casa")
    await run(w.bob, "/join alice")
    await run(w.alice, "/start")
    sent_before = w.alice.host._seq
    await run(w.bob, "/guess", "/guess ab", "/guess 1", "/guess -", "/word co-op", "/word ab", "/word a b")
    assert w.alice.host._seq == sent_before and w.alice.host._game.lives == 6  # nada chegou ao host
    msgs = out(caplog)
    assert sum("Letra inválida" in m for m in msgs) == 3 and sum("Palavra inválida" in m for m in msgs) == 2
    assert sum("uso: /guess" in m or "uso: /word" in m for m in msgs) == 2
    await run(w.bob, "/word CASA")  # normaliza e vence
    assert w.alice.host.status == GameStatus.FINISHED


# --- /status, /cancel, /leave ---


async def test_status_shows_the_host_or_the_player_view(w, caplog):
    await run(w.alice, "/status")  # sem partida em lugar nenhum
    assert any("não está em uma partida" in m for m in out(caplog, "Game"))
    await run(w.alice, "/create banana")
    await run(w.bob, "/join alice")
    await run(w.alice, "/start")
    await run(w.bob, "/guess a")
    caplog.clear()
    await run(w.alice, "/status")
    host_view = "\n".join(out(caplog, "Game"))
    assert "status: RUNNING" in host_view and "banana" in host_view and "Vidas: 6 / 6" in host_view
    assert "[Game]" not in host_view  # o prefixo vem do logger, sem duplicar
    caplog.clear()
    await run(w.bob, "/status")
    player_view = "\n".join(out(caplog, "Game"))
    for piece in ("host: alice@CIC", "_ a _ a _ a", "Vidas: 6 / 6", "Erradas: -", "Jogadores: bob@CIC", "Vez de: bob@CIC"):
        assert piece in player_view, piece


async def test_cancel_and_leave(w, caplog):
    await run(w.alice, "/cancel")
    await run(w.bob, "/leave")
    assert any("não está hospedando" in m for m in out(caplog)) and any("não está em uma partida como jogador" in m for m in out(caplog))
    await run(w.alice, "/create casa")
    await run(w.bob, "/join alice")
    await run(w.carol, "/join alice")
    await run(w.carol, "/leave")
    assert w.alice.host._players == [w.bob.id] and not w.carol.player.active
    await run(w.alice, "/cancel")
    assert not w.alice.host.active and not w.bob.player.active
    assert any("Partida cancelada" in m for m in out(caplog)) and any("Você saiu" in m for m in out(caplog))
