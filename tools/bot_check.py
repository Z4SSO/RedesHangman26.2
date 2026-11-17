#!/usr/bin/env python3
"""Interoperabilidade (cenário 11): o nosso cliente como JOGADOR contra o bot oficial.

    python tools/bot_check.py win [N]     # N jogadores (padrão 2) que acham a palavra e vencem
    python tools/bot_check.py lose        # 1 jogador que erra de propósito até perder
    python tools/bot_check.py timeout     # 1 jogador que fica inativo até o bot removê-lo (BYE idle)
    python tools/bot_check.py all

Usa o Rendezvous público e o bot dos monitores (`bot@CIC`, 45.171.101.167:8081). Os peers
de teste se registram no namespace CIC com nomes `testeX` e são removidos (UNREGISTER) no fim.
O bot atende todos os grupos: se houver outra partida em andamento o script espera o próximo
lobby (até 5 min). O JSON bruto trocado com o bot vai para logs/bot/<modo>.wire.log.

A palavra é descoberta por frequência de letras usando words.txt como dicionário (as palavras
do bot, como "abacaxi" e "algoritmo", estão nessa lista).
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forca import protocol  # noqa: E402
from forca.config import Config  # noqa: E402
from forca.models import PeerState, PlayerState  # noqa: E402
from forca.p2p_client import P2PClient  # noqa: E402

BOT = "bot@CIC"
LOG_DIR = ROOT / "logs" / "bot"
WORDS = [w.strip() for w in (ROOT / "words.txt").read_text(encoding="utf-8").split() if w.strip().isalpha()]
T0 = time.monotonic()


def say(who: str, text: str) -> None:
    print(f"[{time.monotonic() - T0:6.1f}s] {who:7} {text}", flush=True)


class Collector(logging.Handler):
    """Guarda as mensagens de log (o jogo escreve o resultado pelo logger)."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(f"{record.name}|{record.getMessage()}")

    def find(self, regex: str) -> list[str]:
        rx = re.compile(regex)
        return [r for r in self.records if rx.search(r)]


async def start(name: str, port: int) -> P2PClient:
    client = P2PClient(replace(Config(), name=name, namespace="CIC", listen_port=port, log_file=None))
    await client.start()
    for _ in range(80):
        if client.table.state_of(BOT) == PeerState.CONNECTED:
            return client
        await asyncio.sleep(0.5)
    await client.stop()
    raise SystemExit(f"{name}: não conseguiu conectar ao bot (Rendezvous/bot fora do ar?)")


async def wait_open(client: P2PClient, who: str, timeout: float = 300) -> dict:
    """Espera o bot abrir um lobby (status OPEN) e devolve a partida."""
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        reply = await client.router.request(
            BOT, protocol.new_message("GAME_LIST", src=client.cfg.peer_id, dst=BOT), timeout=5)
        games = (reply or {}).get("games") or []
        if games and games[0]["status"] == "OPEN":
            return games[0]
        state = (games[0]["game_id"], games[0]["status"]) if games else None
        if state != last:
            say(who, f"aguardando lobby aberto (bot: {state})")
            last = state
        await asyncio.sleep(3)
    raise SystemExit("o bot não abriu lobby a tempo")


def pick(player, wrong_only: bool = False) -> tuple[str, str]:
    """Próxima jogada: ('word', palavra) quando só resta uma candidata, senão a letra mais frequente."""
    mask = player.masked.replace(" ", "")
    wrong, known = set(player.wrong), {c for c in mask if c != "_"}

    def fits(word: str) -> bool:
        if len(word) != len(mask) or set(word) & wrong:
            return False
        return all((m == "_" and c not in known) or m == c for c, m in zip(word, mask))

    cands = [w for w in WORDS if fits(w)]
    if len(cands) == 1:
        return "word", cands[0]
    freq = Counter(c for w in (cands or WORDS) for c in set(w) if c not in known and c not in wrong)
    return "letter", (freq.most_common(1)[0][0] if freq else "e")


async def play(client: P2PClient, who: str, deadline: float, lose: bool = False) -> bool:
    """Joga cada vez que for a vez; True quando a partida acaba (GAME_OVER)."""
    junk = iter("zqxkwjyvh")  # letras que não estão em nenhuma palavra do dicionário
    last_seq, was_playing = -1, False
    while time.monotonic() < deadline:
        p = client.player
        was_playing |= p.state == PlayerState.PLAYING
        if was_playing and p.state == PlayerState.IDLE:
            return True
        if p.state == PlayerState.PLAYING and p.turn == client.cfg.peer_id and p.seq != last_seq:
            last_seq = p.seq
            kind, value = ("letter", next(junk, "z")) if lose else pick(p)
            say(who, f"vez (seq={p.seq}) {p.masked} erradas={p.wrong} vidas={p.lives} → {kind} {value}")
            await (p.guess_word(value) if kind == "word" else p.guess_letter(value))
        await asyncio.sleep(0.25)
    return False


def report(title: str, checks: list[tuple[bool, str]]) -> bool:
    ok = all(c for c, _ in checks)
    print(f"\n{'PASSOU' if ok else 'FALHOU'}  {title}")
    for good, text in checks:
        print(f"   {'✓' if good else '✗'} {text}")
    return ok


async def run_mode(mode: str, players: int) -> bool:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    collector = Collector()
    wire = logging.getLogger("Wire")
    wire.setLevel(logging.DEBUG)
    wire.propagate = False  # o JSON bruto vai só para o arquivo e para a verificação, não para a tela
    wire_file = logging.FileHandler(LOG_DIR / f"{mode}.wire.log", mode="w", encoding="utf-8")
    wire_file.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    for h in (collector, wire_file):
        wire.addHandler(h)
    for name in ("Player", "Game"):
        logging.getLogger(name).addHandler(collector)
        logging.getLogger(name).setLevel(logging.INFO)

    names = [(f"teste{chr(65 + i)}", 28101 + i) for i in range(players)]
    clients = [(n, await start(n, port)) for n, port in names]
    checks: list[tuple[bool, str]] = []
    try:
        say("*", f"conectados ao bot: {[n for n, _ in names]}")
        game = await wait_open(clients[0][1], names[0][0])
        await asyncio.gather(*(c.player.join(BOT, game["game_id"]) for _, c in clients))
        say("*", f"entraram em {game['game_id']}")
        if mode == "timeout":
            return await timeout_mode(clients[0][1], clients[0][0], collector, checks)
        results = await asyncio.gather(*(
            play(c, n, time.monotonic() + 240, lose=(mode == "lose")) for n, c in clients))
        checks.append((all(results), "a partida terminou para todos os jogadores"))
        over = collector.find(r"GAME_OVER (WON|LOST)")
        if mode == "win":
            checks.append((len(over) >= players and all("GAME_OVER WON" in o for o in over[:players]),
                           f"GAME_OVER WON recebido por todos ({len(over)} mensagens)"))
            checks.append((all("winner=teste" in o for o in over[:players]), "winner é um dos nossos jogadores"))
        else:
            checks.append((bool(over) and "GAME_OVER LOST" in over[0] and "winner=None" in over[0],
                           "GAME_OVER LOST com winner=None e palavra revelada"))
        checks.append((all("hash OK" in o for o in over) and bool(over), "o word_hash do GAME_START confere (hash OK)"))
        seqs = [int(m.group(1)) for r in collector.find(r"STATE seq=\d+ applied") if (m := re.search(r"seq=(\d+)", r))]
        checks.append((not collector.find(r"ignored"), "nenhum STATE descartado por seq fora de ordem"))
        checks.append((not collector.find(r"hash mismatch"), "nenhum aviso 'host cheated: hash mismatch'"))
        checks.append((bool(seqs), f"STATE aplicados pelo nosso jogador (seq {seqs[:1]}..{seqs[-1:]})"))
        return report(f"cenário 11 ({mode}, {players} jogador(es)) contra {BOT}", checks)
    finally:
        await asyncio.gather(*(c.stop() for _, c in clients))


async def timeout_mode(client: P2PClient, who: str, collector: Collector, checks: list) -> bool:
    """Entra e não joga: após 3 timeouts o bot remove o jogador com BYE reason "idle"."""
    say(who, "entrei e NÃO vou jogar (esperando o bot me remover após 3 timeouts de 30 s)")
    end = time.monotonic() + 200
    while time.monotonic() < end and not collector.find(r'"type":"BYE".*"reason":"idle"'):
        await asyncio.sleep(1)
    bye = collector.find(r'<- bot@CIC \{"type":"BYE".*"reason":"idle"')
    checks.append((bool(bye), "o bot enviou BYE reason:\"idle\" após os timeouts"))
    if bye:
        msg_id = re.search(r'"msg_id":"([^"]+)"', bye[0]).group(1)
        checks.append((bool(collector.find(rf'-> bot@CIC \{{"type":"BYE_OK","msg_id":"{msg_id}"')),
                       "respondemos BYE_OK com o mesmo msg_id"))
    timeouts = collector.find(r"timeout")
    checks.append((len(timeouts) >= 1, f"STATE com timeout:true anunciado ({len(timeouts)}x no log)"))
    checks.append((client.player.lives == client.cfg.lives or client.player.state == PlayerState.IDLE,
                   "a perda de vez não custou vida"))
    await asyncio.sleep(8)  # o PeerTable reconecta sozinho; tentamos voltar à partida
    game = await client.router.request(
        BOT, protocol.new_message("GAME_LIST", src=client.cfg.peer_id, dst=BOT), timeout=5)
    games = (game or {}).get("games") or []
    if games:
        await client.player.join(BOT, games[0]["game_id"])
        await asyncio.sleep(3)
    refused = collector.find(r"Cannot join .*: (game_running|game_finished|unknown_game)")
    checks.append((bool(refused) or client.player.state == PlayerState.IDLE,
                   f"voltar à partida é recusado pelo bot ({refused[-1].split('|')[1] if refused else 'sem JOIN_ERR'})"))
    return report(f"cenário 11 (timeout) contra {BOT}", checks)


async def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="           %(levelname)-7s [%(name)s] %(message)s")
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    plan = {"win": [("win", n)], "lose": [("lose", 1)], "timeout": [("timeout", 1)],
            "all": [("win", 2), ("lose", 1), ("timeout", 1)]}.get(mode)
    if plan is None:
        print(__doc__)
        return 2
    results = [await run_mode(m, k) for m, k in plan]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
