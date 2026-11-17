#!/usr/bin/env python3
"""Roda os cenários de teste 1 a 10 da especificação com PROCESSOS REAIS.

    python tools/scenarios.py                 # todos, com um Rendezvous local
    python tools/scenarios.py --only 4,7a     # só alguns
    python tools/scenarios.py --list          # lista os cenários

Cada cenário sobe `python -m forca.main` (alice, bob e carol), manda comandos pela
entrada de cada um e CONFERE as linhas que a especificação espera na saída/nos logs.
Tempos curtos (PING 1 s, turno 6 s) para cada cenário levar segundos. A saída de cada
peer fica em logs/cenarios/<id>/<nome>.log (DEBUG, com o JSON bruto) e a transcrição da
tela em logs/cenarios/<id>/tela.txt. Código de saída 1 se algum cenário falhar.

Cenário 11 (interoperabilidade) não está aqui: depende do bot oficial (ver docs/testes.md).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rdv_local import LocalRendezvous  # noqa: E402
from run_local import ROOT, Launcher  # noqa: E402

OUT_DIR = ROOT / "logs" / "cenarios"
BASE_PORT = 29000
FAST_CONFIG = {
    "discover_interval": 2, "ping_interval": 1, "ping_miss_limit": 3, "turn_timeout": 6,
    "base_backoff": 1, "max_backoff": 4, "max_reconnect_attempts": 5,
}
LINE = re.compile(r"^\[(\w+)\] (.*)$")


class Abort(Exception):
    """O cenário não conseguiu nem montar o cenário (setup falhou)."""


class Scenario:
    """Um cenário em execução: peers reais, linhas capturadas e as verificações."""

    def __init__(self, sid: str, idx: int, rdv: LocalRendezvous, rdv_port: int, cfg_path: Path) -> None:
        self.sid, self.idx, self.rdv, self.rdv_port, self.cfg_path = sid, idx, rdv, rdv_port, cfg_path
        self.ns = f"S{idx}"
        self.dir = OUT_DIR / sid
        self.lines: dict[str, list[str]] = {}
        self.screen: list[str] = []
        self.checks: list[tuple[bool, str]] = []
        self.launchers: list[Launcher] = []
        self.ports = {"alice": BASE_PORT + idx * 10, "bob": BASE_PORT + idx * 10 + 1,
                      "carol": BASE_PORT + idx * 10 + 2}

    # --- peers ---
    def _out(self, text: str) -> None:
        self.screen.append(f"{time.strftime('%H:%M:%S')} {text}")
        m = LINE.match(text)
        if m:
            self.lines.setdefault(m.group(1), []).append(m.group(2))

    def _command(self, name, port, namespace, log_level, log_dir):
        return [sys.executable, "-m", "forca.main", "--config", str(self.cfg_path),
                "--name", name, "--namespace", namespace, "--port", str(port),
                "--rdv-host", "127.0.0.1", "--rdv-port", str(self.rdv_port),
                "--log-file", str(log_dir / f"{name}.log"), "--log-level", log_level]

    async def up(self, names=("alice", "bob", "carol")) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            (self.dir / f"{name}.log").unlink(missing_ok=True)  # log novo a cada execução
            lau = Launcher([name], base_port=self.ports[name], namespace=self.ns,
                           log_dir=self.dir, out=self._out, command=self._command)
            await lau.start()
            self.launchers.append(lau)

    def proc(self, name: str):
        for lau in reversed(self.launchers):
            if name in lau.peers:
                return lau.peers[name]
        raise KeyError(name)

    def send(self, name: str, text: str) -> None:
        asyncio.get_running_loop().create_task(self._send(name, text))

    async def _send(self, name: str, text: str) -> None:
        for lau in reversed(self.launchers):
            if name in lau.peers:
                await lau.send(name, text)
                return

    def pid(self, name: str) -> str:
        return f"{name}@{self.ns}"

    def mark(self, name: str) -> int:
        return len(self.lines.get(name, []))

    async def wait(self, name: str, regex: str, since: int = 0, timeout: float = 12.0):
        """Espera uma linha do peer que case com `regex` (a partir de `since`)."""
        pat = re.compile(regex)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for line in self.lines.get(name, [])[since:]:
                m = pat.search(line)
                if m:
                    return m
            await asyncio.sleep(0.05)
        return None

    def log_text(self, name: str) -> str:
        path = self.dir / f"{name}.log"
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

    def check(self, ok: bool, descr: str) -> bool:
        self.checks.append((bool(ok), descr))
        return bool(ok)

    async def need(self, name: str, regex: str, descr: str, since: int = 0, timeout: float = 12.0):
        """wait + check; devolve o match (ou None)."""
        m = await self.wait(name, regex, since, timeout)
        self.check(m is not None, descr)
        return m

    # --- montagem comum ---
    async def mesh(self, names=("alice", "bob", "carol")) -> None:
        """Espera cada peer conectar nos outros."""
        await self.up(names)
        for n in names:
            others = [o for o in names if o != n]
            for o in others:
                if not await self.wait(n, rf"\[PeerTable\] {o}@{self.ns} CONNECTED", timeout=15):
                    raise Abort(f"{n} não conectou em {o}")

    async def game(self, word: str = "banana", players=("bob", "carol")) -> None:
        """alice cria e inicia a partida; os jogadores entram na ordem dada."""
        await self.mesh()
        self.send("alice", f"/create {word}")
        if not await self.wait("alice", r"Partida criada"):
            raise Abort("alice não criou a partida")
        for p in players:
            m = self.mark(p)
            self.send(p, f"/join {self.pid('alice')}")
            if not await self.wait(p, r"\[Game\] Joined", m):
                raise Abort(f"{p} não entrou na partida")
        marks = {p: self.mark(p) for p in players}
        self.send("alice", "/start")
        for p in players:
            if not await self.wait(p, r"Game started", marks[p]):
                raise Abort(f"{p} não recebeu o GAME_START")

    async def guess(self, name: str, what: str, expect: str = "Jogada aceita") -> bool:
        m = self.mark(name)
        self.send(name, f"/word {what[1:]}" if what.startswith("=") else f"/guess {what}")
        return await self.wait(name, expect, m, timeout=8) is not None

    def states(self, name: str) -> list[int]:
        """seq de cada STATE aplicado pelo jogador, na ordem."""
        return [int(m.group(1)) for line in self.lines.get(name, [])
                if (m := re.search(r"\[Player\] STATE seq=(\d+) applied", line))]

    async def cleanup(self) -> None:
        for lau in self.launchers:
            for proc in lau.peers.values():
                if proc.returncode is None:
                    try:
                        proc.send_signal(signal.SIGCONT)  # se estava congelado (SIGSTOP)
                    except ProcessLookupError:
                        pass
                    proc.kill()
                await proc.wait()
            for t in lau._relays:
                t.cancel()
            await asyncio.gather(*lau._relays, return_exceptions=True)
        (self.dir / "tela.txt").write_text("\n".join(self.screen) + "\n", encoding="utf-8")


def ordered(text: str, patterns: list[str]) -> tuple[bool, list[int]]:
    """Cada padrão aparece em alguma linha, em ordem estritamente crescente de linha."""
    lines = text.splitlines()
    idxs, start = [], 0
    for pat in patterns:
        rx = re.compile(pat)
        found = next((i for i in range(start, len(lines)) if rx.search(lines[i])), None)
        if found is None:
            return False, idxs
        idxs.append(found)
        start = found + 1
    return True, idxs


# ============================ cenários ============================


async def s1_malha(sc: Scenario) -> None:
    await sc.mesh()
    await asyncio.sleep(2.5)  # dá tempo de o 1º PING/PONG medir o RTT
    for n in ("alice", "bob", "carol"):
        m = sc.mark(n)
        sc.send(n, "/conn")
        await sc.need(n, r"Conexões ativas \(2\)", f"{n}: /conn mostra exatamente 2 conexões", m)
    conn = [ln for ln in sc.lines["alice"] if re.search(r"(bob|carol)@\w+ +(inbound|outbound)", ln)]
    sc.check(len({re.search(r"(bob|carol)@", ln).group(1) for ln in conn}) == 2,
             "alice: uma conexão por vizinho (sem duplicadas)")
    sc.check(any("RTT" in ln and "ms" in ln for ln in conn), "RTT preenchido no /conn")
    # kill -9 em carol: os outros marcam STALE e /conn passa a listar uma só
    ma, mb = sc.mark("alice"), sc.mark("bob")
    sc.proc("carol").kill()
    await sc.need("alice", rf"carol@{sc.ns} STALE", "alice marca carol STALE após o kill -9", ma)
    await sc.need("bob", rf"carol@{sc.ns} STALE", "bob marca carol STALE após o kill -9", mb)
    m = sc.mark("alice")
    sc.send("alice", "/conn")
    await sc.need("alice", r"Conexões ativas \(1\)", "alice: /conn deixa de listar carol", m)


async def s2_vitoria(sc: Scenario) -> None:
    await sc.game()
    await sc.guess("bob", "b")
    await sc.guess("carol", "a")
    m = {p: sc.mark(p) for p in ("bob", "carol")}
    await sc.guess("bob", "n")
    for p in ("bob", "carol"):
        await sc.need(p, rf"GAME_OVER WON word=banana winner=bob@{sc.ns} — hash OK",
                      f"{p}: GAME_OVER WON, winner=bob e hash OK", m[p])
        await sc.need(p, rf"Placar: .*bob@{sc.ns}=3", f"{p}: placar com bob=3", m[p])
        seqs = sc.states(p)
        sc.check(seqs == list(range(1, len(seqs) + 1)) and len(seqs) >= 3,
                 f"{p}: STATE com seq 1..N sem falhas ({seqs})")


async def s3_derrota(sc: Scenario) -> None:
    await sc.game()
    for i, letter in enumerate("zxqwky"):
        await sc.guess("bob" if i % 2 == 0 else "carol", letter)
    for p in ("bob", "carol"):
        await sc.need(p, r"GAME_OVER LOST word=banana winner=None — hash OK",
                      f"{p}: GAME_OVER LOST, palavra revelada, winner=None, hash OK")


async def s4_fora_do_turno(sc: Scenario) -> None:
    await sc.game()
    before = sc.states("bob")
    m = sc.mark("carol")
    sc.send("carol", "/guess b")  # a vez é do bob
    await sc.need("carol", r"Jogada recusada: not_your_turn", "carol recebe not_your_turn", m)
    await asyncio.sleep(1.5)
    sc.check(sc.states("bob") == before and sc.states("carol") == before,
             f"nenhum STATE novo foi gerado (seq continua {before[-1:]})")


async def s5_repetida_e_palavra(sc: Scenario) -> None:
    await sc.game()
    await sc.guess("bob", "b")
    before = sc.states("carol")
    m = sc.mark("carol")
    sc.send("carol", "/guess b")  # já usada; a vez continua da carol
    await sc.need("carol", r"Jogada recusada: letter_already_used", "letter_already_used", m)
    await asyncio.sleep(1)
    sc.check(sc.states("carol") == before, "jogada recusada não gera STATE nem consome o turno")
    m = sc.mark("carol")
    await sc.guess("carol", "=cabana", expect=r"Jogada aceita: errada")  # /word errado
    await sc.need("carol", r"STATE seq=\d+ applied: b_{5} lives=5 turn=bob",
                  "/word errado custou 1 vida (5), nada foi revelado e o turno passou ao bob", m, timeout=3)
    marks = {p: sc.mark(p) for p in ("bob", "carol")}  # antes da jogada que encerra
    await sc.guess("bob", "=banana", expect=r"Jogada aceita: correta")
    for p in ("bob", "carol"):
        await sc.need(p, rf"GAME_OVER WON word=banana winner=bob@{sc.ns}",
                      f"{p}: /word certo encerra a partida com WON", marks[p])


async def s6_timeout(sc: Scenario) -> None:
    await sc.game()
    ma, mb, mc = sc.mark("alice"), sc.mark("bob"), sc.mark("carol")
    await sc.need("alice", rf"Turn timeout for bob@{sc.ns} — skipping", "host: Turn timeout ... skipping",
                  ma, timeout=12)
    await sc.need("carol", rf"bob@{sc.ns}: timeout", "STATE indica timeout (carol vê)", mc, timeout=5)
    await sc.need("carol", rf"STATE seq=2 applied: _{{6}} lives=6 turn=carol@{sc.ns}",
                  "o turno passou para carol e as vidas continuam 6", mc, timeout=5)


async def _queda_de_jogador(sc: Scenario, how: str) -> None:
    await sc.game()
    ma, mb = sc.mark("alice"), sc.mark("bob")
    if how == "kill":
        sc.proc("carol").kill()
    else:  # SIGSTOP: o socket continua aberto; só o KeepAlive percebe (3 PINGs)
        sc.proc("carol").send_signal(signal.SIGSTOP)
        await sc.need("alice", rf"carol@{sc.ns} missed 3 PINGs — marking STALE",
                      "alice: missed 3 PINGs — marking STALE", ma, timeout=15)
    await sc.need("alice", rf"Player carol@{sc.ns} STALE — removed from game",
                  "alice remove carol da partida", ma, timeout=15)
    await sc.need("bob", r"STATE seq=\d+ applied", "bob recebe o STATE da remoção", mb, timeout=5)
    m = sc.mark("bob")
    sc.send("bob", "/status")
    await sc.need("bob", rf"Jogadores: bob@{sc.ns}\b(?!,)", "bob: a partida segue só com bob", m)
    sc.check(await sc.guess("bob", "b"), "a partida continua: bob joga e a jogada é aceita")


async def s7a_queda_kill(sc: Scenario) -> None:
    await _queda_de_jogador(sc, "kill")


async def s7b_queda_sigstop(sc: Scenario) -> None:
    await _queda_de_jogador(sc, "stop")


async def s8_reconexao(sc: Scenario) -> None:
    await sc.game()
    sc.proc("carol").kill()
    await sc.need("alice", rf"Player carol@{sc.ns} STALE — removed from game", "carol removida", timeout=15)
    ma, m = sc.mark("alice"), sc.mark("carol")  # as linhas do processo novo começam aqui
    await sc.up(("carol",))  # carol volta (mesma porta, processo novo)
    await sc.need("carol", rf"\[PeerTable\] alice@{sc.ns} CONNECTED", "carol reconecta em alice", m, timeout=15)
    sc.send("carol", f"/join {sc.pid('alice')}")
    await sc.need("carol", r"\[Game\] Joined .*\(rejoin\)", "carol: JOIN_OK com rejoin=true", m)
    await sc.need("alice", rf"carol@{sc.ns} rejoined", "alice: carol rejoined", ma)
    await sc.need("carol", r"\[Player\] STATE seq=\d+ applied", "carol recebe o STATE corrente", m)
    m = sc.mark("carol")
    sc.send("carol", "/status")
    await sc.need("carol", rf"Jogadores: bob@{sc.ns}, carol@{sc.ns}", "carol volta ao FIM do rodízio", m)


async def s9_queda_do_host(sc: Scenario) -> None:
    await sc.game()
    marks = {p: sc.mark(p) for p in ("bob", "carol")}
    sc.proc("alice").kill()
    for p in ("bob", "carol"):
        await sc.need(p, rf"\[Game\] Host alice@{sc.ns} unreachable — game aborted",
                      f"{p}: Host alice unreachable — game aborted", marks[p], timeout=10)
    m = sc.mark("bob")
    sc.send("bob", "/status")
    await sc.need("bob", r"Você não está em uma partida", "bob volta a IDLE", m)


async def _quit_ordem(sc: Scenario, quem: str, padroes: list[str], descr: str, sinal=None) -> None:
    mark = {p: sc.mark(p) for p in ("alice", "bob", "carol")}
    if sinal is None:
        sc.send(quem, "/quit")
    else:
        sc.proc(quem).send_signal(sinal)
    try:
        code = await asyncio.wait_for(sc.proc(quem).wait(), 15)
    except asyncio.TimeoutError:
        code = None
    sc.check(code == 0, f"{quem}: o processo termina sozinho com código 0 (código={code})")
    ok, idx = ordered(sc.log_text(quem), padroes)
    sc.check(ok, f"{descr} (linhas {idx} do log)")
    return mark


async def s10a_quit_host(sc: Scenario) -> None:
    await sc.game()
    mark = await _quit_ordem(sc, "alice", [
        r"\[Wire\] -> \S+ \{\"type\":\"GAME_OVER\".*ABORTED", r"\[Wire\] -> \S+ \{\"type\":\"BYE\"",
        rf"\[RDV\] unregistered alice@{sc.ns}"],
        "alice (host RUNNING): GAME_OVER ABORTED → BYE → UNREGISTER, nessa ordem")
    await sc.need("bob", r"Partida abortada pelo host \(host_shutdown\)", "bob volta a IDLE", mark["bob"])


async def s10b_quit_jogador(sc: Scenario) -> None:
    await sc.game()
    await _quit_ordem(sc, "bob", [
        r"\[Wire\] -> \S+ \{\"type\":\"LEAVE\"", r"\[Wire\] -> \S+ \{\"type\":\"BYE\"",
        rf"\[RDV\] unregistered bob@{sc.ns}"],
        "bob (jogador em partida): LEAVE → BYE → UNREGISTER")


async def s10c_quit_sem_partida(sc: Scenario) -> None:
    await sc.mesh()
    await _quit_ordem(sc, "bob", [
        r"\[Wire\] -> \S+ \{\"type\":\"BYE\"", rf"\[RDV\] unregistered bob@{sc.ns}"],
        "bob (sem partida): BYE → UNREGISTER")
    # o Rendezvous não guarda mais o registro do bob: um DISCOVER de outro peer não o traz
    sc.check((sc.ns, "bob") not in sc.rdv.registered, "o UNREGISTER removeu o bob do Rendezvous")
    sc.check((sc.ns, "alice") in sc.rdv.registered and (sc.ns, "carol") in sc.rdv.registered,
             "alice e carol continuam registradas")
    sc.check("UNREGISTER" in sc.rdv.requests, "o Rendezvous recebeu o UNREGISTER")


async def s10d_ctrl_c(sc: Scenario) -> None:
    await sc.game()
    await _quit_ordem(sc, "alice", [
        r"\[Wire\] -> \S+ \{\"type\":\"GAME_OVER\".*ABORTED", r"\[Wire\] -> \S+ \{\"type\":\"BYE\"",
        rf"\[RDV\] unregistered alice@{sc.ns}"],
        "Ctrl+C (SIGINT) no host tem a mesma ordem do /quit", sinal=signal.SIGINT)


SCENARIOS: list[tuple[str, str, Callable[[Scenario], Awaitable[None]]]] = [
    ("1", "malha de descoberta (3 peers, /conn, kill -9)", s1_malha),
    ("2", "partida completa com vitória", s2_vitoria),
    ("3", "partida com derrota", s3_derrota),
    ("4", "jogada fora do turno", s4_fora_do_turno),
    ("5", "letra repetida e palpite de palavra", s5_repetida_e_palavra),
    ("6", "timeout de turno", s6_timeout),
    ("7a", "queda de jogador com kill -9", s7a_queda_kill),
    ("7b", "queda de jogador congelado (SIGSTOP, 3 PINGs perdidos)", s7b_queda_sigstop),
    ("8", "reconexão de jogador (rejoin)", s8_reconexao),
    ("9", "queda do host", s9_queda_do_host),
    ("10a", "/quit no host com partida RUNNING", s10a_quit_host),
    ("10b", "/quit em jogador durante a partida", s10b_quit_jogador),
    ("10c", "/quit sem partida", s10c_quit_sem_partida),
    ("10d", "Ctrl+C no host com partida RUNNING", s10d_ctrl_c),
]


async def run_one(idx: int, sid: str, title: str, fn, rdv: LocalRendezvous, rdv_port: int, cfg: Path) -> bool:
    sc = Scenario(sid, idx, rdv, rdv_port, cfg)
    t0 = time.monotonic()
    error = None
    try:
        await asyncio.wait_for(fn(sc), 120)
    except Abort as exc:
        error = f"montagem falhou: {exc}"
    except asyncio.TimeoutError:
        error = "estourou 120 s"
    except Exception as exc:  # um bug do script não pode esconder os outros cenários
        error = f"erro no script: {exc!r}"
    finally:
        await sc.cleanup()
    ok = error is None and bool(sc.checks) and all(c for c, _ in sc.checks)
    print(f"\n{'PASSOU' if ok else 'FALHOU'}  cenário {sid}: {title}  ({time.monotonic() - t0:.1f} s)")
    for good, descr in sc.checks:
        print(f"   {'✓' if good else '✗'} {descr}")
    if error:
        print(f"   ✗ {error}")
    return ok


async def main_async(only: list[str] | None) -> int:
    rdv = LocalRendezvous()
    server = await rdv.start(0)
    rdv_port = server.sockets[0].getsockname()[1]
    tmp = Path(tempfile.mkdtemp(prefix="forca-cenarios-"))
    cfg = tmp / "config.json"
    cfg.write_text(json.dumps({**json.loads((ROOT / "config.json").read_text()), **FAST_CONFIG}))
    if OUT_DIR.exists() and not only:
        shutil.rmtree(OUT_DIR)
    results = {}
    try:
        for idx, (sid, title, fn) in enumerate(SCENARIOS, start=1):
            if only and sid not in only:
                continue
            results[sid] = await run_one(idx, sid, title, fn, rdv, rdv_port, cfg)
    finally:
        server.close()
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [s for s, ok in results.items() if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} cenários passaram"
          + (f"; falharam: {', '.join(failed)}" if failed else "") + f". Logs em {OUT_DIR}")
    return 1 if failed else 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Cenários 1 a 10 da especificação, com peers reais")
    ap.add_argument("--only", help="ids separados por vírgula, ex.: 4,7a,10")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()
    if args.list:
        for sid, title, _ in SCENARIOS:
            print(f"{sid:>4}  {title}")
        return
    only = None
    if args.only:
        wanted = [s.strip() for s in args.only.split(",") if s.strip()]
        only = [sid for sid, _, _ in SCENARIOS if sid in wanted or sid.rstrip("abcd") in wanted]
    sys.exit(asyncio.run(main_async(only)))


if __name__ == "__main__":
    main()
