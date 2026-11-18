# Trabalho de Programação — PyP2P-Forca (CIC0124 Redes de Computadores, 2026/2)
# Grupo 2: Luís Felipe de Lima Benvegnú (251004330) e Caio Bonini Sampaio (251004287)
"""tools/run_local.py com peers falsos (um script que ecoa a entrada): sem rede e sem a parte A."""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("run_local", ROOT / "tools" / "run_local.py")
run_local = importlib.util.module_from_spec(spec)
sys.modules["run_local"] = run_local
spec.loader.exec_module(run_local)

ECHO = """
import sys
print("ready", flush=True)
for line in sys.stdin:
    line = line.strip()
    print("got: " + line, flush=True)
    if line == "/quit" and "--ignore-quit" not in sys.argv:
        break
"""


@pytest.fixture
def fake_peer(tmp_path):
    script = tmp_path / "fake_peer.py"
    script.write_text(ECHO)

    def command(name, port, namespace, level, log_dir, *, ignore_quit=False):
        return [sys.executable, str(script), name, str(port)] + (["--ignore-quit"] if ignore_quit else [])

    return command


async def make(fake_peer, tmp_path, names=("alice", "bob", "carol"), command=None):
    out = []
    launcher = run_local.Launcher(list(names), 9000, "CIC", "DEBUG", tmp_path / "logs", out.append, command or fake_peer)
    await launcher.start()
    return launcher, out


async def settle(out, expected, timeout=5.0):
    """Espera `expected` aparecer na saída (lista de linhas)."""
    end = asyncio.get_running_loop().time() + timeout
    while not any(expected in line for line in out):
        if asyncio.get_running_loop().time() > end:
            raise AssertionError(f"não apareceu: {expected!r}\n" + "\n".join(out))
        await asyncio.sleep(0.02)


async def test_starts_one_process_per_peer_on_consecutive_ports(fake_peer, tmp_path):
    launcher, out = await make(fake_peer, tmp_path)
    try:
        for n in ("alice", "bob", "carol"):
            await settle(out, f"[{n}] ready")
        for i, n in enumerate(("alice", "bob", "carol")):
            assert any(f"{n}@CIC na porta {9000 + i}" in l for l in out)
        assert (tmp_path / "logs").is_dir() and launcher.alive() == ["alice", "bob", "carol"]
    finally:
        await launcher.quit_all(1)


async def test_commands_go_only_to_the_chosen_peer_and_all_reaches_everyone(fake_peer, tmp_path):
    launcher, out = await make(fake_peer, tmp_path)
    try:
        await launcher.handle("bob /join alice@CIC")
        await launcher.handle("carol> /status")  # a sintaxe com ">" também vale
        await settle(out, "[bob] got: /join alice@CIC")
        await settle(out, "[carol] got: /status")
        assert not any("[alice] got" in l for l in out)
        await launcher.handle("all /conn")
        for n in ("alice", "bob", "carol"):
            await settle(out, f"[{n}] got: /conn")
    finally:
        await launcher.quit_all(1)


async def test_bad_input_only_prints_usage(fake_peer, tmp_path):
    launcher, out = await make(fake_peer, tmp_path)
    try:
        for line in ("zed /conn", "bob", "!kill zed", "   ", "!list"):
            assert await launcher.handle(line) is True
        assert sum("uso:" in l for l in out) == 3 and any("vivos: alice, bob, carol" in l for l in out)
    finally:
        await launcher.quit_all(1)


async def test_kill_is_a_sigkill_and_the_others_keep_running(fake_peer, tmp_path):
    launcher, out = await make(fake_peer, tmp_path)
    try:
        await launcher.handle("!kill carol")
        await settle(out, "[carol] terminou (código -9)")  # -9 = morto por SIGKILL, sem /quit
        assert launcher.alive() == ["alice", "bob"]
        await launcher.handle("carol /conn")  # peer morto: avisa e segue
        assert any("carol já terminou" in l for l in out)
    finally:
        await launcher.quit_all(1)


async def test_quit_all_leaves_no_orphan_even_if_a_peer_ignores_quit(fake_peer, tmp_path):
    def command(name, port, ns, level, log_dir):
        return fake_peer(name, port, ns, level, log_dir, ignore_quit=(name == "bob"))

    launcher, out = await make(fake_peer, tmp_path, command=command)
    assert await launcher.handle("!quit") is False
    await launcher.quit_all(grace=0.5)
    assert launcher.alive() == [] and all(p.returncode is not None for p in launcher.peers.values())
    assert "[run_local] bob não saiu em 0.5 s: SIGKILL" in out
    assert any("[alice] terminou (código 0)" in l for l in out)  # quem obedeceu saiu limpo


async def test_kill_needs_the_exact_command(fake_peer, tmp_path):
    launcher, out = await make(fake_peer, tmp_path)
    try:
        await launcher.handle("!killall")  # não é "!kill": não pode matar ninguém
        assert launcher.alive() == ["alice", "bob", "carol"] and any("uso:" in l for l in out)
    finally:
        await launcher.quit_all(1)


def test_default_screen_level_is_info_and_the_log_file_keeps_everything():
    assert run_local.Launcher(["a"]).log_level == "INFO"  # o arquivo já recebe DEBUG e o JSON bruto
    assert run_local.build_parser().parse_args([]).log_level == "INFO"
    cmd = run_local.peer_command("bob", 8082, "CIC", "INFO", Path("/x"))
    assert cmd[cmd.index("--log-file") + 1] == "/x/bob.log" and cmd[cmd.index("--log-level") + 1] == "INFO"
