import json
import logging

import pytest

from forca import main as m


@pytest.fixture
def clean_logging():
    """Devolve a raiz do logging ao que era depois do teste."""
    root = logging.getLogger()
    before, level = list(root.handlers), root.level
    yield root
    for h in list(root.handlers):
        if h not in before:
            root.removeHandler(h)
            h.close()
    root.setLevel(level)


def config_file(tmp_path, **data):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


# --- argumentos e precedência ---


def test_parse_args_defaults_and_flags():
    a = m.parse_args([])
    assert (a.config, a.log_level, a.name, a.listen_port) == ("config.json", "INFO", None, None)
    a = m.parse_args(["--name", "bob", "--namespace", "X", "--port", "9000", "--rdv-host", "h",
                      "--rdv-port", "1", "--log-file", "x.log", "--log-level", "debug"])
    assert (a.name, a.namespace, a.listen_port, a.rdv_host, a.rdv_port, a.log_file, a.log_level) == (
        "bob", "X", 9000, "h", 1, "x.log", "DEBUG")


def test_invalid_log_level_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        m.parse_args(["--log-level", "LOUD"])
    assert exc.value.code == 2 and "nível inválido" in capsys.readouterr().err


def test_command_line_beats_config_file_beats_default(tmp_path):
    path = config_file(tmp_path, name="fromfile", listen_port=9999, namespace="FILE")
    cfg = m.build_config(m.parse_args(["--config", path, "--name", "cli"]))
    assert cfg.name == "cli"  # linha de comando
    assert cfg.listen_port == 9999 and cfg.namespace == "FILE"  # arquivo
    assert cfg.rdv_port == 8080 and cfg.lives == 6  # padrão


@pytest.mark.parametrize("port", ["0", "70000", "-1"])
def test_invalid_port_is_a_clear_error(port):
    with pytest.raises(ValueError, match="listen_port"):
        m.build_config(m.parse_args(["--config", "/nonexistent.json", "--port", port]))


def test_unknown_key_in_config_file_is_a_clear_error(tmp_path):
    path = config_file(tmp_path, nome="typo")
    with pytest.raises(ValueError, match="unknown config keys"):
        m.build_config(m.parse_args(["--config", path]))


# --- logging: tela x arquivo ---


def test_screen_shows_info_and_file_gets_everything(clean_logging, tmp_path, capsys):
    logfile = tmp_path / "logs" / "alice.log"  # a pasta é criada
    m.setup_logging("INFO")
    m.add_log_file(str(logfile))
    logging.getLogger("KeepAlive").debug("raw-debug-line")
    logging.getLogger("Wire").debug('-> {"type":"PING"}')
    logging.getLogger("KeepAlive").info("info-line")
    out = capsys.readouterr().out
    assert "info-line" in out and "raw-debug-line" not in out and "PING" not in out
    text = logfile.read_text(encoding="utf-8")
    assert "raw-debug-line" in text and '-> {"type":"PING"}' in text and "info-line" in text


def test_cli_and_game_always_reach_the_screen(clean_logging, capsys):
    m.setup_logging("ERROR")
    logging.getLogger("CLI").debug("cli-debug")
    logging.getLogger("Game").info("game-info")
    logging.getLogger("Host").info("host-info")
    out = capsys.readouterr().out
    assert "cli-debug" in out and "game-info" in out and "host-info" not in out


def test_set_level_at_runtime_shows_debug_without_restart(clean_logging, capsys):
    screen = m.setup_logging("INFO")
    logging.getLogger("PeerTable").debug("before")
    screen.set_level("debug")
    logging.getLogger("PeerTable").debug("after")
    out = capsys.readouterr().out
    assert "before" not in out and "after" in out
    with pytest.raises(ValueError):
        screen.set_level("LOUD")


def test_log_format_has_time_level_and_module(clean_logging, capsys):
    m.setup_logging("INFO")
    logging.getLogger("RDV").info("registered")
    line = capsys.readouterr().out.strip()
    assert line.endswith("INFO    [RDV] registered") and line[4] == "-"  # 2026-11-17 ...


# --- main(): erros viram mensagem, não traceback ---


def test_bad_config_exits_2_with_a_message_and_no_traceback(clean_logging, tmp_path, capsys):
    bad = tmp_path / "config.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        m.main(["--config", str(bad)])
    out = capsys.readouterr().out
    assert exc.value.code == 2 and "configuração inválida" in out and "Traceback" not in out


def test_unwritable_log_file_exits_2(clean_logging, tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(SystemExit) as exc:
        m.main(["--config", "/nonexistent.json", "--log-file", str(blocker / "sub" / "a.log")])
    assert exc.value.code == 2 and "Traceback" not in capsys.readouterr().out


# --- run(): ordem e encerramento ---


def fake_classes(calls, cli_fails=False):
    class FakeClient:
        def __init__(self, cfg): calls.append("init")
        async def start(self): calls.append("start")
        async def stop(self): calls.append("stop")

    class FakeCLI:
        def __init__(self, client, set_level): pass
        def request_quit(self): calls.append("quit")
        async def run(self):
            calls.append("cli")
            if cli_fails:
                raise RuntimeError("boom")

    return FakeClient, FakeCLI


async def test_run_starts_runs_and_stops(clean_logging, monkeypatch):
    calls = []
    monkeypatch.setattr(m, "P2PClient", fake_classes(calls)[0])
    monkeypatch.setattr(m, "CLI", fake_classes(calls)[1])
    cfg = m.build_config(m.parse_args(["--config", "/nonexistent.json"]))
    await m.run(cfg, m.ScreenFilter())
    assert calls == ["init", "start", "cli", "stop"]


async def test_run_stops_the_client_even_if_the_cli_fails(clean_logging, monkeypatch):
    calls = []
    client_cls, cli_cls = fake_classes(calls, cli_fails=True)
    monkeypatch.setattr(m, "P2PClient", client_cls)
    monkeypatch.setattr(m, "CLI", cli_cls)
    cfg = m.build_config(m.parse_args(["--config", "/nonexistent.json"]))
    with pytest.raises(RuntimeError):
        await m.run(cfg, m.ScreenFilter())
    assert calls == ["init", "start", "cli", "stop"]
