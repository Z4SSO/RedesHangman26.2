"""Integração em memória: roteador real + GameHost/GamePlayer reais + tabela falsa."""

import pytest

from forca import protocol as p
from forca.config import Config
from forca.game_wiring import HOST_HANDLERS, PLAYER_HANDLERS, wire_game
from forca.message_router import MessageRouter
from forca.models import GameStatus, PlayerState
from forca.peer_table import EVENT_CONNECTED, EVENT_GONE, EVENT_STALE


class FakeConn:
    def __init__(self, peer_id, features=("hangman",)):
        self.peer_id, self.features = peer_id, list(features)

    async def send(self, msg):
        return True


class FakeTable:
    """Só o que o wire_game usa: subscribe e send_to (que entrega ao outro nó)."""

    def __init__(self, net, peer_id):
        self.net, self.peer_id, self.subs = net, peer_id, {}
        self.states: dict = {}

    def state_of(self, peer_id):
        return self.states.get(peer_id)

    def subscribe(self, event, callback):
        self.subs.setdefault(event, []).append(callback)

    async def fire(self, event, peer_id):
        for cb in self.subs.get(event, []):
            await cb(peer_id)

    async def send_to(self, peer_id, msg):
        node = self.net.get(peer_id)
        if node is None or peer_id in self.net.down:
            return False
        p.validate_envelope(msg, peer_id)  # rígido ao enviar
        await node.router.on_message(FakeConn(self.peer_id, node.features_of_sender), msg)
        return True


class Node:
    def __init__(self, net, name, features=("hangman",), **cfg):
        self.cfg = Config(name=name, namespace="CIC", **cfg)
        self.id = self.cfg.peer_id
        self.features_of_sender = features  # o que os OUTROS veem deste nó no HELLO
        self.table = FakeTable(net, self.id)
        self.router = MessageRouter(self.id, self.table.send_to)
        self.host, self.player = wire_game(self.cfg, self.table, self.router)
        net[self.id] = self


class Net(dict):
    down: set = set()


@pytest.fixture
def net():
    n = Net()
    n.down = set()
    return n


@pytest.fixture
async def trio(net):
    alice, bob, carol = Node(net, "alice"), Node(net, "bob"), Node(net, "carol")
    yield alice, bob, carol
    for n in (alice, bob, carol):
        await n.host.shutdown()


def test_every_game_type_of_the_contract_is_registered(net):
    node = Node(net, "alice")
    assert set(node.router._handlers) == set(HOST_HANDLERS) | set(PLAYER_HANDLERS) | {"CHAT"}  # CHAT: bônus 05.2
    assert set(node.table.subs) == {EVENT_STALE, EVENT_GONE, EVENT_CONNECTED}


async def test_games_request_goes_through_the_router(trio):
    alice, bob, _ = trio
    await alice.host.create("casa", 2)
    req = p.new_message("GAME_LIST", src=bob.id, dst=alice.id)
    reply = await bob.router.request(alice.id, req)
    assert reply["type"] == "GAME_LIST_OK" and reply["games"][0]["game_id"] == alice.host.game_id


async def test_full_game_through_routers(trio):
    alice, bob, carol = trio
    gid = await alice.host.create("casa")
    await bob.player.join(alice.id, gid)
    await carol.player.join(alice.id, gid)
    await alice.host.start()
    assert bob.player.state == PlayerState.PLAYING and carol.player.seq == 1
    await bob.player.guess_letter("c")
    await carol.player.guess_letter("a")
    await bob.player.guess_letter("s")
    assert not bob.player.active and not carol.player.active
    assert alice.host.status == GameStatus.FINISHED


async def test_stale_and_gone_remove_the_player_and_abort_the_host_side(trio):
    alice, bob, carol = trio
    gid = await alice.host.create("banana")
    await bob.player.join(alice.id, gid)
    await carol.player.join(alice.id, gid)
    await alice.host.start()
    await alice.table.fire(EVENT_STALE, carol.id)  # queda de jogador
    assert alice.host._players == [bob.id]
    await bob.table.fire(EVENT_GONE, alice.id)  # peer_gone também vale como queda do host
    assert not bob.player.active


async def test_peer_connected_triggers_the_rejoin(trio):
    alice, bob, carol = trio
    gid = await alice.host.create("banana")
    await bob.player.join(alice.id, gid)
    await carol.player.join(alice.id, gid)
    await alice.host.start()
    await carol.table.fire(EVENT_STALE, alice.id)  # carol perde o host
    await alice.table.fire(EVENT_STALE, carol.id)  # e o host perde a carol
    assert not carol.player.active and alice.host._players == [bob.id]
    await carol.table.fire(EVENT_CONNECTED, alice.id)  # reconectaram
    assert carol.player.state == PlayerState.PLAYING
    assert alice.host._players == [bob.id, carol.id]


async def test_mutual_exclusion_is_wired_in_both_directions(trio):
    alice, bob, _ = trio
    await alice.host.create("casa")
    with pytest.raises(RuntimeError):  # host ativo: não entra como jogador
        await alice.player.join(bob.id, "bob@CIC/00000000")
    gid = alice.host.game_id
    await bob.player.join(alice.id, gid)
    with pytest.raises(RuntimeError):  # jogador ativo: não cria partida
        await bob.host.create("gato")


async def test_game_messages_from_a_peer_without_hangman_are_ignored(net, trio):
    alice, bob, _ = trio
    await alice.host.create("casa")
    stranger = FakeConn("dave@CIC", features=())
    join = p.new_message("JOIN", src="dave@CIC", dst=alice.id, game_id=alice.host.game_id)
    await alice.router.on_message(stranger, join)
    assert alice.host.describe()["players"] == []


# --- bônus 05.2: chat ---


def record_sent(*nodes):
    """Guarda (de, para, msg) de tudo que os nós enviam, sem alterar a entrega."""
    sent = []
    for n in nodes:
        orig = n.table.send_to

        async def spy(peer_id, msg, orig=orig, me=n.id):
            sent.append((me, peer_id, msg))
            return await orig(peer_id, msg)

        n.table.send_to = spy
        n.host.send = spy
        n.player.send = spy
    return sent


async def lobby3(trio):
    alice, bob, carol = trio
    gid = await alice.host.create("casa")
    await bob.player.join(alice.id, gid)
    await carol.player.join(alice.id, gid)
    await alice.host.start()
    return alice, bob, carol, gid


async def test_chat_from_a_player_reaches_everyone_but_the_author(trio, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="Game")
    alice, bob, carol, gid = await lobby3(trio)
    sent = record_sent(alice, bob, carol)
    await bob.player.chat("oi pessoal")
    chats = [(a, b, m) for a, b, m in sent if m["type"] == "CHAT"]
    assert [(a, b) for a, b, _ in chats] == [(bob.id, alice.id), (alice.id, carol.id)]  # nada volta a bob
    relayed = chats[1][2]
    assert relayed["from"] == bob.id and relayed["src"] == alice.id and relayed["text"] == "oi pessoal"
    shown = [r.getMessage() for r in caplog.records if r.name == "Game" and "oi pessoal" in r.getMessage()]
    assert sorted(shown) == sorted(["você: oi pessoal", f"{bob.id}: oi pessoal", f"{bob.id}: oi pessoal"])


async def test_chat_from_the_host_reaches_all_players(trio):
    alice, bob, carol, gid = await lobby3(trio)
    sent = record_sent(alice, bob, carol)
    await alice.host.chat("boa sorte")
    chats = [(b, m["from"], m["text"]) for a, b, m in sent if m["type"] == "CHAT"]
    assert sorted(chats) == [(bob.id, alice.id, "boa sorte"), (carol.id, alice.id, "boa sorte")]


async def test_chat_text_from_the_wire_is_sanitized_and_truncated(trio, caplog):
    alice, bob, carol, gid = await lobby3(trio)
    sent = record_sent(alice, bob, carol)
    forged = p.new_message("CHAT", src=bob.id, dst=alice.id, game_id=gid, text="a\n[Host] falso" + "z" * 400)
    await alice.router.on_message(FakeConn(bob.id), forged)
    (_, _, relayed), = [x for x in sent if x[2]["type"] == "CHAT"]
    assert "\n" not in relayed["text"] and len(relayed["text"]) == p.CHAT_MAX_LEN


async def test_chat_from_a_non_player_or_other_game_is_invalid_state(trio):
    alice, bob, carol = trio
    gid = await alice.host.create("casa")
    await bob.player.join(alice.id, gid)  # carol NÃO entrou
    await alice.host.start()
    sent = record_sent(alice)
    for src, game in ((carol.id, gid), (bob.id, "alice@CIC/outra")):
        await alice.router.on_message(
            FakeConn(src), p.new_message("CHAT", src=src, dst=alice.id, game_id=game, text="oi"))
    errors = [m for _, _, m in sent if m["type"] == "ERROR"]
    assert [m["code"] for m in errors] == ["invalid_state", "invalid_state"]
    assert not [m for _, _, m in sent if m["type"] == "CHAT"]  # nada foi repassado


async def test_player_ignores_chat_that_does_not_come_from_its_host(trio, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="Game")
    alice, bob, carol, gid = await lobby3(trio)
    caplog.clear()
    await bob.router.on_message(
        FakeConn(carol.id), p.new_message("CHAT", src=carol.id, dst=bob.id, game_id=gid, text="intruso"))
    assert "intruso" not in caplog.text


async def test_chat_outside_a_game_is_ignored_without_crashing(trio):
    alice, bob, _ = trio
    await bob.router.on_message(
        FakeConn(alice.id), p.new_message("CHAT", src=alice.id, dst=bob.id, game_id="x", text="oi"))
    await alice.router.on_message(
        FakeConn(bob.id), p.new_message("CHAT", src=bob.id, dst=alice.id, game_id="x", text="oi"))


# --- bônus 05.1: migração de host ---


@pytest.fixture
async def quartet(net, tmp_path, monkeypatch):
    (tmp_path / "words.txt").write_text("casa\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    nodes = [Node(net, n, host_migration=True) for n in ("alice", "bob", "carol", "dave")]
    yield nodes
    for n in nodes:
        await n.host.shutdown()
        await n.player.leave()


async def running_game(alice, others):
    gid = await alice.host.create("zebra")
    for n in others:
        await n.player.join(alice.id, gid)
    await alice.host.start()
    await others[0].player.guess_letter("q")  # errada: o novo host herda 5 vidas
    return gid


@pytest.mark.parametrize("order", [("bob", "carol", "dave"), ("dave", "carol", "bob")])
async def test_host_dies_and_the_smallest_peer_id_continues_the_game(net, quartet, order):
    alice, bob, carol, dave = quartet
    gid = await running_game(alice, [bob, carol, dave])
    net.down.add(alice.id)  # kill -9 no host
    by_name = {"bob": bob, "carol": carol, "dave": dave}
    for name in order:  # nas duas ordens: sucessor primeiro (corrida) e sucessor por último
        await by_name[name].table.fire(EVENT_STALE, alice.id)

    assert bob.host.status == GameStatus.RUNNING and bob.host.game_id == gid
    assert not bob.player.active
    for pl in (carol.player, dave.player):
        assert pl.state == PlayerState.PLAYING and pl.host_id == bob.id and pl.lives == 5
        assert pl.seq >= 1 and len(pl.masked) == 4  # palavra nova ("casa")
    # a partida segue e termina normalmente com o novo host
    turn = bob.host._turn
    mover = carol if turn == carol.id else dave
    for letter in "cas":
        mover = carol if bob.host._turn == carol.id else dave
        await mover.player.guess_letter(letter)
    assert bob.host.status == GameStatus.FINISHED
    assert not carol.player.active and not dave.player.active


async def test_with_migration_off_the_other_players_abort(net):
    nodes = [Node(net, n) for n in ("alice", "bob", "carol")]
    alice, bob, carol = nodes
    await running_game(alice, [bob, carol])
    net.down.add(alice.id)
    for n in (bob, carol):
        await n.table.fire(EVENT_STALE, alice.id)
    assert not bob.player.active and not carol.player.active and not bob.host.active
    for n in nodes:
        await n.host.shutdown()


async def test_wire_game_gives_the_player_a_host_alive_bound_to_the_table(net):
    from forca.models import PeerState

    node = Node(net, "bob", host_migration=True)
    assert node.player.host_alive("alice@CIC") is False  # a tabela não conhece o peer
    node.table.states["alice@CIC"] = PeerState.CONNECTED
    assert node.player.host_alive("alice@CIC") is True
    node.table.states["alice@CIC"] = PeerState.STALE
    assert node.player.host_alive("alice@CIC") is False
