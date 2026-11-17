"""Testes da issue 01.2: PeerTable sem rede, com conexões falsas."""

import asyncio

import pytest

from forca.config import Config
from forca.models import PeerState
from forca.peer_table import EVENT_CONNECTED, EVENT_GONE, EVENT_STALE, PeerTable

CFG = Config(name="alice", namespace="CIC")


class FakeConn:
    """Imita PeerConnection: guarda o que foi enviado e se foi fechada."""

    def __init__(self, peer_id, direction="outbound", alive=True):
        self.peer_id = peer_id
        self.direction = direction
        self.alive = alive
        self.sent: list[dict] = []
        self.closed_with: str | None = None

    async def send(self, msg):
        if not self.alive:
            return False
        self.sent.append(msg)
        return True

    async def close(self, reason="shutdown"):
        self.closed_with = reason
        self.alive = False


class FakeConnector:
    """`connect_fn` falso: devolve FakeConn ou None (falha), conta as chamadas."""

    def __init__(self, fail: set[int] = frozenset()):
        self.calls: list[tuple[str, int]] = []
        self.fail = fail  # portas que "não respondem"
        self.by_port: dict[int, str] = {}

    async def __call__(self, ip, port):
        self.calls.append((ip, port))
        if port in self.fail:
            return None
        return FakeConn(self.by_port[port])


def item(name, port, namespace="CIC", ip="127.0.0.1"):
    return {"ip": ip, "port": port, "name": name, "namespace": namespace,
            "ttl": 7200, "expires_in": 7000}


async def settle(table):
    """Espera as tentativas de conexão disparadas em segundo plano."""
    await asyncio.gather(*list(table._tasks))


def recorder(table):
    events = []
    for ev in (EVENT_CONNECTED, EVENT_STALE, EVENT_GONE):
        async def cb(peer_id, ev=ev):
            events.append((ev, peer_id))
        table.subscribe(ev, cb)
    return events


# --- reconcile --------------------------------------------------------------


async def test_new_peers_become_discovered_and_connect_once_each():
    conn = FakeConnector()
    conn.by_port = {8082: "bob@CIC", 8083: "carol@CIC"}
    table = PeerTable(CFG, conn)

    await table.reconcile([item("bob", 8082), item("carol", 8083)])
    # antes da conexão terminar, já estão na tabela
    assert table.state_of("bob@CIC") in (PeerState.DISCOVERED, PeerState.CONNECTING)
    await settle(table)

    assert sorted(conn.calls) == [("127.0.0.1", 8082), ("127.0.0.1", 8083)]
    assert table.state_of("bob@CIC") == PeerState.CONNECTED
    assert {c.peer_id for c in table.connected()} == {"bob@CIC", "carol@CIC"}

    # um segundo DISCOVER igual não reconecta ninguém
    await table.reconcile([item("bob", 8082), item("carol", 8083)])
    await settle(table)
    assert len(conn.calls) == 2


async def test_own_peer_and_malformed_items_are_ignored():
    conn = FakeConnector()
    table = PeerTable(CFG, conn)
    await table.reconcile([item("alice", 8081), {"name": "x"}])
    await settle(table)
    assert conn.calls == [] and table.peers() == []


async def test_unreachable_peer_becomes_stale_without_event():
    conn = FakeConnector(fail={8082})
    table = PeerTable(CFG, conn)
    events = recorder(table)
    await table.reconcile([item("bob", 8082)])
    await settle(table)
    assert table.state_of("bob@CIC") == PeerState.STALE
    assert events == []  # nunca esteve conectado: não é "queda"


async def test_absent_peer_becomes_gone_and_is_closed_with_bye():
    conn = FakeConnector()
    conn.by_port = {8082: "bob@CIC", 8083: "carol@CIC"}
    table = PeerTable(CFG, conn)
    events = recorder(table)
    await table.reconcile([item("bob", 8082), item("carol", 8083)])
    await settle(table)
    bob_conn = next(c for c in table.connected() if c.peer_id == "bob@CIC")

    await table.reconcile([item("carol", 8083)])  # bob sumiu do Rendezvous

    assert table.state_of("bob@CIC") == PeerState.GONE
    assert bob_conn.closed_with == "gone"
    assert [c.peer_id for c in table.connected()] == ["carol@CIC"]
    assert (EVENT_GONE, "bob@CIC") in events


async def test_gone_peer_comes_back_on_next_discover():
    conn = FakeConnector()
    conn.by_port = {8082: "bob@CIC"}
    table = PeerTable(CFG, conn)
    await table.reconcile([item("bob", 8082)])
    await settle(table)
    await table.reconcile([])
    assert table.state_of("bob@CIC") == PeerState.GONE

    await table.reconcile([item("bob", 8082)])
    await settle(table)
    assert table.state_of("bob@CIC") == PeerState.CONNECTED
    assert len(conn.calls) == 2


# --- send_to / broadcast ----------------------------------------------------


async def test_send_to_absent_peer_returns_false():
    table = PeerTable(CFG, FakeConnector())
    assert await table.send_to("ninguem@CIC", {"type": "JOIN"}) is False


async def test_send_to_and_broadcast():
    table = PeerTable(CFG, FakeConnector())
    bob, carol = FakeConn("bob@CIC", "inbound"), FakeConn("carol@CIC", "inbound")
    await table.attach(bob)
    await table.attach(carol)

    assert await table.send_to("bob@CIC", {"type": "X"}) is True
    assert bob.sent == [{"type": "X"}]

    await table.broadcast(lambda pid: {"type": "GAME_LIST", "dst": pid})
    assert bob.sent[-1] == {"type": "GAME_LIST", "dst": "bob@CIC"}
    assert carol.sent[-1] == {"type": "GAME_LIST", "dst": "carol@CIC"}


async def test_broadcast_continues_after_a_failure():
    table = PeerTable(CFG, FakeConnector())
    bad, good = FakeConn("bad@CIC"), FakeConn("good@CIC")

    async def boom(msg):
        raise RuntimeError("socket morreu")

    bad.send = boom
    await table.attach(bad)
    await table.attach(good)
    await table.broadcast(lambda pid: {"type": "X"})  # não levanta
    assert good.sent == [{"type": "X"}]


# --- attach / detach e eventos ----------------------------------------------


async def test_events_reach_subscribers_with_peer_id():
    table = PeerTable(CFG, FakeConnector())
    events = recorder(table)
    bob = FakeConn("bob@CIC", "inbound")

    await table.attach(bob)  # conexão de entrada de quem ainda não foi descoberto
    await table.attach(bob)  # repetido: não emite de novo
    await table.detach(bob)
    assert events == [(EVENT_CONNECTED, "bob@CIC"), (EVENT_STALE, "bob@CIC")]
    assert table.state_of("bob@CIC") == PeerState.STALE
    assert await table.send_to("bob@CIC", {"type": "X"}) is False


async def test_closing_a_replaced_connection_is_ignored():
    table = PeerTable(CFG, FakeConnector())
    events = recorder(table)
    old, new = FakeConn("bob@CIC", "inbound"), FakeConn("bob@CIC", "outbound")
    await table.attach(old)
    await table.attach(new)
    await table.detach(old)  # a duplicada descartada fechou
    assert table.state_of("bob@CIC") == PeerState.CONNECTED
    assert (EVENT_STALE, "bob@CIC") not in events


async def test_failing_callback_does_not_stop_others():
    table = PeerTable(CFG, FakeConnector())
    seen = []

    async def bad(pid):
        raise RuntimeError("bug no handler")

    async def good(pid):
        seen.append(pid)

    table.subscribe(EVENT_CONNECTED, bad)
    table.subscribe(EVENT_CONNECTED, good)
    await table.attach(FakeConn("bob@CIC"))
    assert seen == ["bob@CIC"]


async def test_subscribe_unknown_event():
    with pytest.raises(ValueError):
        PeerTable(CFG, FakeConnector()).subscribe("peer_xyz", lambda pid: None)


# --- encerramento -----------------------------------------------------------


async def test_close_all_sends_bye_and_emits_no_stale():
    table = PeerTable(CFG, FakeConnector())
    events = recorder(table)
    bob = FakeConn("bob@CIC")
    await table.attach(bob)
    await table.close_all()
    await table.detach(bob)  # o PeerServer avisa a queda depois do BYE
    assert bob.closed_with == "shutdown"
    assert (EVENT_STALE, "bob@CIC") not in events
    assert table.connected() == []


async def test_close_all_cancels_pending_connects():
    started = asyncio.Event()

    async def slow_connect(ip, port):
        started.set()
        await asyncio.sleep(10)

    table = PeerTable(CFG, slow_connect)
    await table.reconcile([item("bob", 8082)])
    await started.wait()
    await asyncio.wait_for(table.close_all(), 1)
    assert not table._tasks
