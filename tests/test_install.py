"""scripts/install.py: finding KiCad's plugin folders (Linux layout)."""

import argparse
import importlib.util
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux folder layout")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def install(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "KICAD_DOCUMENTS_HOME"):
        monkeypatch.delenv(var, raising=False)
    spec = importlib.util.spec_from_file_location("install_script", os.path.join(ROOT, "scripts", "install.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def args(**kw):
    return argparse.Namespace(plugins_dir=kw.get("plugins_dir"), kicad_version=kw.get("kicad_version"))


def test_settings_folder_alone_is_enough(install, tmp_path):
    (tmp_path / ".config" / "kicad" / "9.0").mkdir(parents=True)
    assert install.targets(args()) == [str(tmp_path / ".local" / "share" / "kicad" / "9.0" / "plugins")]


def test_documents_folder_and_old_versions(install, tmp_path):
    (tmp_path / ".local" / "share" / "kicad" / "10.0").mkdir(parents=True)
    (tmp_path / ".config" / "kicad" / "8.0").mkdir(parents=True)  # too old
    (tmp_path / ".config" / "kicad" / "10.0").mkdir(parents=True)  # same version, no duplicate
    assert install.targets(args()) == [str(tmp_path / ".local" / "share" / "kicad" / "10.0" / "plugins")]


def test_flatpak(install, tmp_path):
    (tmp_path / ".var" / "app" / "org.kicad.KiCad" / "config" / "kicad" / "9.0").mkdir(parents=True)
    assert install.targets(args()) == [
        str(tmp_path / ".var" / "app" / "org.kicad.KiCad" / "data" / "kicad" / "9.0" / "plugins")]


def test_nothing_found_explains_what_was_searched(install, capsys):
    with pytest.raises(SystemExit) as err:
        install.targets(args())
    assert "Searched:" in str(err.value) and "--kicad-version" in str(err.value)


def test_explicit_version_without_any_folder(install, tmp_path):
    assert install.targets(args(kicad_version="9.0")) == [
        str(tmp_path / ".local" / "share" / "kicad" / "9.0" / "plugins")]
