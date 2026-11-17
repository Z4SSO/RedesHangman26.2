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
