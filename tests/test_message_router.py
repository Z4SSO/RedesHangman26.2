# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
import asyncio
import logging

import pytest

from forca import protocol as p
from forca.message_router import MessageRouter

ME = "alice@CIC"


class FakeConnection:
    def __init__(self, peer_id="bob@CIC", features=("hangman",)):
        self.peer_id, self.features, self.sent = peer_id, list(features), []

    async def send(self, msg):
        self.sent.append(msg)
        return True


class Recorder:
    """Handler que guarda o que recebeu."""

    def __init__(self):
        self.calls = []

    async def __call__(self, conn, msg):
        self.calls.append((conn, msg))


@pytest.fixture
def conn():
    return FakeConnection()


@pytest.fixture
def router():
    async def send(peer_id, msg):
        return True

    return MessageRouter(ME, send)


def game_list(src="bob@CIC", **kw):
    return p.new_message("GAME_LIST", src=src, dst=ME, **kw)


async def test_dispatches_to_registered_handler(router, conn):
    h = Recorder()
    router.register("GAME_LIST", h)
    msg = game_list()
    await router.on_message(conn, msg)
    assert h.calls == [(conn, msg)] and not conn.sent


async def test_unknown_type_answers_error_and_keeps_connection(router, conn):
    msg = p.new_message("FOO", src="bob@CIC", dst=ME)
    await router.on_message(conn, msg)
    err = conn.sent[0]
    assert (err["type"], err["code"], err["ref_msg_id"]) == ("ERROR", "unknown_type", msg["msg_id"])
    assert err["dst"] == "bob@CIC" and err["src"] == ME and err["msg_id"] != msg["msg_id"]
    p.validate_envelope(err, "bob@CIC")  # o ERROR é uma mensagem válida


async def test_not_for_me(router, conn):
    await router.on_message(conn, p.new_message("GAME_LIST", src="bob@CIC", dst="carol@CIC"))
    assert conn.sent[0]["code"] == "not_for_me"


async def test_bad_request_for_missing_field_and_wrong_type(router, conn):
    await router.on_message(conn, p.new_message("JOIN", src="bob@CIC", dst=ME))  # sem game_id
    await router.on_message(conn, p.new_message("JOIN", src="bob@CIC", dst=ME, game_id=5))
    assert [m["code"] for m in conn.sent] == ["bad_request", "bad_request"]


async def test_wrong_ttl_is_dropped_silently(router, conn):
    h = Recorder()
    router.register("GAME_LIST", h)
    msg = game_list()
    msg["ttl"] = 2
    await router.on_message(conn, msg)
    assert not conn.sent and not h.calls


async def test_received_error_is_logged_and_never_answered(router, conn, caplog):
    caplog.set_level(logging.WARNING)
    err = p.new_message("ERROR", src="bob@CIC", dst=ME, code="invalid_state", message="no game", ref_msg_id="x")
    await router.on_message(conn, err)
    assert not conn.sent and "invalid_state" in caplog.text
    broken = p.new_message("ERROR", src="bob@CIC", dst=ME)  # ERROR malformado também não gera resposta
    await router.on_message(conn, broken)
    assert not conn.sent


async def test_peer_without_hangman_feature_gets_no_game_messages(router):
    h = Recorder()
    router.register("GAME_LIST", h)
    chat_only = FakeConnection(features=())
    await router.on_message(chat_only, game_list())
    assert not h.calls and not chat_only.sent


async def test_src_must_match_the_connection_peer(router, conn, caplog):
    caplog.set_level(logging.WARNING)
    h = Recorder()
    router.register("GUESS", h)
    spoofed = p.new_message("GUESS", src="carol@CIC", dst=ME, game_id="g", letter="a")
    await router.on_message(conn, spoofed)  # a conexão é do bob
    assert not h.calls and not conn.sent and "does not match" in caplog.text


async def test_handler_that_raises_does_not_stop_the_next_message(router, conn, caplog):
    seen = []

    async def bad(conn, msg):
        raise RuntimeError("boom")

    async def good(conn, msg):
        seen.append(msg["type"])

    router.register("GAME_LIST", bad)
    router.register("LEAVE", good)
    await router.on_message(conn, game_list())
    await router.on_message(conn, p.new_message("LEAVE", src="bob@CIC", dst=ME, game_id="g"))
    assert seen == ["LEAVE"] and "boom" in caplog.text


async def test_message_without_handler_is_ignored(router, conn):
    await router.on_message(conn, game_list())
    assert not conn.sent


async def test_on_bad_line_answers_bad_json(router, conn):
    await router.on_bad_line(conn, ValueError("invalid json"))
    err = conn.sent[0]
    assert (err["type"], err["code"], err["dst"]) == ("ERROR", "bad_json", "bob@CIC")
    p.validate_envelope(err, "bob@CIC")


# --- request() ---


def make_request_router():
    sent = []

    async def send(peer_id, msg):
        sent.append((peer_id, msg))
        return peer_id != "gone@CIC"

    return MessageRouter(ME, send), sent


async def test_request_gets_the_reply_with_the_same_msg_id_and_skips_handlers():
    router, sent = make_request_router()
    h = Recorder()
    router.register("GAME_LIST_OK", h)
    req = p.new_message("GAME_LIST", src=ME, dst="bob@CIC")
    task = asyncio.create_task(router.request("bob@CIC", req))
    await asyncio.sleep(0)
    reply = p.new_message("GAME_LIST_OK", src="bob@CIC", dst=ME, msg_id=req["msg_id"], games=[])
    await router.on_message(FakeConnection("bob@CIC"), reply)
    assert await task == reply and not h.calls and not router._pending


async def test_request_times_out_with_none():
    router, _ = make_request_router()
    req = p.new_message("GAME_LIST", src=ME, dst="bob@CIC")
    assert await router.request("bob@CIC", req, timeout=0.05) is None
    assert not router._pending


async def test_request_to_disconnected_peer_returns_none_at_once():
    router, _ = make_request_router()
    req = p.new_message("GAME_LIST", src=ME, dst="gone@CIC")
    assert await router.request("gone@CIC", req, timeout=5) is None


async def test_two_simultaneous_requests_do_not_mix():
    router, _ = make_request_router()
    r1 = p.new_message("GAME_LIST", src=ME, dst="bob@CIC")
    r2 = p.new_message("GAME_LIST", src=ME, dst="carol@CIC")
    t1 = asyncio.create_task(router.request("bob@CIC", r1))
    t2 = asyncio.create_task(router.request("carol@CIC", r2))
    await asyncio.sleep(0)
    for who, req in (("carol@CIC", r2), ("bob@CIC", r1)):  # respostas em ordem trocada
        reply = p.new_message("GAME_LIST_OK", src=who, dst=ME, msg_id=req["msg_id"], games=[who])
        await router.on_message(FakeConnection(who), reply)
    assert (await t1)["games"] == ["bob@CIC"] and (await t2)["games"] == ["carol@CIC"]


async def test_reply_from_the_wrong_peer_does_not_complete_the_request():
    router, _ = make_request_router()
    h = Recorder()
    router.register("GAME_LIST_OK", h)
    req = p.new_message("GAME_LIST", src=ME, dst="bob@CIC")
    task = asyncio.create_task(router.request("bob@CIC", req, timeout=0.1))
    await asyncio.sleep(0)
    forged = p.new_message("GAME_LIST_OK", src="carol@CIC", dst=ME, msg_id=req["msg_id"], games=[])
    await router.on_message(FakeConnection("carol@CIC"), forged)
    assert await task is None and len(h.calls) == 1  # a falsa vai ao handler, não ao request


# --- revisão: ERROR como resposta a request(), envelopes inválidos e respostas tardias ---


async def test_error_reply_completes_the_request_at_once():
    router, _ = make_request_router()
    req = p.new_message("GAME_LIST", src=ME, dst="bob@CIC")
    task = asyncio.create_task(router.request("bob@CIC", req, timeout=5))
    await asyncio.sleep(0)
    err = p.new_message("ERROR", src="bob@CIC", dst=ME, code="invalid_state", message="x", ref_msg_id=req["msg_id"])
    await router.on_message(FakeConnection("bob@CIC"), err)
    reply = await asyncio.wait_for(task, 1)  # não espera os 5 s
    assert reply["type"] == "ERROR" and reply["code"] == "invalid_state"


async def test_error_from_the_wrong_peer_does_not_complete_the_request():
    router, _ = make_request_router()
    req = p.new_message("GAME_LIST", src=ME, dst="bob@CIC")
    task = asyncio.create_task(router.request("bob@CIC", req, timeout=0.1))
    await asyncio.sleep(0)
    err = p.new_message("ERROR", src="carol@CIC", dst=ME, code="invalid_state", message="x", ref_msg_id=req["msg_id"])
    await router.on_message(FakeConnection("carol@CIC"), err)
    assert await task is None


async def test_invalid_error_messages_are_never_answered(router, conn):
    wrong_ttl = p.new_message("ERROR", src="bob@CIC", dst=ME, code="x", message="y")
    wrong_ttl["ttl"] = 5
    wrong_dst = p.new_message("ERROR", src="bob@CIC", dst="carol@CIC", code="x", message="y")
    await router.on_message(conn, wrong_ttl)
    await router.on_message(conn, wrong_dst)
    assert not conn.sent


@pytest.mark.parametrize("fields", [
    {"type": "STATE", "game_id": "g", "seq": "1", "masked": "_", "wrong_letters": [], "lives": 6, "turn": "a", "players": []},
    {"type": "GUESS", "game_id": "g", "letter": "a", "word": "casa"},  # os dois
    {"type": "GUESS", "game_id": "g"},  # nenhum
    {"type": "GUESS", "game_id": "g", "letter": 7},
])
async def test_bad_request_for_wrong_game_message_shapes(router, conn, fields):
    kind = fields.pop("type")
    await router.on_message(conn, p.new_message(kind, src="bob@CIC", dst=ME, **fields))
    assert [m["code"] for m in conn.sent] == ["bad_request"]


async def test_late_reply_after_timeout_goes_to_the_handler_and_cleans_up():
    router, _ = make_request_router()
    h = Recorder()
    router.register("GAME_LIST_OK", h)
    req = p.new_message("GAME_LIST", src=ME, dst="bob@CIC")
    assert await router.request("bob@CIC", req, timeout=0.05) is None
    late = p.new_message("GAME_LIST_OK", src="bob@CIC", dst=ME, msg_id=req["msg_id"], games=[])
    await router.on_message(FakeConnection("bob@CIC"), late)
    assert len(h.calls) == 1 and not router._pending


async def test_cancelled_request_cleans_the_pending_entry():
    router, _ = make_request_router()
    req = p.new_message("GAME_LIST", src=ME, dst="bob@CIC")
    task = asyncio.create_task(router.request("bob@CIC", req, timeout=5))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not router._pending


# --- revisão 2: linha inválida antes do HELLO ---


async def test_on_bad_line_before_the_hello_sends_nothing(router, caplog):
    caplog.set_level(logging.DEBUG)
    early = FakeConnection(peer_id=None)  # o HELLO ainda não identificou o peer
    await router.on_bad_line(early, ValueError("invalid json"))
    assert not early.sent  # o ERROR sairia sem dst
    assert "bad JSON" in caplog.text
