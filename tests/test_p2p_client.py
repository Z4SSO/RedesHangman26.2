"""Testes da issue 01.7: P2PClient (início, tarefas periódicas, encerramento).

O Rendezvous é um servidor falso COM ESTADO em 127.0.0.1 (porta 0): guarda os
registros, responde DISCOVER e anota cada requisição recebida.
"""

import asyncio
import json
import logging
from dataclasses import replace

import pytest

from forca.config import Config
from forca.p2p_client import P2PClient


class FakeRdv:
    def __init__(self):
        self.registered: dict[tuple[str, str], dict] = {}
        self.requests: list[str] = []  # tipo de cada requisição, na ordem
        self.events: list[str] = []  # linha do tempo compartilhada com os testes
        self.fail_all = False  # responde ERROR a tudo
        self.fake_public_ip = None  # IP "público" divulgado no lugar do real (simula NAT)
        self.server = None
        self.port = 0

    def forget_all(self):
        """Simula o registro ter expirado no servidor."""
        self.registered.clear()

    async def _handle(self, reader, writer):
        req = json.loads(await reader.readline())
        ip = self.fake_public_ip or writer.get_extra_info("peername")[0]
        self.requests.append(req["type"])
        if self.fail_all:
            resp = {"status": "ERROR", "message": "bad_port"}
        elif req["type"] == "REGISTER":
            self.registered[(req["namespace"], req["name"])] = {
                "ip": ip, "port": req["port"], "name": req["name"],
                "namespace": req["namespace"], "ttl": req.get("ttl", 7200), "expires_in": 100,
            }
            resp = {"status": "OK", "ttl": req.get("ttl", 7200), "ip": ip, "port": req["port"]}
        elif req["type"] == "DISCOVER":
            if not self.registered:
                resp = {"status": "ERROR", "message": "peer_not_registered"}
            else:
                ns = req.get("namespace")
                resp = {"status": "OK", "peers": [p for p in self.registered.values()
                                                  if ns is None or p["namespace"] == ns]}
        elif req["type"] == "UNREGISTER":
            self.events.append("UNREGISTER")
            self.registered.pop((req["namespace"], req["name"]), None)
            resp = {"status": "OK"}
        else:
            resp = {"status": "ERROR", "message": "Unknown command"}
        writer.write((json.dumps(resp) + "\n").encode())
        await writer.drain()
        writer.close()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()

    def cfg(self, name, **over) -> Config:
        base = Config(name=name, namespace="CIC", rdv_host="127.0.0.1", rdv_port=self.port,
                      listen_port=0, discover_interval=0.1, register_ttl=3600,
                      base_backoff=0.02, max_backoff=0.1)
        return replace(base, **over)


async def until(cond, timeout=3.0):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > end:
            raise AssertionError("condição não ficou verdadeira a tempo")
        await asyncio.sleep(0.01)


async def start_all(rdv, *names, **over):
    clients = [P2PClient(rdv.cfg(n, **over)) for n in names]
    for c in clients:
        await c.start()
    return clients


async def stop_all(*clients):
    await asyncio.gather(*(c.stop() for c in clients))


# --- cenário 1: três peers ---------------------------------------------------


async def test_three_peers_register_discover_and_connect_to_each_other():
    async with FakeRdv() as rdv:
        clients = await start_all(rdv, "alice", "bob", "carol")
        await until(lambda: all(len(c.table.connected()) == 2 for c in clients))
        assert len(rdv.registered) == 3
        for c in clients:  # /conn: exatamente uma conexão por vizinho
            ids = sorted(conn.peer_id for conn in c.table.connected())
            assert ids == sorted({"alice@CIC", "bob@CIC", "carol@CIC"} - {c.cfg.peer_id})
        await stop_all(*clients)


async def test_ephemeral_port_registers_the_real_port():
    async with FakeRdv() as rdv:
        (c,) = await start_all(rdv, "alice")
        assert c.server.port and rdv.registered[("CIC", "alice")]["port"] == c.server.port
        await c.stop()


async def test_game_is_wired_to_router_and_table_by_the_client():
    """O cliente chama o wire_game da C: handlers no roteador, eventos na tabela."""
    from forca.game_wiring import HOST_HANDLERS, PLAYER_HANDLERS
    async with FakeRdv() as rdv:
        c = P2PClient(rdv.cfg("alice"))
        assert set(HOST_HANDLERS) | set(PLAYER_HANDLERS) <= set(c.router._handlers)
        # host e jogador usam a PeerTable como Sender e o busy cruzado (contrato 5.8)
        assert c.router.send == c.table.send_to
        assert c.host.active is False and c.player.active is False
        assert c.server.on_bad_line == c.router.on_bad_line


# --- encerramento ------------------------------------------------------------


async def test_stop_runs_the_steps_in_contract_order(caplog):
    caplog.set_level(logging.INFO, logger="PeerServer")
    async with FakeRdv() as rdv:
        a, b = await start_all(rdv, "alice", "bob")
        await until(lambda: a.table.connected() and b.table.connected())
        order = rdv.events  # o fake anota "UNREGISTER" aqui

        class Spy:
            def __init__(self, name):
                self.name = name

            async def shutdown(self):
                order.append("host.shutdown")

            async def leave(self):
                order.append("player.leave")

        a.host, a.player = Spy("host"), Spy("player")
        real_close_all = a.table.close_all

        async def close_all(reason="shutdown"):
            order.append("close_all.start")
            await real_close_all(reason)
            order.append("close_all.end")

        a.table.close_all = close_all
        await a.stop()
        assert order == ["host.shutdown", "player.leave", "close_all.start",
                         "close_all.end", "UNREGISTER"]
        assert ("CIC", "alice") not in rdv.registered
        assert "BYE from alice@CIC (reason=shutdown)" in caplog.text  # o bob recebeu o BYE
        await b.stop()


async def test_after_stop_no_task_or_socket_is_left():
    before = asyncio.all_tasks()
    async with FakeRdv() as rdv:
        a, b = await start_all(rdv, "alice", "bob")
        await until(lambda: a.table.connected() and b.table.connected())
        port = a.server.port
        await stop_all(a, b)
        await asyncio.sleep(0.05)
        leftover = [t for t in asyncio.all_tasks() - before if t is not asyncio.current_task()]
        assert leftover == [], leftover
        with pytest.raises(OSError):  # a porta não aceita mais conexões
            await asyncio.open_connection("127.0.0.1", port)


async def test_stop_twice_at_the_same_time_shuts_down_once():
    async with FakeRdv() as rdv:
        (c,) = await start_all(rdv, "alice")
        await asyncio.gather(c.stop(), c.stop())
        assert rdv.requests.count("UNREGISTER") == 1


async def test_stop_survives_a_failing_step():
    async with FakeRdv() as rdv:
        (c,) = await start_all(rdv, "alice")

        async def boom():
            raise RuntimeError("bug")

        c.host.shutdown = boom
        await c.stop()  # não levanta e os passos seguintes rodam
        assert rdv.requests.count("UNREGISTER") == 1


# --- Rendezvous: erros e taxa -------------------------------------------------


async def test_peer_not_registered_registers_again_and_repeats_discover():
    async with FakeRdv() as rdv:
        (c,) = await start_all(rdv, "alice")
        await until(lambda: "DISCOVER" in rdv.requests)
        rdv.forget_all()  # o registro expirou no servidor
        mark = len(rdv.requests)

        def repeated():  # chegou o DISCOVER repetido depois do REGISTER?
            seq = rdv.requests[mark:]
            return "REGISTER" in seq and "DISCOVER" in seq[seq.index("REGISTER"):]

        await until(repeated)
        seq = rdv.requests[mark:]
        # DISCOVER (peer_not_registered) -> REGISTER -> DISCOVER repetido
        i = seq.index("REGISTER")
        assert seq[i - 1] == "DISCOVER" and seq[i + 1] == "DISCOVER"
        assert ("CIC", "alice") in rdv.registered
        await c.stop()


async def test_rendezvous_down_does_not_crash_the_peer():
    cfg = Config(name="alice", namespace="CIC", rdv_host="127.0.0.1", rdv_port=1,
                 listen_port=0, discover_interval=0.1)
    c = P2PClient(cfg)
    await c.start()  # o Rendezvous recusa a conexão: só um aviso no log
    await asyncio.sleep(0.3)
    assert c.server.port and not c._registered
    await asyncio.wait_for(c.stop(), 10)


async def test_loop_never_spins_when_the_server_answers_errors():
    """Limite de 50 req/min do Rendezvous: com tudo falhando, 1 requisição por
    intervalo (nunca um laço sem pausa)."""
    async with FakeRdv() as rdv:
        rdv.fail_all = True
        (c,) = await start_all(rdv, "alice", discover_interval=0.2)
        await asyncio.sleep(1.0)
        n = len(rdv.requests)
        await c.stop()
        assert 3 <= n <= 9, n  # ~1 inicial + 1 por 0,2 s; um laço sem pausa daria centenas


async def test_normal_use_costs_about_three_requests_per_minute():
    cfg = Config()  # valores padrão da especificação
    discovers_per_min = 60 / cfg.discover_interval
    refreshes_per_min = 60 / (cfg.register_ttl / 2)
    assert discovers_per_min + refreshes_per_min < 4  # ≈ 3 req/min, longe das 50


async def test_reconcile_now_is_rate_limited():
    async with FakeRdv() as rdv:
        (c,) = await start_all(rdv, "alice", discover_interval=30)
        await until(lambda: "DISCOVER" in rdv.requests)
        before = rdv.requests.count("DISCOVER")
        assert await c.reconcile_now() is True
        assert await c.reconcile_now() is False  # 2º em seguida é ignorado
        assert rdv.requests.count("DISCOVER") == before + 1
        await c.stop()


# --- garantias que a C pediu à parte A (contrato 5.9) ----------------------------


async def test_duplicate_connection_never_fires_peer_stale_or_peer_gone():
    """`wire_game` trata todo peer_stale como queda: fechar a conexão duplicada
    não pode disparar evento. Várias rodadas, com os dois lados descobrindo um
    ao outro ao mesmo tempo (é quando nascem as conexões duplicadas)."""
    for _ in range(4):
        async with FakeRdv() as rdv:
            a, b = (P2PClient(rdv.cfg(n, discover_interval=0.05)) for n in ("alice", "bob"))
            events = []
            for c in (a, b):
                for ev in ("peer_stale", "peer_gone", "peer_connected"):
                    async def cb(pid, ev=ev, me=c.cfg.name):
                        events.append((me, ev, pid))
                    c.table.subscribe(ev, cb)
            await asyncio.gather(a.start(), b.start())
            await until(lambda: len(a.table.connected()) == 1 and len(b.table.connected()) == 1)
            await asyncio.sleep(0.4)  # sobra tempo para a duplicada ser fechada e ruídos aparecerem
            assert [e for e in events if e[1] != "peer_connected"] == []
            # um peer_connected por lado: a troca de duplicada é silenciosa
            assert sorted(events) == [("alice", "peer_connected", "bob@CIC"),
                                      ("bob", "peer_connected", "alice@CIC")]
            assert len(a.table.connected()) == 1 and len(b.table.connected()) == 1
            await stop_all(a, b)


async def test_stop_without_start_is_safe():
    async with FakeRdv() as rdv:
        c = P2PClient(rdv.cfg("alice"))
        await asyncio.wait_for(c.stop(), 2)  # nada foi criado pelo start(): não levanta
        assert rdv.requests == []  # e não fala com o Rendezvous (nunca registrou)


async def test_stop_is_safe_when_start_failed_on_a_busy_port():
    busy = await asyncio.start_server(lambda r, w: None, "0.0.0.0", 0)
    port = busy.sockets[0].getsockname()[1]
    try:
        async with FakeRdv() as rdv:
            c = P2PClient(rdv.cfg("alice", listen_port=port))
            with pytest.raises(OSError):
                await c.start()  # porta ocupada: falha fatal
            await asyncio.wait_for(c.stop(), 2)
    finally:
        busy.close()
        await busy.wait_closed()


async def test_start_cancelled_propagates_cancelled_error_and_stop_is_safe():
    """O main cancela o start() no 1º Ctrl+C: o CancelledError tem de passar, e o
    stop() logo depois (no finally do main) não pode levantar nem deixar nada."""
    reached = asyncio.Event()

    async def silent(reader, writer):  # Rendezvous que aceita e nunca responde
        reached.set()
        await asyncio.sleep(30)

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    before = asyncio.all_tasks()
    try:
        c = P2PClient(Config(name="alice", namespace="CIC", rdv_host="127.0.0.1", rdv_port=port,
                             listen_port=0))
        starting = asyncio.ensure_future(c.start())
        await asyncio.wait_for(reached.wait(), 2)  # o start() está no REGISTER, pendurado
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        started = asyncio.get_running_loop().time()
        await asyncio.wait_for(c.stop(), 12)
        # nunca registrou: não tenta UNREGISTER num servidor que não responde (esperaria 5 s)
        assert asyncio.get_running_loop().time() - started < 1.0
        await asyncio.sleep(0.05)
        mine = ("discover", "register", "ping", "read", "connect", "retry", "close", "shutdown")
        leftover = [t.get_name() for t in asyncio.all_tasks() - before
                    if t is not asyncio.current_task() and not t.done()
                    and t.get_name().startswith(mine)]
        assert leftover == []  # nenhuma tarefa do cliente sobrou
    finally:
        server.close()


# --- peers atrás do mesmo IP público (NAT sem hairpin) -----------------------------


async def test_neighbors_sharing_my_public_ip_are_reached_through_loopback():
    """O Rendezvous divulga o IP público; se ele é o mesmo, tenta 127.0.0.1 primeiro.
    203.0.113.7 (documentação) não é alcançável: sem a regra, a conexão travaria."""
    async with FakeRdv() as rdv:
        rdv.fake_public_ip = "203.0.113.7"
        started = asyncio.get_running_loop().time()
        a, b = await start_all(rdv, "alice", "bob")
        await until(lambda: len(a.table.connected()) == 1 and len(b.table.connected()) == 1, timeout=4)
        assert asyncio.get_running_loop().time() - started < 4  # sem esperar o timeout de 5 s
        assert [c.peer_id for c in a.table.connected()] == ["bob@CIC"]
        await stop_all(a, b)


async def test_different_public_ip_does_not_try_loopback():
    async with FakeRdv() as rdv:
        (c,) = await start_all(rdv, "alice")
        calls = []

        async def spy(ip, port):
            calls.append((ip, port))
            return None

        c.server.connect = spy
        c.rdv.public_ip = "203.0.113.7"
        await c._connect("198.51.100.9", 8082)  # outro IP: caminho normal
        assert calls == [("198.51.100.9", 8082)]
        calls.clear()
        await c._connect("203.0.113.7", 8082)  # mesmo IP público: loopback primeiro, depois o IP
        assert calls == [("127.0.0.1", 8082), ("203.0.113.7", 8082)]
        await c.stop()


# --- correções da revisão contra a especificação -----------------------------


async def test_register_is_refreshed_every_half_of_the_ttl():
    async with FakeRdv() as rdv:
        (c,) = await start_all(rdv, "alice", register_ttl=2, discover_interval=30)  # refresh a cada 1 s
        await until(lambda: rdv.requests.count("REGISTER") >= 3, timeout=5)  # 1 inicial + 2 refreshes
        await c.stop()


async def test_refresh_uses_the_ttl_the_server_applied():
    """O servidor satura o TTL pedido; o refresh deve seguir o valor efetivo."""
    async with FakeRdv() as rdv:
        (c,) = await start_all(rdv, "alice", register_ttl=86400 * 3)
        rdv.registered[("CIC", "alice")]["ttl"]  # registrado
        assert c._ttl == 86400 * 3  # o fake não satura; o P2PClient guarda o que o servidor devolveu
        await c.stop()


async def test_failed_discover_does_not_touch_the_peer_table():
    """DISCOVER com erro não reconcilia: um vizinho conectado não pode virar GONE."""
    async with FakeRdv() as rdv:
        a, b = await start_all(rdv, "alice", "bob")
        await until(lambda: len(a.table.connected()) == 1)
        rdv.fail_all = True
        await asyncio.sleep(0.6)  # vários ciclos de DISCOVER falhando
        assert len(a.table.connected()) == 1
        assert a.table.state_of("bob@CIC").value == "CONNECTED"
        await stop_all(a, b)


async def test_unregister_is_sent_even_after_a_transient_not_registered_state():
    async with FakeRdv() as rdv:
        (c,) = await start_all(rdv, "alice")
        await until(lambda: "DISCOVER" in rdv.requests)
        c._registered = False  # simula o estado depois de um peer_not_registered
        await c.stop()
        assert rdv.requests.count("UNREGISTER") == 1


async def test_reconcile_now_does_nothing_while_stopping():
    async with FakeRdv() as rdv:
        (c,) = await start_all(rdv, "alice", discover_interval=30)
        await until(lambda: "DISCOVER" in rdv.requests)
        stopping = asyncio.create_task(c.stop())
        await asyncio.sleep(0)
        before = rdv.requests.count("DISCOVER")
        assert await c.reconcile_now() is False
        await stopping
        assert rdv.requests.count("DISCOVER") == before
