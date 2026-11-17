"""Testes das issues 01.3 e 01.4: PeerServer/PeerConnection em 127.0.0.1, porta 0."""

import asyncio
import json
import logging
from dataclasses import replace

import pytest

from forca import protocol
from forca.config import Config
from forca.peer_connection import PeerServer


class Node:
    """Um PeerServer de teste que anota o que acontece com ele."""

    def __init__(self, name="alice", **cfg):
        self.cfg = replace(Config(name=name, namespace="CIC", listen_port=0), **cfg)
        self.messages: list[tuple[object, dict]] = []
        self.connected: list[object] = []
        self.closed: list[object] = []
        self.server = PeerServer(self.cfg, self._on_message, self._on_closed, self._on_connected)

    async def _on_message(self, conn, msg):
        self.messages.append((conn, msg))

    async def _on_closed(self, conn):
        self.closed.append(conn)

    async def _on_connected(self, conn):
        self.connected.append(conn)

    async def __aenter__(self):
        await self.server.start()
        return self

    async def __aexit__(self, *exc):
        await self.server.stop()

    async def connect_to(self, other: "Node"):
        return await self.server.connect("127.0.0.1", other.server.port)


async def wait_for(cond, timeout=2.0):
    """Espera `cond()` ficar verdadeira (sem sleep fixo e longo)."""
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("condição não ficou verdadeira a tempo")
        await asyncio.sleep(0.01)


def msg(i):
    return protocol.new_message("GAME_LIST", src="alice@CIC", dst="bob@CIC", n=i)


# --- 01.3: transporte -------------------------------------------------------


async def test_two_messages_arrive_as_two_lines_in_order():
    async with Node("alice") as a, Node("bob") as b:
        conn = await a.connect_to(b)
        assert await conn.send(msg(1)) and await conn.send(msg(2))
        await wait_for(lambda: len(b.messages) == 2)
        assert [m["n"] for _, m in b.messages] == [1, 2]


async def test_concurrent_sends_do_not_mix_lines():
    async with Node("alice") as a, Node("bob") as b:
        conn = await a.connect_to(b)
        await asyncio.gather(*(conn.send(msg(i)) for i in range(50)))
        await wait_for(lambda: len(b.messages) == 50)
        assert sorted(m["n"] for _, m in b.messages) == list(range(50))


async def test_huge_line_closes_that_connection_but_not_the_server():
    async with Node("alice") as a, Node("bob") as b:
        reader, writer = await asyncio.open_connection("127.0.0.1", b.server.port)
        writer.write(b'{"x":"' + b"a" * (protocol.MAX_LINE_BYTES + 10) + b'"}\n')
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 2) == b""  # b fechou
        writer.close()
        # o servidor continua aceitando conexões e mensagens normais
        conn = await a.connect_to(b)
        assert await conn.send(msg(1))
        await wait_for(lambda: len(b.messages) == 1)


async def test_invalid_json_gets_error_bad_json_and_close():
    async with Node("bob") as b:
        reader, writer = await asyncio.open_connection("127.0.0.1", b.server.port)
        writer.write(b"isto nao e json\n")
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), 2)
        reply = json.loads(line)
        assert reply["type"] == "ERROR" and reply["code"] == "bad_json"
        assert await asyncio.wait_for(reader.read(), 2) == b""
        writer.close()
        assert b.messages == []


async def test_other_side_closing_triggers_on_closed():
    async with Node("alice") as a, Node("bob") as b:
        conn = await a.connect_to(b)
        await wait_for(lambda: len(b.connected) == 1)
        await conn.close()
        await wait_for(lambda: len(b.closed) == 1 and len(a.closed) == 1)


async def test_send_on_closed_connection_returns_false():
    async with Node("alice") as a, Node("bob") as b:
        conn = await a.connect_to(b)
        await conn.close()
        assert await conn.send(msg(1)) is False


async def test_connect_to_closed_port_returns_none():
    async with Node("alice") as a, Node("bob") as b:
        port = b.server.port
    # a porta de bob foi liberada: ninguém escuta mais lá
    async with Node("alice") as a:
        assert await a.server.connect("127.0.0.1", port) is None


async def test_handler_exception_does_not_kill_connection():
    async with Node("alice") as a, Node("bob") as b:
        calls = []

        async def flaky(conn, m):
            calls.append(m["n"])
            if m["n"] == 1:
                raise RuntimeError("bug no handler")

        b.server.on_message = flaky
        conn = await a.connect_to(b)
        await conn.send(msg(1))
        await conn.send(msg(2))
        await wait_for(lambda: calls == [1, 2])


async def test_wire_log_shows_raw_json_both_ways(caplog):
    caplog.set_level(logging.DEBUG, logger="Wire")
    async with Node("alice") as a, Node("bob") as b:
        conn = await a.connect_to(b)
        await conn.send(msg(7))
        await wait_for(lambda: len(b.messages) == 1)
    wire = [r.getMessage() for r in caplog.records if r.name == "Wire"]
    assert any(l.startswith("->") and '"n":7' in l for l in wire)
    assert any(l.startswith("<-") and '"n":7' in l for l in wire)


async def test_stop_closes_everything_and_leaves_no_tasks():
    a, b = Node("alice"), Node("bob")
    await a.server.start()
    await b.server.start()
    conn = await a.connect_to(b)
    await wait_for(lambda: len(b.connected) == 1)
    await a.server.stop()
    await b.server.stop()
    assert conn.closed
    assert not a.server._tasks and not b.server._tasks


# --- 01.4: HELLO, BYE, duplicadas -------------------------------------------


async def raw_connect(node):
    return await asyncio.open_connection("127.0.0.1", node.server.port)


async def read_msg(reader, timeout=2):
    return json.loads(await asyncio.wait_for(reader.readline(), timeout))


async def test_hello_ok_repeats_msg_id_and_stores_features():
    async with Node("bob") as b:
        reader, writer = await raw_connect(b)
        hello = protocol.new_message(
            "HELLO", peer_id="alice@CIC", version="1.0", features=["hangman", "chat"]
        )
        writer.write(protocol.encode(hello))
        await writer.drain()
        ok = await read_msg(reader)
        assert ok["type"] == "HELLO_OK" and ok["msg_id"] == hello["msg_id"]
        assert ok["peer_id"] == "bob@CIC" and "hangman" in ok["features"]
        await wait_for(lambda: len(b.connected) == 1)
        conn = b.connected[0]
        assert conn.peer_id == "alice@CIC"
        assert conn.features == ["hangman", "chat"] and conn.supports_game
        writer.close()


async def test_peer_without_hangman_is_accepted_but_marked():
    async with Node("bob") as b:
        reader, writer = await raw_connect(b)
        writer.write(protocol.encode(protocol.new_message(
            "HELLO", peer_id="old@CIC", version="1.0", features=["chat"])))
        await writer.drain()
        await read_msg(reader)
        await wait_for(lambda: len(b.connected) == 1)
        assert b.connected[0].supports_game is False
        writer.close()


async def test_message_before_hello_is_dropped():
    async with Node("bob") as b:
        reader, writer = await raw_connect(b)
        writer.write(protocol.encode(msg(1)))  # antes do HELLO
        hello = protocol.new_message(
            "HELLO", peer_id="alice@CIC", version="1.0", features=["hangman"])
        writer.write(protocol.encode(hello))
        await writer.drain()
        assert (await read_msg(reader))["type"] == "HELLO_OK"
        await asyncio.sleep(0.05)
        assert b.messages == []  # a primeira mensagem nunca chegou ao roteador
        writer.close()


async def test_invalid_hello_closes_connection():
    async with Node("bob") as b:
        reader, writer = await raw_connect(b)
        bad = protocol.new_message("HELLO", peer_id="alice@CIC", version="1.0")  # sem features
        writer.write(protocol.encode(bad))
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 2) == b""
        assert b.connected == []
        writer.close()


async def test_hello_with_my_own_peer_id_is_refused():
    async with Node("bob") as b:
        reader, writer = await raw_connect(b)
        writer.write(protocol.encode(protocol.new_message(
            "HELLO", peer_id="bob@CIC", version="1.0", features=["hangman"])))
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 2) == b""
        writer.close()


async def test_connect_fills_peer_id_and_features_on_both_sides():
    async with Node("alice") as a, Node("bob") as b:
        conn = await a.connect_to(b)
        assert conn.peer_id == "bob@CIC" and conn.direction == "outbound"
        await wait_for(lambda: len(b.connected) == 1)
        assert b.connected[0].peer_id == "alice@CIC" and b.connected[0].direction == "inbound"
        assert a.connected == [conn]


async def test_ping_is_answered_with_pong_repeating_msg_id_and_timestamp():
    async with Node("bob") as b:
        reader, writer = await raw_connect(b)
        writer.write(protocol.encode(protocol.new_message(
            "HELLO", peer_id="alice@CIC", version="1.0", features=["hangman"])))
        await read_msg(reader)
        ping = protocol.new_message("PING", timestamp="2026-10-27T10:00:00.120Z")
        writer.write(protocol.encode(ping))
        await writer.drain()
        pong = await read_msg(reader)
        assert pong == {"type": "PONG", "msg_id": ping["msg_id"],
                        "timestamp": "2026-10-27T10:00:00.120Z", "ttl": 1}
        writer.close()


async def test_pong_goes_to_on_pong_hook_not_to_router():
    async with Node("alice") as a, Node("bob") as b:
        got = []
        a.server.on_pong = lambda conn, m: got.append(m["msg_id"])
        conn = await a.connect_to(b)
        await wait_for(lambda: len(b.connected) == 1)
        await b.connected[0].send(protocol.new_message("PONG", timestamp="2026-10-27T10:00:00Z"))
        await wait_for(lambda: len(got) == 1)
        assert a.messages == []


async def test_bye_gets_bye_ok_and_both_sides_close():
    async with Node("alice") as a, Node("bob") as b:
        conn = await a.connect_to(b)
        await wait_for(lambda: len(b.connected) == 1)
        started = asyncio.get_running_loop().time()
        await conn.close("shutdown")
        assert asyncio.get_running_loop().time() - started < 1.0  # BYE_OK chegou
        await wait_for(lambda: len(a.closed) == 1 and len(b.closed) == 1)
        assert a.messages == b.messages == []  # BYE/BYE_OK não sobem ao roteador


async def test_close_gives_up_after_two_seconds_without_bye_ok(monkeypatch):
    import forca.peer_connection as pc
    monkeypatch.setattr(pc, "BYE_TIMEOUT", 0.3)
    async with Node("bob") as b:
        reader, writer = await raw_connect(b)
        writer.write(protocol.encode(protocol.new_message(
            "HELLO", peer_id="alice@CIC", version="1.0", features=["hangman"])))
        await read_msg(reader)  # HELLO_OK; depois o cliente fica mudo
        await wait_for(lambda: len(b.connected) == 1)
        started = asyncio.get_running_loop().time()
        await b.connected[0].close("shutdown")
        elapsed = asyncio.get_running_loop().time() - started
        assert 0.25 < elapsed < 1.0
        assert (await read_msg(reader))["type"] == "BYE"
        writer.close()


@pytest.mark.parametrize("names", [("alice", "bob"), ("bob", "alice")])
async def test_simultaneous_connections_leave_exactly_one_per_side(names):
    async with Node(names[0]) as x, Node(names[1]) as y:
        cx, cy = await asyncio.gather(x.connect_to(y), y.connect_to(x))
        low, high = (x, y) if x.cfg.peer_id < y.cfg.peer_id else (y, x)
        # nenhuma queda anunciada: a troca de duplicada não é um peer_stale
        await asyncio.sleep(0.3)
        assert x.closed == [] and y.closed == []
        # cada lado tem UMA conexão válida com o outro...
        assert len(x.server._by_peer) == 1 and len(y.server._by_peer) == 1
        vx = x.server._by_peer[y.cfg.peer_id]
        vy = y.server._by_peer[x.cfg.peer_id]
        assert not vx.closed and not vy.closed
        # ...e é a MESMA conexão (aberta pelo menor peer_id)
        assert low.server._by_peer[high.cfg.peer_id].direction == "outbound"
        assert high.server._by_peer[low.cfg.peer_id].direction == "inbound"
        # e funciona nos dois sentidos
        assert await vx.send(msg(1)) and await vy.send(msg(2))
        await wait_for(lambda: len(x.messages) == 1 and len(y.messages) == 1)


async def test_duplicate_log_names_the_kept_direction(caplog):
    caplog.set_level(logging.INFO, logger="PeerServer")
    async with Node("alice") as a, Node("bob") as b:
        await asyncio.gather(a.connect_to(b), b.connect_to(a))
        await asyncio.sleep(0.2)
    texts = [r.getMessage() for r in caplog.records]
    assert any("Duplicate connection with" in t and "(lower peer_id)" in t for t in texts)
    assert any("Inbound connected:" in t for t in texts)
    assert any("Outbound connected:" in t for t in texts)


async def test_reconnect_from_same_direction_replaces_old_connection():
    async with Node("alice") as a, Node("bob") as b:
        first = await a.connect_to(b)
        second = await a.connect_to(b)  # alice reconectou (a primeira ficou zumbi)
        assert second is not None
        await wait_for(lambda: first.closed)
        assert b.server._by_peer["alice@CIC"] is not None


async def test_both_sides_closing_at_the_same_time_do_not_wait_for_bye_ok():
    async with Node("alice") as a, Node("bob") as b:
        ca = await a.connect_to(b)
        await wait_for(lambda: len(b.connected) == 1)
        cb = b.connected[0]
        started = asyncio.get_running_loop().time()
        await asyncio.gather(ca.close("shutdown"), cb.close("shutdown"))
        # cada um recebe o BYE do outro e a conexão fecha: sem esperar os 2 s
        assert asyncio.get_running_loop().time() - started < 1.0
