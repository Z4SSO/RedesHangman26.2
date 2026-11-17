import asyncio
import io
import logging
from types import SimpleNamespace

import pytest

from forca.cli import HELP, CLI
from forca.config import Config
from forca.models import PeerState
from forca.rendezvous_connection import RendezvousError


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def conn(peer_id, direction="outbound", rtt=None):
    return SimpleNamespace(peer_id=peer_id, direction=direction, state=PeerState.CONNECTED, rtt_ms=rtt)


class FakeRdv:
    def __init__(self, peers=(), error=None):
        self.peers, self.error, self.calls = list(peers), error, []

    async def discover(self, namespace=None):
        self.calls.append(namespace)
        if self.error:
            raise self.error
        return self.peers


class FakeClient:
    def __init__(self, conns=(), peers=()):
        self.cfg = Config(name="alice", namespace="CIC")
        self.rdv = FakeRdv(peers)
        self.table = SimpleNamespace(connected=lambda: list(conns))
        self.reconciled = 0
        self.reconcile_error = None

    async def reconcile_now(self):
        if self.reconcile_error:
            raise self.reconcile_error
        self.reconciled += 1


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def levels():
    return []


def make_cli(client=None, levels=None, clock=None, **kw):
    client = client or FakeClient()
    set_level = (lambda name: levels.append(name)) if levels is not None else None
    return CLI(client, set_level, stdin=None, clock=clock or Clock(), **kw)


def lines(caplog, logger="CLI"):
    return [r.getMessage() for r in caplog.records if r.name == logger]


@pytest.fixture(autouse=True)
def cli_logs(caplog):
    caplog.set_level(logging.DEBUG, logger="CLI")


# --- parser ---


async def test_unknown_command_warns_and_the_program_goes_on(caplog):
    cli = make_cli()
    await cli.execute("/foo")
    await cli.execute("sem barra")
    await cli.execute("   ")
    out = lines(caplog)
    assert any("Comando desconhecido: /foo" in m for m in out)
    assert any("começam com '/'" in m for m in out)


async def test_commands_are_case_insensitive_and_extra_spaces_are_ignored(caplog):
    cli = make_cli(FakeClient(conns=[conn("bob@CIC")]))
    await cli.execute("  /CONN   ")
    assert any("bob@CIC" in m for m in lines(caplog))


async def test_help_lists_the_17_commands_of_the_spec(caplog):
    await make_cli().execute("/help")
    shown = [m for m in lines(caplog) if m.startswith("  /")]
    assert len(HELP) == 17 and len(shown) == 17
    for usage, _ in HELP:
        assert any(m.strip().startswith(usage) for m in shown), usage


# --- /log ---


async def test_log_calls_the_injected_function(levels, caplog):
    cli = make_cli(levels=levels)
    await cli.execute("/log debug")
    assert levels == ["debug"] and any("DEBUG" in m for m in lines(caplog))


async def test_log_with_wrong_arguments_or_level_only_warns(caplog):
    def reject(name):
        raise ValueError(f"nível inválido {name!r}")

    cli = CLI(FakeClient(), reject, stdin=None)
    await cli.execute("/log")
    await cli.execute("/log LOUD")
    out = lines(caplog)
    assert any("uso: /log" in m for m in out) and any("nível inválido" in m for m in out)


# --- /conn, /rtt, /reconnect ---


async def test_conn_shows_one_line_per_neighbor(caplog):
    cli = make_cli(FakeClient(conns=[conn("carol@CIC", "inbound", 41.74), conn("bob@CIC")]))
    await cli.execute("/conn")
    out = lines(caplog)
    assert out[0].startswith("Conexões ativas (2)")
    assert "bob@CIC" in out[1] and "outbound" in out[1] and "CONNECTED" in out[1] and "RTT -" in out[1]
    assert "carol@CIC" in out[2] and "inbound" in out[2] and "41.7 ms" in out[2]


async def test_rtt_and_empty_table(caplog):
    await make_cli(FakeClient(conns=[conn("bob@CIC", rtt=12.34)])).execute("/rtt")
    assert any("bob@CIC" in m and "12.3 ms" in m for m in lines(caplog))
    caplog.clear()
    await make_cli().execute("/rtt")
    assert any("Nenhum peer conectado" in m for m in lines(caplog))


async def test_reconnect_forces_a_reconciliation():
    client = FakeClient()
    await make_cli(client).execute("/reconnect")
    assert client.reconciled == 1


# --- /peers ---


async def test_peers_default_all_and_namespace_forms(clock, caplog):
    client = FakeClient(conns=[conn("bob@CIC")], peers=[
        {"name": "bob", "namespace": "CIC", "ip": "10.0.0.2", "port": 8082},
        {"name": "dave", "namespace": "CIC", "ip": "10.0.0.4", "port": 8084}])
    cli = make_cli(client, clock=clock)
    for command, expected in (("/peers", "CIC"), ("/peers *", None), ("/peers #FORCA", "FORCA")):
        await cli.execute(command)
        clock.t += 6
        assert client.rdv.calls[-1] == expected
    out = lines(caplog)
    assert any("bob@CIC" in m and "conectado" in m for m in out)
    assert any("dave@CIC" in m and m.rstrip().endswith("-") for m in out)


async def test_peers_respects_the_rendezvous_rate_limit(clock, caplog):
    client = FakeClient()
    cli = make_cli(client, clock=clock)
    await cli.execute("/peers")
    await cli.execute("/peers")  # logo em seguida: recusado
    assert len(client.rdv.calls) == 1 and any("aguarde" in m for m in lines(caplog))
    clock.t += 5.5
    await cli.execute("/peers")
    assert len(client.rdv.calls) == 2


async def test_peers_bad_arguments_and_rendezvous_error_do_not_crash(clock, caplog):
    client = FakeClient()
    cli = make_cli(client, clock=clock)
    await cli.execute("/peers foo")
    await cli.execute("/peers # extra")
    assert not client.rdv.calls and sum("uso: /peers" in m for m in lines(caplog)) == 2
    client.rdv.error = RendezvousError("peer_not_registered")
    await cli.execute("/peers")
    assert any("peer_not_registered" in m for m in lines(caplog))


async def test_a_failing_command_is_logged_and_the_next_one_runs(caplog):
    client = FakeClient(conns=[conn("bob@CIC")])
    client.reconcile_error = RuntimeError("boom")
    cli = make_cli(client)
    await cli.execute("/reconnect")
    await cli.execute("/conn")
    assert "boom" in caplog.text and any("bob@CIC" in m for m in lines(caplog))


# --- laço e teclado ---


async def test_run_executes_lines_until_quit_and_survives_unknown_commands(caplog):
    cli = make_cli(FakeClient(conns=[conn("bob@CIC")]))
    for line in ("/foo", "/conn", "/quit", "/conn"):
        cli.feed(line)
    await asyncio.wait_for(cli.run(), 2)
    out = lines(caplog)
    assert sum("bob@CIC" in m for m in out) == 1  # o /conn depois do /quit não roda
    assert any("Encerrando" in m for m in out)


async def test_request_quit_ends_the_loop_like_quit():
    cli = make_cli()
    task = asyncio.create_task(cli.run())
    await asyncio.sleep(0.01)
    cli.request_quit()  # o que Ctrl+C / SIGTERM chamam
    await asyncio.wait_for(task, 2)


async def test_waiting_for_the_keyboard_does_not_block_the_event_loop():
    cli = make_cli()
    task = asyncio.create_task(cli.run())  # fila vazia: o laço espera uma linha
    ticks = 0
    for _ in range(20):  # outras tarefas (PING/PONG) continuam rodando
        await asyncio.sleep(0.001)
        ticks += 1
    assert ticks == 20 and not task.done()
    cli.request_quit()
    await asyncio.wait_for(task, 2)


async def test_stdin_thread_feeds_lines_and_eof_means_quit(caplog):
    cli = CLI(FakeClient(conns=[conn("bob@CIC")]), None, stdin=io.StringIO("/conn\n/rtt\n"))
    await asyncio.wait_for(cli.run(), 2)  # sem /quit: o EOF encerra
    out = lines(caplog)
    assert any("Conexões ativas" in m for m in out) and any("RTT médio" in m for m in out)


# --- revisão: /reconnect e /peers dividem o limite do Rendezvous; Ctrl+C com comando lento ---


async def test_reconnect_and_peers_share_the_rendezvous_gap(clock, caplog):
    client = FakeClient()
    cli = make_cli(client, clock=clock)
    await cli.execute("/reconnect")
    await cli.execute("/reconnect")  # colar o comando várias vezes não passa de 50 req/min
    await cli.execute("/peers")
    assert client.reconciled == 1 and not client.rdv.calls
    assert sum("aguarde" in m for m in lines(caplog)) == 2
    clock.t += 5.5
    await cli.execute("/peers")
    assert len(client.rdv.calls) == 1


async def test_ctrl_c_interrupts_a_slow_command():
    client = FakeClient()

    async def hang(namespace=None):
        await asyncio.sleep(30)

    client.rdv.discover = hang
    cli = make_cli(client)
    cli.feed("/peers")
    task = asyncio.create_task(cli.run())
    await asyncio.sleep(0.05)  # o /peers está pendurado no Rendezvous
    started = asyncio.get_running_loop().time()
    cli.request_quit()  # o que Ctrl+C / SIGTERM chamam
    await asyncio.wait_for(task, 2)
    assert asyncio.get_running_loop().time() - started < 1


async def test_leave_tells_the_host_to_use_cancel(caplog):
    client = FakeClient()
    client.host = SimpleNamespace(active=True)
    client.player = SimpleNamespace(active=False)
    await make_cli(client).execute("/leave")
    assert any("/cancel" in m for m in lines(caplog))


def test_help_is_the_only_command_list():
    from forca import cli

    assert not hasattr(cli, "COMMANDS") and len(cli.HELP) == 17
