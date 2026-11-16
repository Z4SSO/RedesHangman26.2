import json

import pytest

from forca import protocol as p
from forca.config import Config, load_config


def make_guess(**extra):
    return p.new_message(
        "GUESS", src="bob@CIC", dst="alice@CIC", game_id="alice@CIC/3f9a2c1b", **extra
    )


def test_new_message_fills_envelope():
    msg = p.new_message("GAME_LIST", src="bob@CIC", dst="alice@CIC")
    assert msg["type"] == "GAME_LIST"
    assert msg["ttl"] == 1
    assert len(msg["msg_id"]) == 36


def test_connection_messages_omit_src_dst():
    msg = p.new_message("PING", timestamp=p.now_iso(millis=True))
    assert "src" not in msg and "dst" not in msg
    p.validate_envelope(msg, "alice@CIC")


def test_reply_repeats_msg_id_and_swaps_peers():
    req = make_guess(letter="a")
    res = p.reply(req, "GUESS_RESULT", game_id=req["game_id"], accepted=True, correct=True)
    assert res["msg_id"] == req["msg_id"]
    assert res["src"] == "alice@CIC" and res["dst"] == "bob@CIC"


def test_encode_is_single_line_and_decode_roundtrip():
    msg = make_guess(letter="á")
    raw = p.encode(msg)
    assert raw.endswith(b"\n") and raw.count(b"\n") == 1
    assert p.decode(raw.strip()) == msg


def test_encode_rejects_oversized_line():
    msg = make_guess(word="x" * 40000)
    with pytest.raises(p.ProtocolError):
        p.encode(msg)


@pytest.mark.parametrize("line", [b"not json", b"[1,2]", b"\xff\xfe", b""])
def test_decode_rejects_garbage(line):
    with pytest.raises(p.ProtocolError) as exc:
        p.decode(line)
    assert exc.value.code == p.ErrorCode.BAD_JSON


def test_unknown_type():
    msg = p.new_message("FOO", src="a@x", dst="b@x")
    with pytest.raises(p.ProtocolError) as exc:
        p.validate_envelope(msg, "b@x")
    assert exc.value.code == p.ErrorCode.UNKNOWN_TYPE


def test_not_for_me():
    msg = make_guess(letter="a")
    with pytest.raises(p.ProtocolError) as exc:
        p.validate_envelope(msg, "carol@CIC")
    assert exc.value.code == p.ErrorCode.NOT_FOR_ME


def test_wrong_ttl_is_silent_discard():
    msg = make_guess(letter="a")
    msg["ttl"] = 2
    with pytest.raises(p.ProtocolError) as exc:
        p.validate_envelope(msg, "alice@CIC")
    assert exc.value.silent is True


def test_missing_src_is_bad_request():
    msg = make_guess(letter="a")
    del msg["src"]
    with pytest.raises(p.ProtocolError) as exc:
        p.validate_envelope(msg, "alice@CIC")
    assert exc.value.code == p.ErrorCode.BAD_REQUEST


def test_guess_needs_exactly_one_of_letter_or_word():
    for extra in ({}, {"letter": "a", "word": "casa"}):
        with pytest.raises(p.ProtocolError):
            p.validate_envelope(make_guess(**extra), "alice@CIC")
    p.validate_envelope(make_guess(letter="a"), "alice@CIC")
    p.validate_envelope(make_guess(word="casa"), "alice@CIC")


def test_missing_required_field():
    msg = p.new_message("JOIN", src="bob@CIC", dst="alice@CIC")
    with pytest.raises(p.ProtocolError) as exc:
        p.validate_envelope(msg, "alice@CIC")
    assert exc.value.code == p.ErrorCode.BAD_REQUEST


def test_receiver_tolerates_aborted_game_over_without_optional_fields():
    msg = p.new_message(
        "GAME_OVER", src="alice@CIC", dst="bob@CIC",
        game_id="alice@CIC/3f9a2c1b", result="ABORTED", reason="host_shutdown",
    )
    p.validate_envelope(msg, "bob@CIC")


def test_receiver_tolerates_state_without_last_guess():
    msg = p.new_message(
        "STATE", src="alice@CIC", dst="bob@CIC", game_id="alice@CIC/3f9a2c1b",
        seq=1, masked="____", wrong_letters=[], lives=6, turn="bob@CIC",
        players=["bob@CIC"],
    )
    p.validate_envelope(msg, "bob@CIC")


def test_make_error_points_to_cause():
    req = make_guess(letter="a")
    err = p.make_error(req, p.ErrorCode.INVALID_STATE, "no game", src="alice@CIC")
    assert err["ref_msg_id"] == req["msg_id"]
    assert err["msg_id"] != req["msg_id"]
    assert err["dst"] == "bob@CIC"


def test_peer_id_helpers():
    assert p.make_peer_id("alice", "CIC") == "alice@CIC"
    assert p.split_peer_id("alice@CIC") == ("alice", "CIC")


def test_config_defaults_and_overrides(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"name": "bob", "listen_port": 8082}))
    cfg = load_config(path, {"namespace": "UnB", "name": None})
    assert cfg.name == "bob" and cfg.namespace == "UnB"
    assert cfg.peer_id == "bob@UnB"
    assert cfg.ping_interval == Config().ping_interval


def test_config_rejects_unknown_key(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"nme": "typo"}))
    with pytest.raises(ValueError):
        load_config(path)


def _state(**over):
    fields = dict(
        game_id="alice@CIC/3f9a2c1b", seq=1, masked="____", wrong_letters=[],
        lives=6, turn="bob@CIC", players=["bob@CIC"],
    )
    fields.update(over)
    return p.new_message("STATE", src="alice@CIC", dst="bob@CIC", **fields)


@pytest.mark.parametrize(
    "over",
    [
        {"seq": "1"},
        {"seq": True},
        {"players": 5},
        {"players": [1, 2]},
        {"wrong_letters": "e"},
        {"masked": None},
        {"last_guess": "x"},
    ],
)
def test_wrong_field_type_is_bad_request(over):
    with pytest.raises(p.ProtocolError) as exc:
        p.validate_envelope(_state(**over), "bob@CIC")
    assert exc.value.code == p.ErrorCode.BAD_REQUEST
    assert not exc.value.silent


def test_state_with_null_last_guess_is_valid():
    p.validate_envelope(_state(last_guess=None), "bob@CIC")


def test_game_over_winner_null_is_valid():
    msg = p.new_message(
        "GAME_OVER", src="alice@CIC", dst="bob@CIC", game_id="g",
        result="LOST", word="banana", winner=None, scores={"bob@CIC": 1},
    )
    p.validate_envelope(msg, "bob@CIC")


def test_join_ok_rejoin_must_be_bool():
    msg = p.new_message(
        "JOIN_OK", src="alice@CIC", dst="bob@CIC", game_id="g",
        players=["bob@CIC"], rejoin="false",
    )
    with pytest.raises(p.ProtocolError) as exc:
        p.validate_envelope(msg, "bob@CIC")
    assert exc.value.code == p.ErrorCode.BAD_REQUEST


def test_hello_features_must_be_list_of_str():
    msg = p.new_message(
        "HELLO", peer_id="bob@CIC", version="1.0", features="hangman"
    )
    with pytest.raises(p.ProtocolError):
        p.validate_envelope(msg)
