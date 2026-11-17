import asyncio
import logging

import pytest

from forca import game_host
from forca.config import Config
from forca.game_host import GameHost
from forca.hangman import word_hash
from forca.models import GameStatus

from helpers import FakeSender, incoming

HOST = "alice@CIC"


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
async def host(sender):
    h = GameHost(Config(name="alice", namespace="CIC"), sender)
    yield h
    await h.shutdown()  # cancela a tarefa de expiração, se houver


async def join(host, who):
    await host.on_join(None, incoming("JOIN", who, HOST, game_id=host.game_id))


async def guess(host, who, **kw):
    await host.on_guess(None, incoming("GUESS", who, HOST, game_id=host.game_id, **kw))


async def running(host, sender, word="banana", *players, max_players=None):
    await host.create(word, max_players)
    for pl in players:
        await join(host, pl)
    await host.start()
    sender.clear()


# --- 02.2: create / describe / GAME_LIST ---


async def test_create_and_describe(host):
    gid = await host.create("Banana", 3)
    assert gid.startswith("alice@CIC/") and len(gid.split("/")[1]) == 8
    assert host.status == GameStatus.OPEN and host.active
    assert host.describe() == {
        "game_id": gid, "host": HOST, "status": "OPEN", "players": [],
        "max_players": 3, "lives": 6, "word_length": 6,
    }


async def test_create_twice_and_invalid_word(host):
    with pytest.raises(ValueError):
        await host.create("co-op")
    assert not host.active
    await host.create("casa")
    with pytest.raises(RuntimeError):
        await host.create("casa")


async def test_game_list_without_game_is_empty_and_repeats_msg_id(host, sender):
    req = incoming("GAME_LIST", "bob@CIC", HOST)
    await host.on_game_list(None, req)
    res = sender.last()
    assert res["type"] == "GAME_LIST_OK" and res["games"] == []
    assert res["msg_id"] == req["msg_id"] and (res["src"], res["dst"]) == (HOST, "bob@CIC")


async def test_game_list_with_game(host, sender):
    await host.create("casa")
    await host.on_game_list(None, incoming("GAME_LIST", "bob@CIC", HOST))
    assert sender.last()["games"][0]["word_length"] == 4


async def test_join_ok_in_order_and_duplicate(host, sender):
    await host.create("casa")
    await join(host, "carol@CIC")
    await join(host, "bob@CIC")
    oks = sender.of_type("JOIN_OK")
    assert oks[1]["players"] == ["carol@CIC", "bob@CIC"] and oks[1]["rejoin"] is False
    await join(host, "bob@CIC")
    assert sender.last()["reason"] == "already_joined"


async def test_join_errors(host, sender):
    await host.on_join(None, incoming("JOIN", "bob@CIC", HOST, game_id="x/1"))
    assert sender.last()["reason"] == "unknown_game"
    await host.create("casa", 1)
    await host.on_join(None, incoming("JOIN", "bob@CIC", HOST, game_id="alice@CIC/00000000"))
    assert sender.last()["reason"] == "unknown_game"
    await join(host, "bob@CIC")
    await join(host, "carol@CIC")
    assert sender.last()["reason"] == "game_full"
    await host.start()
    await join(host, "dave@CIC")
    assert sender.last()["reason"] == "game_running"
    await guess(host, "bob@CIC", word="casa")  # termina a partida: FINISHED
    await join(host, "dave@CIC")
    assert sender.last()["reason"] == "game_finished"


async def test_leave_in_lobby(host, sender):
    await host.create("casa")
    await join(host, "bob@CIC")
    await host.on_leave(None, incoming("LEAVE", "bob@CIC", HOST, game_id=host.game_id))
    assert sender.last()["type"] == "LEAVE_OK"
    assert host.describe()["players"] == []


# --- 02.3: start / GAME_START / STATE ---


async def test_start_without_players_is_refused(host):
    await host.create("casa")
    with pytest.raises(ValueError):
        await host.start()
    assert host.status == GameStatus.OPEN


async def test_start_sends_game_start_then_state_seq1(host, sender):
    await host.create("casa")
    await join(host, "bob@CIC")
    await join(host, "carol@CIC")
    sender.clear()
    await host.start()
    types = [(pid, m["type"]) for pid, m in sender.sent]
    assert types == [
        ("bob@CIC", "GAME_START"), ("carol@CIC", "GAME_START"),
        ("bob@CIC", "STATE"), ("carol@CIC", "STATE"),
    ]
    gs, st = sender.of_type("GAME_START")[0], sender.of_type("STATE")[0]
    assert gs["word_hash"] == word_hash("casa") and gs["players"] == ["bob@CIC", "carol@CIC"]
    assert (gs["lives"], gs["word_length"], gs["turn_timeout"]) == (6, 4, 30)
    assert (st["seq"], st["masked"], st["turn"], st["last_guess"]) == (1, "____", "bob@CIC", None)
    assert st["wrong_letters"] == []


async def test_seq_grows_without_gaps(host, sender):
    await running(host, sender, "banana", "bob@CIC", "carol@CIC")
    await guess(host, "bob@CIC", letter="a")
    await guess(host, "carol@CIC", letter="z")
    await guess(host, "bob@CIC", letter="b")
    assert [m["seq"] for m in sender.of_type("STATE", to="bob@CIC")] == [2, 3, 4]


# --- 02.4: GUESS / turnos / GAME_OVER ---


async def test_correct_letter_updates_state_and_passes_turn(host, sender):
    await running(host, sender, "banana", "bob@CIC", "carol@CIC")
    await guess(host, "bob@CIC", letter="A")
    res = sender.of_type("GUESS_RESULT")[0]
    assert (res["accepted"], res["correct"]) == (True, True)
    st = sender.of_type("STATE", to="carol@CIC")[0]
    assert st["masked"] == "_a_a_a" and st["turn"] == "carol@CIC"
    assert st["last_guess"] == {"player": "bob@CIC", "letter": "a", "correct": True}


async def test_not_your_turn_generates_no_state(host, sender):
    await running(host, sender, "banana", "bob@CIC", "carol@CIC")
    await guess(host, "carol@CIC", letter="a")
    assert sender.of_type("GUESS_RESULT")[0]["reason"] == "not_your_turn"
    assert not sender.of_type("STATE")
    assert host._turn == "bob@CIC" and host._seq == 1 and host._game.lives == 6


async def test_rejections_keep_turn_lives_and_seq(host, sender):
    await running(host, sender, "banana", "bob@CIC", "carol@CIC")
    await guess(host, "bob@CIC", letter="z")
    await guess(host, "carol@CIC", letter="z")  # repetida
    await guess(host, "carol@CIC", letter="1")
    await guess(host, "carol@CIC", word="co-op")
    reasons = [m.get("reason") for m in sender.of_type("GUESS_RESULT")]
    assert reasons == [None, "letter_already_used", "invalid_letter", "invalid_word"]
    assert host._seq == 2 and host._turn == "carol@CIC" and host._game.lives == 5


async def test_guess_in_open_game_by_member_is_game_not_running(host, sender):
    await host.create("casa")
    await join(host, "bob@CIC")
    await guess(host, "bob@CIC", letter="a")
    assert sender.last()["type"] == "GUESS_RESULT" and sender.last()["reason"] == "game_not_running"


async def test_guess_without_game_or_from_non_player_is_error_invalid_state(host, sender):
    req = incoming("GUESS", "bob@CIC", HOST, game_id="alice@CIC/00000000", letter="a")
    await host.on_guess(None, req)  # host sem partida alguma
    err = sender.last()
    assert (err["type"], err["code"], err["ref_msg_id"]) == ("ERROR", "invalid_state", req["msg_id"])
    assert err["msg_id"] != req["msg_id"] and err["dst"] == "bob@CIC"
    await running(host, sender, "casa", "bob@CIC")
    await guess(host, "mallory@CIC", letter="a")  # existe partida, mas ele não é jogador
    assert sender.last()["type"] == "ERROR" and sender.last()["code"] == "invalid_state"
    assert host._seq == 1 and host._game.lives == 6


async def test_win_by_letters(host, sender):
    await running(host, sender, "casa", "bob@CIC")
    for letter in "cas":
        await guess(host, "bob@CIC", letter=letter)
    over = sender.of_type("GAME_OVER")[0]
    assert (over["result"], over["word"], over["winner"]) == ("WON", "casa", "bob@CIC")
    assert over["scores"] == {"bob@CIC": 4} and "reason" not in over
    assert host.status == GameStatus.FINISHED


async def test_wrong_word_costs_life_then_right_word_wins(host, sender):
    await running(host, sender, "banana", "bob@CIC", "carol@CIC")
    await guess(host, "bob@CIC", letter="a")  # bob: 3
    await guess(host, "carol@CIC", word="bananas")
    assert sender.of_type("STATE", to="bob@CIC")[-1]["lives"] == 5
    assert sender.of_type("STATE", to="bob@CIC")[-1]["last_guess"]["word"] == "bananas"
    await guess(host, "bob@CIC", word="Banana")  # +3 restantes
    over = sender.of_type("GAME_OVER", to="carol@CIC")[0]
    assert over["winner"] == "bob@CIC" and over["scores"] == {"bob@CIC": 6, "carol@CIC": 0}


async def test_lost_has_no_winner_and_reveals_word(host, sender):
    host.cfg = Config(name="alice", namespace="CIC", lives=2)
    await running(host, sender, "banana", "bob@CIC")
    await guess(host, "bob@CIC", letter="z")
    await guess(host, "bob@CIC", letter="y")
    over = sender.of_type("GAME_OVER")[0]
    assert (over["result"], over["winner"], over["word"]) == ("LOST", None, "banana")


async def test_finished_listed_then_expires(host, sender, monkeypatch):
    await running(host, sender, "casa", "bob@CIC")
    await guess(host, "bob@CIC", word="casa")
    await host.on_game_list(None, incoming("GAME_LIST", "bob@CIC", HOST))
    assert sender.last()["games"][0]["status"] == "FINISHED"
    host._cancel_expire()
    monkeypatch.setattr(game_host, "FINISHED_TTL", 0)
    host._expire_task = asyncio.create_task(host._expire(host.game_id))
    await asyncio.sleep(0.01)
    assert host.status == GameStatus.IDLE
    await host.on_game_list(None, incoming("GAME_LIST", "bob@CIC", HOST))
    assert sender.last()["games"] == []


async def test_last_player_leaving_during_guess_reply_does_not_crash(caplog):
    caplog.set_level(logging.INFO)
    class LeavingSender(FakeSender):
        host = None

        async def __call__(self, peer_id, msg):
            ok = await super().__call__(peer_id, msg)
            if msg["type"] == "GUESS_RESULT":  # o jogador sai no meio do await
                await self.host.on_leave(None, incoming("LEAVE", peer_id, HOST, game_id=self.host.game_id))
            return ok

    s = LeavingSender()
    h = s.host = GameHost(Config(name="alice", namespace="CIC"), s)
    await running(h, s, "banana", "bob@CIC")
    caplog.clear()
    await guess(h, "bob@CIC", letter="z")
    assert h.status == GameStatus.FINISHED
    assert h._seq == 1 and "Turn:" not in caplog.text  # nenhum STATE/turno fantasma depois do aborto
    await h.shutdown()


async def test_second_guess_during_reply_does_not_get_a_second_turn():
    class ReentrantSender(FakeSender):
        host = None
        fired = False

        async def __call__(self, peer_id, msg):
            ok = await super().__call__(peer_id, msg)
            if msg["type"] == "GUESS_RESULT" and not self.fired:
                self.fired = True  # o mesmo jogador manda outro GUESS durante o await
                await guess(self.host, "bob@CIC", letter="y")
            return ok

    s = ReentrantSender()
    h = s.host = GameHost(Config(name="alice", namespace="CIC"), s)
    await running(h, s, "banana", "bob@CIC", "carol@CIC")
    await guess(h, "bob@CIC", letter="z")
    results = s.of_type("GUESS_RESULT")
    assert results[0]["accepted"] is True and results[1]["reason"] == "not_your_turn"
    assert h._game.lives == 5 and h._turn == "carol@CIC"
    await h.shutdown()


async def test_host_logs_use_spec_texts(host, sender, caplog):
    caplog.set_level(logging.INFO)
    await host.create("banana", 4)
    await join(host, "bob@CIC")
    await host.start()
    await guess(host, "bob@CIC", letter="n")
    await host.on_peer_stale("bob@CIC")
    for text in ("created (word_length=6, lives=6)", "bob@CIC joined (1/4)",
                 "Turn: bob@CIC (timeout 30 s)", "GUESS bob@CIC letter=n → correct, masked=__n_n_",
                 "Player bob@CIC STALE — removed from game"):
        assert text in caplog.text, text


# --- regressões da auditoria (sondas A-E) ---


class HookSender(FakeSender):
    """Sender que executa `hook(host, peer_id, msg)` uma vez, no meio de um envio."""

    def __init__(self, when, hook):
        super().__init__()
        self.host, self.when, self.hook, self.fired = None, when, hook, False

    async def __call__(self, peer_id, msg):
        ok = await super().__call__(peer_id, msg)
        if not self.fired and self.when(msg):
            self.fired = True
            await self.hook(self.host, peer_id, msg)
        return ok


def hooked_host(when, hook):
    s = HookSender(when, hook)
    h = s.host = GameHost(Config(name="alice", namespace="CIC"), s)
    return h, s


async def leave(h, who):
    await h.on_leave(None, incoming("LEAVE", who, HOST, game_id=h.game_id))


async def test_A_leave_during_game_over_keeps_host_consistent():
    h, s = hooked_host(lambda m: m["type"] == "GAME_OVER", lambda h, pid, m: leave(h, pid))
    await running(h, s, "casa", "bob@CIC")
    await guess(h, "bob@CIC", word="casa")
    assert h.status == GameStatus.FINISHED and h._game is not None
    await h.on_game_list(None, incoming("GAME_LIST", "dave@CIC", HOST))  # não pode levantar
    assert s.last()["games"][0]["status"] == "FINISHED"
    await h.shutdown()


async def test_B_second_guess_after_winning_move_is_refused():
    async def again(h, pid, m):
        await guess(h, pid, letter="z")

    h, s = hooked_host(lambda m: m["type"] == "GUESS_RESULT", again)
    await running(h, s, "casa", "bob@CIC")
    await guess(h, "bob@CIC", word="casa")
    results = s.of_type("GUESS_RESULT")
    assert results[0]["accepted"] is True and results[1]["reason"] == "game_not_running"
    assert h._game.lives == 6
    await h.shutdown()


async def test_C_guess_during_game_over_is_game_not_running():
    async def late(h, pid, m):
        await guess(h, "bob@CIC", letter="x")

    h, s = hooked_host(lambda m: m["type"] == "GAME_OVER", late)
    await running(h, s, "casa", "bob@CIC", "carol@CIC")
    await guess(h, "bob@CIC", letter="c")
    await guess(h, "carol@CIC", word="casa")
    late_result = [m for m in s.of_type("GUESS_RESULT", to="bob@CIC")][-1]
    assert late_result["reason"] == "game_not_running"
    await h.shutdown()


async def test_D_player_leaving_during_game_start_logs_no_turn(caplog):
    caplog.set_level(logging.INFO)
    h, s = hooked_host(lambda m: m["type"] == "GAME_START", lambda h, pid, m: leave(h, pid))
    await h.create("casa")
    await join(h, "bob@CIC")
    await h.start()
    assert h.status == GameStatus.FINISHED and h._seq == 0
    assert not s.of_type("STATE") and "Turn: None" not in caplog.text
    await h.shutdown()


async def test_E_join_in_running_by_listed_player_is_rejoin(host, sender):
    await running(host, sender, "casa", "bob@CIC", "carol@CIC")
    await guess(host, "bob@CIC", letter="c")  # seq 2
    sender.clear()
    await join(host, "carol@CIC")
    ok = sender.of_type("JOIN_OK")[0]
    assert ok["rejoin"] is True and ok["players"] == ["bob@CIC", "carol@CIC"]
    states = sender.of_type("STATE")
    assert [(m["dst"], m["seq"]) for m in states] == [("carol@CIC", 2)]
    assert host._seq == 2 and host._players == ["bob@CIC", "carol@CIC"]


async def test_no_state_after_game_over_when_game_ends_during_rejoin_ok():
    h, s = hooked_host(
        lambda m: m["type"] == "JOIN_OK" and m["rejoin"], lambda h, pid, m: h.cancel())
    await running(h, s, "banana", "bob@CIC", "carol@CIC")
    await h.on_peer_stale("carol@CIC")
    s.clear()
    await join(h, "carol@CIC")
    types = [m["type"] for _, m in s.sent]
    assert "GAME_OVER" in types and "STATE" not in types[types.index("GAME_OVER"):]
    await h.shutdown()


async def test_busy_blocks_create():
    h = GameHost(Config(name="alice", namespace="CIC"), FakeSender(), busy=lambda: True)
    with pytest.raises(RuntimeError):
        await h.create("casa")
    assert not h.active


async def test_new_game_after_finished(host, sender):
    await running(host, sender, "casa", "bob@CIC")
    await guess(host, "bob@CIC", word="casa")
    await host.create("gato")  # FINISHED não bloqueia nova partida
    assert host.status == GameStatus.OPEN


async def test_cancel_sends_aborted_and_finishes(host, sender):
    await running(host, sender, "banana", "bob@CIC", "carol@CIC")
    await host.cancel()
    overs = sender.of_type("GAME_OVER")
    assert {m["dst"] for m in overs} == {"bob@CIC", "carol@CIC"}
    assert all(m["result"] == "ABORTED" and m["reason"] == "host_shutdown" for m in overs)
    # diagrama da especificação: /cancel passa por FINISHED (60 s), só no_players vai a IDLE
    assert host.status == GameStatus.FINISHED and not host.active
    await host.create("gato")  # e já pode criar outra partida
    assert host.status == GameStatus.OPEN


# --- saída / queda de jogador (02.5 parcial: remoção e rejoin) ---


async def test_leave_running_passes_turn_and_broadcasts(host, sender):
    await running(host, sender, "banana", "bob@CIC", "carol@CIC", "dave@CIC")
    await host.on_leave(None, incoming("LEAVE", "bob@CIC", HOST, game_id=host.game_id))
    st = sender.of_type("STATE")[0]
    assert st["players"] == ["carol@CIC", "dave@CIC"] and st["turn"] == "carol@CIC"
    assert len(sender.of_type("STATE")) == 2


async def test_last_player_leaving_aborts_through_finished(host, sender):
    await running(host, sender, "banana", "bob@CIC")
    await host.on_leave(None, incoming("LEAVE", "bob@CIC", HOST, game_id=host.game_id))
    assert host.status == GameStatus.FINISHED and not host.active  # decisão 12: 60 s e depois IDLE
    await host.on_game_list(None, incoming("GAME_LIST", "dave@CIC", HOST))
    assert sender.last()["games"][0]["status"] == "FINISHED"


async def test_last_player_leaving_in_open_game_keeps_it_open(host, sender):
    await host.create("casa")
    await join(host, "bob@CIC")
    await host.on_leave(None, incoming("LEAVE", "bob@CIC", HOST, game_id=host.game_id))
    assert host.status == GameStatus.OPEN and host.describe()["players"] == []


async def test_stale_player_removed_then_rejoin(host, sender):
    await running(host, sender, "banana", "bob@CIC", "carol@CIC")
    await guess(host, "bob@CIC", letter="a")  # bob: 3 pontos, vez de carol
    await host.on_peer_stale("carol@CIC")
    assert host._players == ["bob@CIC"] and host._turn == "bob@CIC"
    sender.clear()
    await join(host, "carol@CIC")
    ok = sender.of_type("JOIN_OK")[0]
    assert ok["rejoin"] is True and ok["players"] == ["bob@CIC", "carol@CIC"]
    assert sender.of_type("STATE", to="carol@CIC")[0]["players"] == ["bob@CIC", "carol@CIC"]


# --- 02.5: timeout de turno (cenário 6) e queda na vez do jogador (cenário 7) ---


class YieldingSender(FakeSender):
    """Cede o controle ao loop em cada envio, como um socket de verdade."""

    async def __call__(self, peer_id, msg):
        await asyncio.sleep(0)
        return await super().__call__(peer_id, msg)


def fast_host(sender, timeout):
    return GameHost(Config(name="alice", namespace="CIC", turn_timeout=timeout), sender)


async def test_turn_timeout_skips_turn_without_costing_life(caplog):
    caplog.set_level(logging.INFO)
    s = YieldingSender()
    h = fast_host(s, 1)  # turn_timeout é inteiro no protocolo (GAME_START valida o tipo)
    await running(h, s, "banana", "bob@CIC", "carol@CIC", "dave@CIC")
    await asyncio.sleep(1.3)  # um timeout (1 s); o segundo só em ~2 s
    states = s.of_type("STATE")
    assert {m["dst"] for m in states} == {"bob@CIC", "carol@CIC", "dave@CIC"}  # difusão completa
    st = states[0]
    assert st["seq"] == 2 and st["turn"] == "carol@CIC" and st["lives"] == 6
    assert st["last_guess"] == {"player": "bob@CIC", "timeout": True}
    assert "Turn timeout for bob@CIC — skipping" in caplog.text
    await h.shutdown()


async def test_turn_timer_restarts_on_every_state():
    s = YieldingSender()
    h = fast_host(s, 1)
    await running(h, s, "banana", "bob@CIC", "carol@CIC")
    await asyncio.sleep(0.6)
    await guess(h, "bob@CIC", letter="a")  # novo STATE: o relógio recomeça
    await asyncio.sleep(0.6)  # 1,2 s desde o início, 0,6 s desde a jogada: ainda sem timeout
    assert h._seq == 2 and h._turn == "carol@CIC"
    await asyncio.sleep(0.7)  # passou de 1 s desde a jogada
    assert h._seq == 3 and h._last_guess == {"player": "carol@CIC", "timeout": True}
    await h.shutdown()


async def test_turn_timer_is_cancelled_when_game_ends_or_shuts_down():
    s = YieldingSender()
    h = fast_host(s, 1)
    await running(h, s, "casa", "bob@CIC")
    assert h._turn_task is not None
    await guess(h, "bob@CIC", word="casa")  # vitória
    assert h._turn_task is None
    await running(h, s, "gato", "bob@CIC")
    await h.cancel()
    assert h._turn_task is None
    await running(h, s, "pato", "bob@CIC")
    await h.shutdown()
    await asyncio.sleep(0)  # deixa o loop concluir os cancelamentos
    assert h._turn_task is None and not [t for t in asyncio.all_tasks() if "GameHost._turn_timer" in repr(t)]


async def test_stale_on_players_own_turn_passes_the_turn(host, sender):
    await running(host, sender, "banana", "bob@CIC", "carol@CIC")
    await host.on_peer_stale("bob@CIC")  # kill -9 na vez do bob
    st = sender.of_type("STATE")[-1]
    assert st["turn"] == "carol@CIC" and st["players"] == ["carol@CIC"]
    await guess(host, "carol@CIC", letter="a")  # a partida continua
    assert host.status == GameStatus.RUNNING


# --- GameHost.status_lines() (a CLI delega o /status ao host) ---


async def test_host_status_lines(host, sender):
    assert host.status_lines() == []  # sem partida: quem chama mostra o do jogador
    await host.create("banana")
    assert "status: OPEN" in host.status_lines()[0]
    await join(host, "bob@CIC")
    await join(host, "carol@CIC")
    await host.start()
    await guess(host, "bob@CIC", letter="a")
    text = "\n".join(host.status_lines())
    for piece in (host.game_id, f"host: {HOST}", "status: RUNNING", "_ a _ a _ a", "banana",
                  "Vidas: 6 / 6", "Erradas: -", "bob@CIC, carol@CIC", "Vez de: carol@CIC", "s restantes"):
        assert piece in text, piece
    await guess(host, "carol@CIC", letter="z")
    assert "Erradas: z" in "\n".join(host.status_lines())
    await guess(host, "bob@CIC", word="banana")
    assert "status: FINISHED" in host.status_lines()[0]


async def test_timer_ignores_stale_seq_and_finished_game(sender):
    h = GameHost(Config(name="alice", namespace="CIC", turn_timeout=0), sender)
    await running(h, sender, "banana", "bob@CIC", "carol@CIC")
    h._cancel_turn_timer()  # só o timer chamado à mão abaixo
    await h._turn_timer(h._seq - 1)  # timer velho: o STATE já mudou desde que ele nasceu
    assert not sender.sent and h._last_guess is None
    await h.cancel()
    sender.clear()
    await h._turn_timer(h._seq)  # partida já encerrada
    assert not sender.of_type("STATE")
    await h.shutdown()


# --- revisão da 02.5: log depois do fim e timer que escapa do shutdown ---


async def test_no_turn_log_after_last_player_leaves_during_timeout_broadcast(caplog):
    caplog.set_level(logging.INFO)

    class LeavingOnTimeout(YieldingSender):
        host = None

        async def __call__(self, peer_id, msg):
            ok = await super().__call__(peer_id, msg)
            if msg["type"] == "STATE" and (msg.get("last_guess") or {}).get("timeout"):
                await leave(self.host, peer_id)  # o único jogador sai no meio da difusão
            return ok

    s = LeavingOnTimeout()
    h = s.host = fast_host(s, 1)
    await running(h, s, "banana", "bob@CIC")
    caplog.clear()
    await asyncio.sleep(1.3)
    assert "Turn timeout for bob@CIC — skipping" in caplog.text
    assert "finished: ABORTED (no_players)" in caplog.text
    assert "Turn: None" not in caplog.text
    await h.shutdown()


async def test_shutdown_cancels_the_timer_that_is_still_broadcasting():
    class BlockingSender(FakeSender):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()

        async def __call__(self, peer_id, msg):
            if msg["type"] == "STATE" and msg["seq"] >= 2:  # o STATE do timeout
                self.entered.set()
                await self.release.wait()  # socket lento
            return await super().__call__(peer_id, msg)

    s = BlockingSender()
    h = fast_host(s, 1)
    await running(h, s, "banana", "bob@CIC", "carol@CIC")
    try:
        await asyncio.wait_for(s.entered.wait(), 3)  # o timer estourou e está difundindo
        await h.shutdown()
        await asyncio.sleep(0)
        assert not [t for t in asyncio.all_tasks() if "GameHost._turn_timer" in repr(t)]
    finally:
        s.release.set()
