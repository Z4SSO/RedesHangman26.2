"""Testes da issue 01.1 contra um Rendezvous FALSO em 127.0.0.1 (porta 0).

O servidor falso imita o real: lê UMA linha por conexão, responde UMA linha e
fecha. Ele guarda cada linha recebida para conferirmos o JSON enviado.
"""

import asyncio
import json
import logging
from dataclasses import replace

import pytest

from forca.config import Config
from forca.rendezvous_connection import RendezvousConnection, RendezvousError

BLOCK_MSG = (
    "Connection from 127.0.0.1:40046 has been blocked due to excessive login "
    "attempts (limit: 50). The block will be lifted in 59 seconds."
)


class FakeRendezvous:
    """`respond(request: dict) -> dict | None`. None = não responde (timeout)."""

    def __init__(self, respond):
        self.respond = respond
        self.lines: list[bytes] = []  # linha bruta recebida em cada conexão
        self.server = None
        self.port = 0

    async def _handle(self, reader, writer):
        line = await reader.readline()
        self.lines.append(line)
        resp = self.respond(json.loads(line))
        if resp is None:
            await asyncio.sleep(10)  # fica mudo; o cliente deve desistir antes
        else:
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()
        writer.close()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()

    def client(self, timeout: float = 1.0, **cfg) -> RendezvousConnection:
        base = Config(rdv_host="127.0.0.1", rdv_port=self.port, name="alice",
                      namespace="CIC", listen_port=8081, register_ttl=7200)
        return RendezvousConnection(replace(base, **cfg), timeout=timeout)

    def requests(self) -> list[dict]:
        return [json.loads(line) for line in self.lines]


def ok_register(req):
    return {"status": "OK", "ttl": req["ttl"], "ip": "45.171.103.246", "port": req["port"]}


# --- REGISTER ---------------------------------------------------------------


async def test_register_sends_spec_json_and_stores_public_ip(caplog):
    caplog.set_level(logging.INFO, logger="RDV")
    async with FakeRendezvous(ok_register) as srv:
        rdv = srv.client()
        resp = await rdv.register()

    assert srv.requests() == [
        {"type": "REGISTER", "namespace": "CIC", "name": "alice", "port": 8081, "ttl": 7200}
    ]
    assert srv.lines[0].endswith(b"\n") and srv.lines[0].count(b"\n") == 1
    assert resp["status"] == "OK"
    assert rdv.public_ip == "45.171.103.246"
    assert "registered alice@CIC as 45.171.103.246:8081 (ttl=7200)" in caplog.text


async def test_register_bad_port_raises_with_server_message():
    async with FakeRendezvous(lambda r: {"status": "ERROR", "message": "bad_port"}) as srv:
        with pytest.raises(RendezvousError) as exc:
            await srv.client().register()
    assert exc.value.message == "bad_port"


async def test_rate_limit_block_message_is_kept():
    async with FakeRendezvous(lambda r: {"status": "ERROR", "message": BLOCK_MSG}) as srv:
        with pytest.raises(RendezvousError) as exc:
            await srv.client().register()
    assert exc.value.message == BLOCK_MSG


# --- DISCOVER ---------------------------------------------------------------


async def test_discover_filters_own_peer():
    peers = [
        {"ip": "1.1.1.1", "port": 8081, "name": "alice", "namespace": "CIC", "ttl": 7200, "expires_in": 7100},
        {"ip": "2.2.2.2", "port": 8082, "name": "bob", "namespace": "CIC", "ttl": 7200, "expires_in": 5908},
        # mesmo nome em outro namespace NÃO é o próprio peer
        {"ip": "3.3.3.3", "port": 8083, "name": "alice", "namespace": "OUTRO", "ttl": 60, "expires_in": 30},
    ]
    async with FakeRendezvous(lambda r: {"status": "OK", "peers": peers}) as srv:
        result = await srv.client().discover()

    assert srv.requests() == [{"type": "DISCOVER", "namespace": "CIC"}]
    assert [(p["name"], p["namespace"]) for p in result] == [("bob", "CIC"), ("alice", "OUTRO")]


async def test_discover_other_namespace():
    async with FakeRendezvous(lambda r: {"status": "OK", "peers": []}) as srv:
        assert await srv.client().discover("FORCA") == []
    assert srv.requests() == [{"type": "DISCOVER", "namespace": "FORCA"}]


async def test_discover_peer_not_registered():
    async with FakeRendezvous(lambda r: {"status": "ERROR", "message": "peer_not_registered"}) as srv:
        with pytest.raises(RendezvousError) as exc:
            await srv.client().discover()
    assert exc.value.message == "peer_not_registered"


# --- UNREGISTER -------------------------------------------------------------


async def test_unregister_sends_namespace_name_port():
    async with FakeRendezvous(lambda r: {"status": "OK"}) as srv:
        assert await srv.client().unregister() is None
    assert srv.requests() == [
        {"type": "UNREGISTER", "namespace": "CIC", "name": "alice", "port": 8081}
    ]


# --- transporte -------------------------------------------------------------


async def test_one_new_connection_per_command():
    def respond(req):
        if req["type"] == "REGISTER":
            return ok_register(req)
        if req["type"] == "DISCOVER":
            return {"status": "OK", "peers": []}
        return {"status": "OK"}

    async with FakeRendezvous(respond) as srv:
        rdv = srv.client()
        await rdv.register()
        await rdv.discover()
        await rdv.unregister()

    # cada conexão recebeu exatamente uma linha, com um comando
    assert [r["type"] for r in srv.requests()] == ["REGISTER", "DISCOVER", "UNREGISTER"]


async def test_timeout_when_server_is_silent():
    async with FakeRendezvous(lambda r: None) as srv:
        with pytest.raises(RendezvousError) as exc:
            await asyncio.wait_for(srv.client(timeout=0.2).discover(), 2)
    assert exc.value.message == "timeout"


async def test_connection_refused():
    # porta que acabou de ser liberada: ninguém escutando
    async with FakeRendezvous(lambda r: None) as srv:
        port = srv.port
    rdv = RendezvousConnection(Config(rdv_host="127.0.0.1", rdv_port=port), timeout=0.5)
    with pytest.raises(RendezvousError) as exc:
        await rdv.register()
    assert exc.value.message == "connection_failed"


async def test_garbage_response_is_bad_response():
    async def handle(reader, writer):
        await reader.readline()
        writer.write(b"isto nao e json\n")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    rdv = RendezvousConnection(Config(rdv_host="127.0.0.1", rdv_port=port), timeout=1)
    with pytest.raises(RendezvousError) as exc:
        await rdv.discover()
    server.close()
    assert exc.value.message == "bad_response"
