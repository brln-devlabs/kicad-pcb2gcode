import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugin"))

from kicad_pcb2gcode import i18n  # noqa: E402


@pytest.fixture(autouse=True)
def english_and_isolated_config(tmp_path, monkeypatch):
    """Deterministic language and a throw-away config directory for every test."""
    i18n.set_lang("en")
    monkeypatch.setenv("KICAD_PCB2GCODE_CONFIG_DIR", str(tmp_path / "config"))
    yield
