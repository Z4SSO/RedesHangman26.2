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


async def test_replacing_connection_of_connected_peer_emits_no_event():
    table = PeerTable(CFG, FakeConnector())
    events = recorder(table)
    old, new = FakeConn("bob@CIC", "outbound"), FakeConn("bob@CIC", "inbound")
    await table.attach(old)
    await table.attach(new)  # desempate de duplicada: troca silenciosa
    assert events == [(EVENT_CONNECTED, "bob@CIC")]  # um só, da primeira
    assert table.connected() == [new]


# --- 01.6: reconexão com backoff --------------------------------------------

from dataclasses import replace as _replace  # noqa: E402

from forca.peer_table import backoff_delay  # noqa: E402

FAST = _replace(CFG, base_backoff=0.02, max_backoff=0.08, max_reconnect_attempts=5)


async def until(cond, timeout=3.0):
    """Espera `cond()` ficar verdadeira (sem sleep fixo longo)."""
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("condição não ficou verdadeira a tempo")
        await asyncio.sleep(0.005)


def test_backoff_delay_follows_spec_with_default_values():
    d = Config()  # base_backoff=2, max_backoff=60
    assert [backoff_delay(n, d.base_backoff, d.max_backoff) for n in range(7)] == [
        2, 4, 8, 16, 32, 60, 60
    ]


async def test_gives_up_after_max_attempts_and_becomes_gone():
    conn = FakeConnector(fail={8082})
    table = PeerTable(FAST, conn)
    events = recorder(table)
    await table.reconcile([item("bob", 8082)])
    await until(lambda: table.state_of("bob@CIC") == PeerState.GONE)

    assert len(conn.calls) == 1 + 5  # a conexão inicial + 5 reconexões, nem uma a mais
    assert events == [(EVENT_GONE, "bob@CIC")]
    entry = table.peers()[0]
    assert entry.retry_task is None and entry.attempts == 5
    await asyncio.sleep(0.2)
    assert len(conn.calls) == 6  # GONE não tenta mais


async def test_waits_double_until_the_cap():
    conn = FakeConnector(fail={8082})
    table = PeerTable(FAST, conn)
    delays = []
    original = table._schedule_retry

    async def spy(entry):
        before = entry.retry_task
        await original(entry)
        if entry.retry_task is not None and entry.retry_task is not before:
            delays.append(entry.next_retry - asyncio.get_running_loop().time())

    table._schedule_retry = spy
    await table.reconcile([item("bob", 8082)])
    await until(lambda: table.state_of("bob@CIC") == PeerState.GONE)
    expected = [0.02, 0.04, 0.08, 0.08, 0.08]  # base × 2^n, limitado a max_backoff
    assert len(delays) == 5
    assert all(abs(d - e) < 0.015 for d, e in zip(delays, expected)), delays


async def test_discover_brings_gone_peer_back_and_resets_attempts():
    conn = FakeConnector(fail={8082})
    conn.by_port = {8082: "bob@CIC"}
    table = PeerTable(FAST, conn)
    await table.reconcile([item("bob", 8082)])
    await until(lambda: table.state_of("bob@CIC") == PeerState.GONE)

    conn.fail.clear()  # o peer voltou a responder
    await table.reconcile([item("bob", 8082)])
    await until(lambda: table.state_of("bob@CIC") == PeerState.CONNECTED)
    assert table.peers()[0].attempts == 0


async def test_successful_reconnect_resets_attempts():
    conn = FakeConnector(fail={8082})
    conn.by_port = {8082: "bob@CIC"}
    table = PeerTable(FAST, conn)
    await table.reconcile([item("bob", 8082)])
    await until(lambda: len(conn.calls) >= 3)  # falhou 3 vezes
    assert table.peers()[0].attempts >= 2
    conn.fail.clear()
    await until(lambda: table.state_of("bob@CIC") == PeerState.CONNECTED)
    entry = table.peers()[0]
    assert entry.attempts == 0 and entry.retry_task is None and entry.next_retry is None


async def test_lost_connection_is_retried_and_events_follow():
    conn = FakeConnector()
    conn.by_port = {8082: "bob@CIC"}
    table = PeerTable(FAST, conn)
    events = recorder(table)
    await table.reconcile([item("bob", 8082)])
    await until(lambda: table.state_of("bob@CIC") == PeerState.CONNECTED)
    first = table.connected()[0]

    await table.detach(first)  # a conexão caiu
    assert table.state_of("bob@CIC") == PeerState.STALE
    await until(lambda: table.state_of("bob@CIC") == PeerState.CONNECTED)
    assert table.connected()[0] is not first
    assert events == [(EVENT_CONNECTED, "bob@CIC"), (EVENT_STALE, "bob@CIC"),
                      (EVENT_CONNECTED, "bob@CIC")]


async def test_inbound_connection_cancels_pending_retry():
    conn = FakeConnector(fail={8082})
    table = PeerTable(CFG, conn)  # backoff padrão (2 s): a espera fica pendente
    await table.reconcile([item("bob", 8082)])
    await until(lambda: table.peers() and table.peers()[0].retry_task is not None)

    await table.attach(FakeConn("bob@CIC", "inbound"))  # o bob conectou em nós
    entry = table.peers()[0]
    assert entry.state == PeerState.CONNECTED
    assert entry.retry_task is None and entry.attempts == 0
    await asyncio.sleep(0.05)
    assert len(conn.calls) == 1  # nenhuma reconexão depois disso
    await table.close_all()


async def test_peer_absent_from_discover_cancels_retry():
    conn = FakeConnector(fail={8082})
    table = PeerTable(CFG, conn)
    await table.reconcile([item("bob", 8082)])
    await until(lambda: table.peers() and table.peers()[0].retry_task is not None)
    await table.reconcile([])
    entry = table.peers()[0]
    assert entry.state == PeerState.GONE and entry.retry_task is None
    await table.close_all()


async def test_close_all_cancels_pending_retries():
    conn = FakeConnector(fail={8082})
    table = PeerTable(CFG, conn)
    await table.reconcile([item("bob", 8082)])
    await until(lambda: table.peers() and table.peers()[0].retry_task is not None)
    await asyncio.wait_for(table.close_all(), 1)
    assert not table._tasks


async def test_retry_now_tries_immediately_and_restarts_count():
    conn = FakeConnector(fail={8082})
    conn.by_port = {8082: "bob@CIC"}
    table = PeerTable(CFG, conn)  # backoff padrão: sem retry_now esperaria 2 s
    await table.reconcile([item("bob", 8082)])
    await until(lambda: table.peers() and table.peers()[0].retry_task is not None)
    assert table.peers()[0].attempts == 1

    conn.fail.clear()
    table.retry_now()
    await until(lambda: table.state_of("bob@CIC") == PeerState.CONNECTED, timeout=1.0)
    assert len(conn.calls) == 2 and table.peers()[0].attempts == 0
    await table.close_all()


async def test_peer_in_backoff_does_not_delay_the_others():
    conn = FakeConnector(fail={8082})
    conn.by_port = {8082: "bob@CIC", 8083: "carol@CIC"}
    table = PeerTable(CFG, conn)  # bob espera 2 s; carol não pode esperar junto
    started = asyncio.get_running_loop().time()
    await table.reconcile([item("bob", 8082), item("carol", 8083)])
    await until(lambda: table.state_of("carol@CIC") == PeerState.CONNECTED, timeout=1.0)
    assert asyncio.get_running_loop().time() - started < 0.5
    await table.close_all()


async def test_stale_peer_without_address_is_tried_when_discover_brings_it():
    conn = FakeConnector()
    conn.by_port = {8082: "bob@CIC"}
    table = PeerTable(FAST, conn)
    bob_in = FakeConn("bob@CIC", "inbound")
    await table.attach(bob_in)  # só conhecemos o bob por uma conexão de entrada
    await table.detach(bob_in)  # caiu: sem ip/porta não há como reconectar
    assert table.state_of("bob@CIC") == PeerState.STALE and conn.calls == []

    await table.reconcile([item("bob", 8082)])  # o DISCOVER traz o endereço
    await until(lambda: table.state_of("bob@CIC") == PeerState.CONNECTED)


async def test_absent_peers_are_closed_in_parallel():
    """Cada fechamento espera o BYE_OK (até 2 s): vários ausentes não somam o tempo."""
    class SlowConn(FakeConn):
        async def close(self, reason="shutdown"):
            await asyncio.sleep(0.3)
            await super().close(reason)

    conn = FakeConnector()
    conn.by_port = {8082: "bob@CIC", 8083: "carol@CIC", 8084: "dave@CIC"}
    table = PeerTable(CFG, conn)
    for pid in ("bob@CIC", "carol@CIC", "dave@CIC"):
        await table.attach(SlowConn(pid))
    started = asyncio.get_running_loop().time()
    await table.reconcile([])  # os três sumiram do Rendezvous
    assert asyncio.get_running_loop().time() - started < 0.7  # ~0,3 s, não 0,9 s
    assert all(table.state_of(p) == PeerState.GONE for p in ("bob@CIC", "carol@CIC", "dave@CIC"))
