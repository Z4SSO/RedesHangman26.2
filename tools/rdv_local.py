#!/usr/bin/env python3
"""Servidor Rendezvous local mínimo, com a mesma API do servidor público.

    python tools/rdv_local.py --port 18080

Serve para testar sem depender do servidor público (que é compartilhado, pode estar
lento e mostra peers de outros grupos). Implementa REGISTER, DISCOVER e UNREGISTER
como na especificação ("Protocolo Peer–Rendezvous"): uma linha JSON por conexão,
resposta de uma linha, conexão fechada em seguida. Não implementa expiração por TTL
nem o limite de 50 req/min (é só para testes). Todos os peers saem por 127.0.0.1.

Os peers precisam apontar para ele: `--rdv-host 127.0.0.1 --rdv-port 18080`.
"""

from __future__ import annotations

import argparse
import asyncio
import json


class LocalRendezvous:
    def __init__(self) -> None:
        self.registered: dict[tuple[str, str], dict] = {}
        self.requests: list[str] = []  # tipo de cada requisição, na ordem (para os testes)

    def respond(self, req: dict) -> dict:
        kind = req.get("type")
        if kind == "REGISTER":
            port = req.get("port")
            if not isinstance(port, int) or not 1 <= port <= 65535:
                return {"status": "ERROR", "message": "bad_port"}
            ttl = req.get("ttl", 7200)
            self.registered[(req["namespace"], req["name"])] = {
                "ip": "127.0.0.1", "port": port, "name": req["name"],
                "namespace": req["namespace"], "ttl": ttl, "expires_in": ttl,
            }
            return {"status": "OK", "ttl": ttl, "ip": "127.0.0.1", "port": port}
        if kind == "DISCOVER":
            if not self.registered:
                return {"status": "ERROR", "message": "peer_not_registered"}
            ns = req.get("namespace")
            return {"status": "OK", "peers": [p for p in self.registered.values()
                                              if ns is None or p["namespace"] == ns]}
        if kind == "UNREGISTER":
            if "namespace" not in req:
                return {"status": "ERROR", "message": "namespace_required"}
            self.registered.pop((req["namespace"], req.get("name")), None)
            return {"status": "OK"}
        return {"status": "ERROR", "message": "Unknown command"}

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            line = await asyncio.wait_for(reader.readline(), 5)
            req = json.loads(line)
            self.requests.append(str(req.get("type")))
            resp = self.respond(req)
        except (ValueError, asyncio.TimeoutError):
            resp = {"status": "ERROR", "message": "Empty request line"}
        writer.write((json.dumps(resp) + "\n").encode())
        await writer.drain()
        writer.close()

    async def start(self, port: int = 0, host: str = "127.0.0.1") -> asyncio.AbstractServer:
        """Começa a escutar; com port=0 o sistema escolhe (veja server.sockets[0])."""
        return await asyncio.start_server(self.handle, host, port)


async def _main(port: int) -> None:
    server = await LocalRendezvous().start(port)
    print(f"[rdv_local] escutando em 127.0.0.1:{port}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rendezvous local para testes")
    ap.add_argument("--port", type=int, default=18080)
    try:
        asyncio.run(_main(ap.parse_args().port))
    except KeyboardInterrupt:
        pass
