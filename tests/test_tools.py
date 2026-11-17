"""Testes das ferramentas de apoio: Rendezvous local e utilitários do runner de cenários."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from rdv_local import LocalRendezvous  # noqa: E402
from scenarios import SCENARIOS, ordered  # noqa: E402


async def ask(port: int, req: dict) -> dict:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write((json.dumps(req) + "\n").encode())
    await writer.drain()
    resp = json.loads(await reader.readline())
    writer.close()
    return resp


@pytest.fixture
async def rdv():
    local = LocalRendezvous()
    server = await local.start(0)
    yield local, server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()


async def test_rdv_local_register_discover_unregister(rdv):
    local, port = rdv
    assert (await ask(port, {"type": "DISCOVER"}))["message"] == "peer_not_registered"
    ok = await ask(port, {"type": "REGISTER", "namespace": "CIC", "name": "alice", "port": 8081, "ttl": 60})
    assert ok == {"status": "OK", "ttl": 60, "ip": "127.0.0.1", "port": 8081}
    await ask(port, {"type": "REGISTER", "namespace": "OUTRO", "name": "bob", "port": 8082})
    peers = (await ask(port, {"type": "DISCOVER", "namespace": "CIC"}))["peers"]
    assert [(p["name"], p["port"]) for p in peers] == [("alice", 8081)]  # só o namespace pedido
    assert len((await ask(port, {"type": "DISCOVER"}))["peers"]) == 2  # sem namespace: todos
    assert await ask(port, {"type": "UNREGISTER", "namespace": "CIC", "name": "alice", "port": 8081}) == {"status": "OK"}
    assert ("CIC", "alice") not in local.registered


async def test_rdv_local_errors_follow_the_spec(rdv):
    _, port = rdv
    assert (await ask(port, {"type": "REGISTER", "namespace": "CIC", "name": "x", "port": 0}))["message"] == "bad_port"
    assert (await ask(port, {"type": "UNREGISTER"}))["message"] == "namespace_required"
    assert (await ask(port, {"type": "XYZ"}))["message"] == "Unknown command"


def test_ordered_requires_increasing_line_order():
    text = "a1\nb\nxx\nc\nb2"
    assert ordered(text, ["a", "b", "c"]) == (True, [0, 1, 3])
    assert ordered(text, ["c", "a"])[0] is False  # fora de ordem
    assert ordered(text, ["a", "zzz"])[0] is False  # ausente


def test_scenario_ids_are_unique_and_cover_1_to_10():
    ids = [sid for sid, _, _ in SCENARIOS]
    assert len(ids) == len(set(ids))
    assert {i.rstrip("abcd") for i in ids} == {str(n) for n in range(1, 11)}
