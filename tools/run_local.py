#!/usr/bin/env python3
"""Sobe N peers locais, mostra a saída de cada um e deixa mandar comandos a cada peer.

    python tools/run_local.py --names alice,bob,carol --base-port 8081 --namespace CIC

Entrada (uma linha por comando):
    bob /join alice@CIC     manda "/join alice@CIC" para o bob (também vale "bob> /join ...")
    all /conn               manda para todos
    !kill carol             SIGKILL no carol (cenários 7 e 9: queda abrupta)
    !list                   mostra quem está vivo
    !quit                   encerra todos (envia /quit, espera --grace s, mata quem sobrar)

Todos os peers saem pelo MESMO IP (o limite do Rendezvous é por IP) e se registram com o IP
público: no servidor compartilhado use um --namespace só seu (ex.: --namespace CIC-caio) para não
colidir com peers de outros grupos. Cada peer escreve o log completo em logs/<nome>.log. Fechar a entrada (Ctrl+D) ou Ctrl+C
também encerra tudo; nenhum processo fica órfão.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
GRACE = 10.0  # s que o /quit tem antes de o peer ser morto (o BYE espera até 2 s por vizinho)


def peer_command(name: str, port: int, namespace: str, log_level: str, log_dir: Path) -> list[str]:
    return [sys.executable, "-m", "forca.main", "--name", name, "--namespace", namespace,
            "--port", str(port), "--log-file", str(log_dir / f"{name}.log"), "--log-level", log_level]


class Launcher:
    def __init__(self, names: list[str], base_port: int = 8081, namespace: str = "CIC",
                 log_level: str = "DEBUG", log_dir: Path = ROOT / "logs",
                 out: Callable[[str], None] = print, command=peer_command) -> None:
        self.names, self.base_port, self.namespace = names, base_port, namespace
        self.log_level, self.log_dir, self.out, self.command = log_level, log_dir, out, command
        self.peers: dict[str, asyncio.subprocess.Process] = {}
        self._relays: list[asyncio.Task] = []

    async def start(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        for i, name in enumerate(self.names):
            port = self.base_port + i
            cmd = self.command(name, port, self.namespace, self.log_level, self.log_dir)
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=ROOT, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT, env={**os.environ, "PYTHONUNBUFFERED": "1"})
            self.peers[name] = proc
            self._relays.append(asyncio.create_task(self._relay(name, proc)))
            self.out(f"[run_local] {name}@{self.namespace} na porta {port} (pid {proc.pid})")

    async def _relay(self, name: str, proc: asyncio.subprocess.Process) -> None:
        """Repassa a saída do peer com o prefixo [nome]."""
        while line := await proc.stdout.readline():
            self.out(f"[{name}] {line.decode(errors='replace').rstrip()}")
        await proc.wait()
        self.out(f"[{name}] terminou (código {proc.returncode})")

    def alive(self) -> list[str]:
        return [n for n, p in self.peers.items() if p.returncode is None]

    async def send(self, name: str, text: str) -> None:
        proc = self.peers[name]
        if proc.returncode is not None:
            self.out(f"[run_local] {name} já terminou")
            return
        try:
            proc.stdin.write((text + "\n").encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            self.out(f"[run_local] {name} não está mais lendo comandos")

    async def kill(self, name: str) -> None:
        proc = self.peers[name]
        if proc.returncode is None:
            proc.kill()  # SIGKILL: sem BYE, sem UNREGISTER
            self.out(f"[run_local] {name} morto com SIGKILL")

    async def handle(self, line: str) -> bool:
        """Executa uma linha de entrada. False quando é para encerrar."""
        line = line.strip()
        if not line:
            return True
        if line in ("!quit", "!exit"):
            return False
        if line == "!list":
            self.out(f"[run_local] vivos: {', '.join(self.alive()) or '(nenhum)'}")
            return True
        if line.startswith("!kill"):
            _, _, who = line.partition(" ")
            if who.strip() in self.peers:
                await self.kill(who.strip())
            else:
                self.out(f"[run_local] uso: !kill <{'|'.join(self.names)}>")
            return True
        who, _, text = line.partition(" ")
        who, text = who.rstrip(">"), text.strip()
        if not text or (who != "all" and who not in self.peers):
            self.out(f"[run_local] uso: <{'|'.join(self.names)}|all> <comando>   ou   !kill <nome>   ou   !quit")
            return True
        for name in (self.names if who == "all" else [who]):
            await self.send(name, text)
        return True

    async def quit_all(self, grace: float = GRACE) -> None:
        """/quit a todos, espera `grace` s e mata quem sobrar. Nenhum processo fica órfão."""
        for name in self.alive():
            await self.send(name, "/quit")
        procs = [p for p in self.peers.values() if p.returncode is None]
        try:
            await asyncio.wait_for(asyncio.gather(*(p.wait() for p in procs)), grace)
        except asyncio.TimeoutError:
            pass
        for name, proc in self.peers.items():
            if proc.returncode is None:
                self.out(f"[run_local] {name} não saiu em {grace:g} s: SIGKILL")
                proc.kill()
        await asyncio.gather(*(p.wait() for p in self.peers.values()))
        await asyncio.gather(*self._relays, return_exceptions=True)


def _read_input(loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    """Thread daemon: lê o teclado sem bloquear o event loop. EOF vira !quit."""
    for line in sys.stdin:
        loop.call_soon_threadsafe(queue.put_nowait, line)
    loop.call_soon_threadsafe(queue.put_nowait, "!quit")


async def run(args: argparse.Namespace) -> None:
    names = [n.strip() for n in args.names.split(",") if n.strip()]
    if not names or len(set(names)) != len(names):
        raise SystemExit("--names precisa de nomes não vazios e sem repetição")
    launcher = Launcher(names, args.base_port, args.namespace, args.log_level)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    loop.add_signal_handler(signal.SIGINT, queue.put_nowait, "!quit")
    loop.add_signal_handler(signal.SIGTERM, queue.put_nowait, "!quit")
    threading.Thread(target=_read_input, args=(loop, queue), daemon=True).start()
    try:
        await launcher.start()
        print("Comandos: <nome|all> <comando> | !kill <nome> | !list | !quit")
        while await launcher.handle(await queue.get()):
            pass
    finally:
        await launcher.quit_all(args.grace)


def main() -> None:
    ap = argparse.ArgumentParser(description="Sobe N peers locais do PyP2P-Forca")
    ap.add_argument("--names", default="alice,bob,carol")
    ap.add_argument("--base-port", type=int, default=8081)
    ap.add_argument("--namespace", default="CIC")
    ap.add_argument("--log-level", default="DEBUG", help="nível mostrado na tela de cada peer")
    ap.add_argument("--grace", type=float, default=GRACE, help="s para os peers saírem no /quit antes do SIGKILL")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
