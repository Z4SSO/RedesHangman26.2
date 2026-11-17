import logging
from types import SimpleNamespace

import pytest

from forca import protocol as p
from forca.config import Config
from forca.game_host import GameHost
from forca.game_player import GamePlayer
from forca.hangman import word_hash
from forca.models import PlayerState

from helpers import FakeSender, incoming

HOST, ME, GID = "alice@CIC", "bob@CIC", "alice@CIC/3f9a2c1b"


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def player(sender):
    return GamePlayer(Config(name="bob", namespace="CIC"), sender)


def from_host(type_, **fields):
    return incoming(type_, HOST, ME, game_id=GID, **fields)


def state(seq, masked="______", turn=ME, lives=6, wrong=(), last=None):
    return from_host(
        "STATE", seq=seq, masked=masked, wrong_letters=list(wrong), lives=lives,
        turn=turn, players=[ME, "carol@CIC"], last_guess=last,
    )


async def playing(player, word="banana"):
    await player.join(HOST, GID)
    await player.on_join_ok(None, from_host("JOIN_OK", players=[ME], rejoin=False))
    await player.on_game_start(None, from_host(
        "GAME_START", players=[ME, "carol@CIC"], lives=6, word_length=len(word),
        word_hash=word_hash(word), turn_timeout=30,
    ))
    await player.on_state(None, state(1))


async def test_join_sends_join_and_ok_keeps_joined(player, sender):
    await player.join(HOST, GID)
    sent = sender.last()
    assert (sent["type"], sent["dst"], sent["game_id"]) == ("JOIN", HOST, GID)
    await player.on_join_ok(None, from_host("JOIN_OK", players=[ME], rejoin=False))
    assert player.state == PlayerState.JOINED and player.players == [ME]


async def test_join_err_goes_back_to_idle(player):
    await player.join(HOST, GID)
    await player.on_join_err(None, from_host("JOIN_ERR", reason="game_full"))
    assert not player.active and player.host_id is None


async def test_join_twice_and_unreachable_host(player):
    await player.join(HOST, GID)
    with pytest.raises(RuntimeError):
        await player.join(HOST, GID)

    async def offline(peer, msg):
        return False

    other = GamePlayer(Config(name="bob", namespace="CIC"), offline)
    await other.join(HOST, GID)
    assert not other.active


async def test_game_start_and_state_make_playing(player):
    await playing(player)
    assert player.state == PlayerState.PLAYING and player.seq == 1 and player.lives == 6


async def test_old_or_repeated_seq_is_discarded(player, caplog):
    caplog.set_level(logging.DEBUG)
    await playing(player)
    await player.on_state(None, state(4, masked="_a_a_a", lives=5))
    await player.on_state(None, state(3, masked="b_____", lives=2))
    await player.on_state(None, state(4, masked="b_____", lives=2))
    assert (player.seq, player.masked, player.lives) == (4, "_a_a_a", 5)
    assert "STATE seq=3 ignored (already at seq=4)" in caplog.text
    assert "STATE seq=4 applied: _a_a_a lives=5 turn=bob@CIC" in caplog.text
    assert "(você)" not in caplog.text.split("applied:")[1].splitlines()[0]  # texto da especificação


async def test_hash_ok_and_cheat_detected(player, caplog):
    caplog.set_level(logging.INFO)
    await playing(player, "banana")
    await player.on_game_over(None, from_host(
        "GAME_OVER", result="WON", word="banana", winner=ME, scores={ME: 6}))
    assert "GAME_OVER WON word=banana winner=bob@CIC — hash OK" in caplog.text
    assert not player.active

    caplog.clear()
    await playing(player, "banana")
    await player.on_game_over(None, from_host(
        "GAME_OVER", result="WON", word="cheater", winner=ME, scores={}))
    assert "host cheated: hash mismatch" in caplog.text
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert not player.active  # a partida termina normalmente


async def test_aborted_without_extra_fields_is_tolerated(player):
    await playing(player)
    await player.on_game_over(None, from_host("GAME_OVER", result="ABORTED"))
    assert not player.active


async def test_host_stale_aborts_and_other_peers_are_ignored(player, caplog):
    await playing(player)
    await player.on_peer_stale("carol@CIC")
    assert player.active
    await player.on_peer_stale(HOST)
    assert not player.active and player.host_id is None and player.seq == 0
    assert f"Host {HOST} unreachable — game aborted" in caplog.text


async def test_rejoin_when_host_comes_back(player, sender):
    await playing(player)
    await player.on_peer_stale(HOST)
    sender.clear()
    await player.on_peer_connected("carol@CIC")
    assert not sender.sent
    await player.on_peer_connected(HOST)
    assert sender.last()["type"] == "JOIN" and sender.last()["game_id"] == GID
    # o rejoin chega sem GAME_START: o STATE sozinho basta
    await player.on_join_ok(None, from_host("JOIN_OK", players=[ME], rejoin=True))
    await player.on_state(None, state(7, masked="b_____"))
    assert player.state == PlayerState.PLAYING and player.seq == 7


async def test_rejoin_keeps_hash_lives_and_timeout(player, caplog):
    caplog.set_level(logging.INFO)
    await player.join(HOST, GID)
    await player.on_join_ok(None, from_host("JOIN_OK", players=[ME], rejoin=False))
    await player.on_game_start(None, from_host(
        "GAME_START", players=[ME], lives=4, word_length=6,
        word_hash=word_hash("banana"), turn_timeout=45))
    await player.on_state(None, state(1, lives=4))
    await player.on_peer_stale(HOST)
    await player.on_peer_connected(HOST)
    await player.on_join_ok(None, from_host("JOIN_OK", players=[ME], rejoin=True))
    await player.on_state(None, state(5, lives=3))
    assert (player.lives_total, player.turn_timeout) == (4, 45)
    await player.on_game_over(None, from_host("GAME_OVER", result="WON", word="banana", winner=ME, scores={}))
    assert "hash OK" in caplog.text  # a verificação não some depois do rejoin


async def test_new_join_discards_pending_rejoin(player, sender):
    await playing(player)
    await player.on_peer_stale(HOST)
    await player.join("dave@CIC", "dave@CIC/1")
    await player.on_join_err(None, incoming("JOIN_ERR", "dave@CIC", ME, game_id="dave@CIC/1", reason="game_full"))
    sender.clear()
    await player.on_peer_connected(HOST)  # o host antigo volta: não deve reentrar sozinho
    assert not sender.sent and not player.active


async def test_game_over_with_non_string_word_does_not_crash(player, caplog):
    caplog.set_level(logging.INFO)
    await playing(player)
    await player.on_game_over(None, from_host("GAME_OVER", result="WON", word=123, winner=ME, scores={}))
    assert "hash not verified" in caplog.text and not player.active


# --- regressões da auditoria (sonda G, janela de rejoin, last_guess, word_length) ---


async def test_G_rejoin_is_dropped_when_peer_became_host(sender):
    cfg = Config(name="bob", namespace="CIC")
    host = GameHost(cfg, sender)
    pl = GamePlayer(cfg, sender, busy=lambda: host.active)
    await playing(pl)
    await pl.on_peer_stale(HOST)
    await host.create("gato")  # o usuário virou host enquanto alice estava fora
    sender.clear()
    await pl.on_peer_connected(HOST)  # não pode levantar nem enviar JOIN
    assert not sender.sent and not pl.active and pl._last_game is None
    await host.shutdown()


async def test_busy_blocks_join(sender):
    pl = GamePlayer(Config(name="bob", namespace="CIC"), sender, busy=lambda: True)
    with pytest.raises(RuntimeError):
        await pl.join(HOST, GID)
    assert not pl.active and not sender.sent


async def test_rejoin_window_expires(player, sender, monkeypatch):
    from forca import game_player

    await playing(player)
    await player.on_peer_stale(HOST)
    monkeypatch.setattr(game_player, "REJOIN_WINDOW", -1.0)
    sender.clear()
    await player.on_peer_connected(HOST)
    assert not sender.sent and player._last_game is None


async def test_last_guess_is_announced_only_once(player, caplog):
    caplog.set_level(logging.INFO, logger="Game")
    await playing(player)
    last = {"player": "carol@CIC", "letter": "a", "correct": True}
    await player.on_state(None, state(2, last=last))
    await player.on_state(None, state(3, last=last))  # STATE de LEAVE/queda repete o último
    await player.on_state(None, state(4, last={"player": ME, "letter": "b", "correct": False}))
    assert caplog.text.count("carol@CIC: letter=a") == 1
    assert caplog.text.count(f"{ME}: letter=b") == 1


async def test_game_start_with_absurd_word_length_is_refused(player):
    await player.join(HOST, GID)
    for bad in (10**9, 2, 21, -1, "4"):
        await player.on_game_start(None, from_host(
            "GAME_START", players=[ME], lives=6, word_length=bad,
            word_hash="x", turn_timeout=30))
        assert player.state == PlayerState.JOINED and player.masked == ""


async def test_malformed_last_guess_does_not_crash(player):
    await playing(player)
    await player.on_state(None, state(2, last="lixo"))
    assert player.seq == 2


async def test_no_rejoin_after_leave_or_in_lobby(player, sender):
    await player.join(HOST, GID)  # ainda no lobby
    await player.on_peer_stale(HOST)
    sender.clear()
    await player.on_peer_connected(HOST)
    assert not sender.sent


async def test_guess_sends_and_needs_playing(player, sender):
    await player.guess_letter("a")
    assert not sender.sent  # fora de partida
    await playing(player)
    sender.clear()
    await player.guess_letter("a")
    await player.guess_word("banana")
    assert sender.sent[0][1]["letter"] == "a" and sender.sent[1][1]["word"] == "banana"
    assert "word" not in sender.sent[0][1]


async def test_rejected_guess_result_warns(player, caplog):
    await playing(player)
    await player.on_guess_result(None, from_host("GUESS_RESULT", accepted=False, reason="not_your_turn"))
    assert "not_your_turn" in caplog.text


async def test_leave_sends_leave_and_goes_idle(player, sender):
    await playing(player)
    await player.leave()
    assert sender.last()["type"] == "LEAVE" and not player.active


async def test_messages_from_strangers_or_other_games_are_ignored(player, sender):
    await playing(player)
    sender.clear()
    await player.on_state(None, incoming("STATE", "mallory@CIC", ME, game_id=GID, seq=9,
        masked="b_____", wrong_letters=[], lives=1, turn=ME, players=[ME], last_guess=None))
    await player.on_state(None, incoming("STATE", HOST, ME, game_id="other/1", seq=9,
        masked="b_____", wrong_letters=[], lives=1, turn=ME, players=[ME], last_guess=None))
    assert player.seq == 1
    errors = sender.of_type("ERROR")  # decisão 14: ignora e responde ERROR invalid_state
    assert [(m["dst"], m["code"]) for m in errors] == [("mallory@CIC", "invalid_state"), (HOST, "invalid_state")]
    sender.clear()
    await player.on_game_start(None, incoming("GAME_START", "mallory@CIC", ME, game_id=GID,
        players=[ME], lives=1, word_length=4, word_hash="x", turn_timeout=30))
    assert sender.last()["code"] == "invalid_state" and player.lives == 6


async def test_status_lines_has_every_required_field(player):
    assert "não está" in player.status_lines()[0]
    await playing(player)
    await player.on_state(None, state(2, masked="_a_a_a", lives=5, wrong=["e"]))
    text = "\n".join(player.status_lines())
    for piece in (GID, f"host: {HOST}", "RUNNING", "_ a _ a _ a", "Vidas: 5 / 6",
                  "Erradas: e", "bob@CIC, carol@CIC", "Vez de: bob@CIC (você)", "s restantes"):
        assert piece in text


# --- host + 2 jogadores ligados por um barramento em memória (cenários 2 e 4) ---

ROUTES = {
    "GAME_LIST": "on_game_list", "JOIN": "on_join", "LEAVE": "on_leave", "GUESS": "on_guess",
    "JOIN_OK": "on_join_ok", "JOIN_ERR": "on_join_err", "LEAVE_OK": "on_leave_ok",
    "GAME_START": "on_game_start", "STATE": "on_state",
    "GUESS_RESULT": "on_guess_result", "GAME_OVER": "on_game_over",
}


def make_bus(*names):
    nodes, log = {}, []

    async def deliver(dst, msg):
        p.validate_envelope(msg, dst)
        log.append((dst, msg))
        node = nodes[dst]
        target = node.host if msg["type"] in ("GAME_LIST", "JOIN", "LEAVE", "GUESS") else node.player
        await getattr(target, ROUTES[msg["type"]])(None, msg)
        return True

    for name in names:
        cfg = Config(name=name, namespace="CIC")
        nodes[cfg.peer_id] = SimpleNamespace(
            host=GameHost(cfg, deliver), player=GamePlayer(cfg, deliver))
    return nodes, log


async def test_full_game_win_between_host_and_two_players():
    nodes, log = make_bus("alice", "bob", "carol")
    alice, bob, carol = nodes["alice@CIC"], nodes["bob@CIC"], nodes["carol@CIC"]
    gid = await alice.host.create("casa")
    await bob.player.join("alice@CIC", gid)
    await carol.player.join("alice@CIC", gid)
    await alice.host.start()
    assert bob.player.seq == carol.player.seq == 1 and bob.player.turn == "bob@CIC"

    await carol.player.guess_letter("a")  # fora da vez: nada muda
    assert alice.host._seq == 1 and bob.player.seq == 1

    await bob.player.guess_letter("c")
    await carol.player.guess_letter("a")
    assert bob.player.masked == "ca_a" and bob.player.seq == carol.player.seq == 3
    await bob.player.guess_letter("s")
    assert not bob.player.active and not carol.player.active
    over = [m for _, m in log if m["type"] == "GAME_OVER"]
    assert {m["winner"] for m in over} == {"bob@CIC"}
    assert over[0]["scores"] == {"bob@CIC": 2, "carol@CIC": 2}
    await alice.host.shutdown()
