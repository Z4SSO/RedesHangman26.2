import json

import pytest

from forca.config import load_config


@pytest.mark.parametrize("bad", [0, -1, 30.5, True, "30", None])
def test_turn_timeout_must_be_integer_at_least_one(bad, tmp_path):
    # None nas sobrescritas significa "não informado": vale o padrão, então não entra aqui.
    if bad is None:
        assert load_config(None, {"turn_timeout": None}).turn_timeout == 30
        return
    with pytest.raises(ValueError, match="turn_timeout"):
        load_config(None, {"turn_timeout": bad})
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"turn_timeout": bad}), encoding="utf-8")
    with pytest.raises(ValueError, match="turn_timeout"):
        load_config(path)


def test_valid_turn_timeout_passes(tmp_path):
    assert load_config(None).turn_timeout == 30
    assert load_config(None, {"turn_timeout": 1}).turn_timeout == 1
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"turn_timeout": 45}), encoding="utf-8")
    assert load_config(path).turn_timeout == 45
