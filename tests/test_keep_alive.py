"""Testes da issue 01.5: KeepAlive (PING, RTT, STALE)."""

import asyncio
import json
import logging
import re
from dataclasses import replace

from forca import protocol
from forca.config import Config
from forca.keep_alive import KeepAlive
from forca.models import PeerState
from forca.peer_connection import PeerServer

INTERVAL = 0.05


class FakeConn:
    """Imita PeerConnection: guarda os PINGs enviados."""

    def __init__(self, peer_id="bob@CIC"):
        self.peer_id = peer_id
        self.label = peer_id
        self.closed = False
        self.state = PeerState.CONNECTED
        self.rtt_ms = None
        self.missed_pings = 0
        self.sent: list[dict] = []
        self.close_reason: str | None = None

    async def send(self, msg):
        if self.closed:
            return False
        self.sent.append(msg)
        return True

    async def close(self, reason="shutdown", wait_ack=True):
        self.close_reason = reason
        self.wait_ack = wait_ack
        self.closed = True


def make_ka(**cfg):
    return KeepAlive(replace(Config(), ping_interval=INTERVAL, ping_miss_limit=3, **cfg))


def pong_for(ping):
    return protocol.new_message("PONG", msg_id=ping["msg_id"], timestamp=ping["timestamp"])


async def wait_for(cond, timeout=2.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("condição não ficou verdadeira a tempo")
        await asyncio.sleep(0.01)


# --- com conexão falsa -------------------------------------------------------


async def test_first_ping_is_sent_immediately_with_millisecond_timestamp():
    ka, conn = make_ka(), FakeConn()
    ka.watch(conn)
    await wait_for(lambda: len(conn.sent) == 1)
    ping = conn.sent[0]
    assert ping["type"] == "PING" and ping["ttl"] == 1
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", ping["timestamp"])
    assert "src" not in ping and "dst" not in ping  # PING é mensagem de conexão
    await ka.stop()


async def test_pings_keep_going_every_interval():
    ka, conn = make_ka(), FakeConn()
    ka.watch(conn)
    await wait_for(lambda: len(conn.sent) >= 2)
    assert len({m["msg_id"] for m in conn.sent}) == len(conn.sent)  # msg_id novo a cada PING
    await ka.stop()


async def test_watch_twice_creates_one_task():
    ka, conn = make_ka(), FakeConn()
    ka.watch(conn)
    ka.watch(conn)
    assert len(ka._watches) == 1
    await ka.stop()


async def test_pong_sets_rtt_and_resets_missed(caplog):
    caplog.set_level(logging.DEBUG, logger="KeepAlive")
    ka, conn = make_ka(), FakeConn()
    ka.watch(conn)
    await wait_for(lambda: len(conn.sent) == 1)
    conn.missed_pings = 2
    ka.on_pong(conn, pong_for(conn.sent[0]))
    assert conn.rtt_ms is not None and conn.rtt_ms >= 0
    assert conn.missed_pings == 0
    assert re.search(r"bob@CIC RTT=\d+\.\d ms \(avg \d+\.\d ms\)", caplog.text)
    await ka.stop()


async def test_rtt_is_moving_average_of_last_10():
    ka, conn = make_ka(), FakeConn()
    ka.watch(conn)
    await wait_for(lambda: len(conn.sent) == 1)
    w = ka._watches[conn]
    loop = asyncio.get_running_loop()
    # 12 amostras de 10, 20, ..., 120 ms: só valem as 10 últimas (30..120)
    for i in range(1, 13):
        mid = f"fake-{i}"
        w.pending[mid] = loop.time() - i * 0.010
        ka.on_pong(conn, protocol.new_message("PONG", msg_id=mid, timestamp="x"))
    expected = sum(range(30, 130, 10)) / 10  # 75 ms
    assert abs(conn.rtt_ms - expected) < 3
    assert len(w.samples) == 10
    await ka.stop()


async def test_unknown_pong_is_ignored():
    ka, conn = make_ka(), FakeConn()
    ka.watch(conn)
    await wait_for(lambda: len(conn.sent) == 1)
    ka.on_pong(conn, protocol.new_message("PONG", msg_id="desconhecido", timestamp="x"))
    assert conn.rtt_ms is None
    await ka.stop()


async def test_silent_peer_is_marked_stale_after_exactly_three_intervals(caplog):
    caplog.set_level(logging.WARNING, logger="KeepAlive")
    ka, conn = make_ka(), FakeConn("carol@CIC")
    started = asyncio.get_running_loop().time()
    ka.watch(conn)
    await wait_for(lambda: conn.closed)
    elapsed = asyncio.get_running_loop().time() - started
    assert conn.close_reason == "idle" and conn.wait_ack is False
    assert conn.state == PeerState.STALE and conn.missed_pings == 3
    assert len(conn.sent) == 3  # 3 PINGs, nenhum a mais
    assert 3 * INTERVAL * 0.9 < elapsed < 3 * INTERVAL + 0.5
    assert "carol@CIC missed 3 PINGs — marking STALE" in caplog.text
    await ka.stop()


async def test_a_pong_in_the_middle_restarts_the_count():
    ka, conn = make_ka(), FakeConn()
    ka.watch(conn)
    await wait_for(lambda: len(conn.sent) == 3)  # 2 sem resposta até aqui
    assert conn.missed_pings == 2 and not conn.closed
    ka.on_pong(conn, pong_for(conn.sent[-1]))  # o par acordou
    assert conn.missed_pings == 0
    await asyncio.sleep(INTERVAL * 1.5)
    assert not conn.closed  # recomeçou a contar do zero
    await ka.stop()


async def test_loop_ends_by_itself_when_connection_closes():
    ka, conn = make_ka(), FakeConn()
    ka.watch(conn)
    await wait_for(lambda: len(conn.sent) == 1)
    task = ka._watches[conn].task
    conn.closed = True
    await asyncio.wait_for(task, 1)
    assert conn not in ka._watches


async def test_unwatch_and_stop_leave_no_tasks():
    ka, a, b = make_ka(), FakeConn("a@CIC"), FakeConn("b@CIC")
    ka.watch(a)
    ka.watch(b)
    tasks = [w.task for w in ka._watches.values()]
    ka.unwatch(a)
    await ka.stop()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert all(t.done() for t in tasks) and not ka._watches


# --- com PeerServer de verdade ----------------------------------------------


class Node:
    def __init__(self, name):
        self.cfg = replace(Config(name=name, namespace="CIC", listen_port=0),
                           ping_interval=INTERVAL, ping_miss_limit=3)
        self.ka = KeepAlive(self.cfg)
        self.closed = []
        self.conns = []
        self.server = PeerServer(self.cfg, self._msg, self._closed, self._connected)
        self.server.on_pong = self.ka.on_pong

    async def _msg(self, conn, msg):
        pass

    async def _connected(self, conn):
        self.conns.append(conn)
        self.ka.watch(conn)

    async def _closed(self, conn):
        self.closed.append(conn)

    async def __aenter__(self):
        await self.server.start()
        return self

    async def __aexit__(self, *exc):
        await self.ka.stop()
        await self.server.stop()


async def test_two_real_peers_measure_rtt_and_stay_connected():
    async with Node("alice") as a, Node("bob") as b:
        ca = await a.server.connect("127.0.0.1", b.server.port)
        await wait_for(lambda: ca.rtt_ms is not None and b.conns and b.conns[0].rtt_ms is not None)
        assert ca.rtt_ms < 100 and b.conns[0].rtt_ms < 100  # em 127.0.0.1 é rápido
        await asyncio.sleep(INTERVAL * 6)  # passam vários intervalos
        assert not ca.closed and ca.missed_pings == 0  # PONGs chegando: nada de STALE
        assert a.closed == [] and b.closed == []


async def test_peer_that_ignores_pings_gets_closed_and_reported_once():
    async with Node("alice") as a:
        reader, writer = await asyncio.open_connection("127.0.0.1", a.server.port)
        hello = protocol.new_message(
            "HELLO", peer_id="mudo@CIC", version="1.0", features=["hangman"])
        writer.write(protocol.encode(hello))
        await writer.drain()
        assert json.loads(await reader.readline())["type"] == "HELLO_OK"
        # a partir daqui o cliente lê (para o TCP não travar) mas nunca responde
        started = asyncio.get_running_loop().time()
        await wait_for(lambda: len(a.closed) == 1, timeout=3)
        assert asyncio.get_running_loop().time() - started < 1.0  # sem esperar o BYE_OK
        await asyncio.sleep(0.2)
        assert len(a.closed) == 1  # peer_stale uma única vez por queda
        assert a.conns[0].state == PeerState.STALE
        writer.close()
