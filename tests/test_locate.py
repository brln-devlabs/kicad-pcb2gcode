"""Finding pcb2gcode outside the plugin's PATH: login shell, Flatpak host."""

import os
import stat
import sys

import pytest

from kicad_pcb2gcode import export
from kicad_pcb2gcode.export import locate_pcb2gcode
from kicad_pcb2gcode.job import JobRequest, pcb2gcode_command, pcb2gcode_missing_message
from kicad_pcb2gcode.settings import Settings

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shells")


def script(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Nothing on PATH and none of the usual places exist."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.setattr(export, "pcb2gcode_candidates", lambda configured="": [configured] if configured else [])
    monkeypatch.setattr(export.os.path, "exists", lambda p, _real=os.path.exists: False if p == "/.flatpak-info" else _real(p))
    return tmp_path


def test_found_through_the_login_shell(isolated, monkeypatch):
    target = script(isolated / "pcb2gcode", "echo 3.1.0\n")
    shell = script(isolated / "fakeshell", 'echo "welcome banner"\necho "{}"\n'.format(target))
    monkeypatch.setenv("SHELL", shell)
    located = locate_pcb2gcode()
    assert located.path == target and not located.host


def test_found_on_the_flatpak_host(isolated, monkeypatch):
    monkeypatch.setenv("FLATPAK_ID", "org.kicad.KiCad")
    bindir = isolated / "bin"
    bindir.mkdir()
    script(bindir / "flatpak-spawn", 'echo "/usr/local/bin/pcb2gcode"\n')
    monkeypatch.setenv("PATH", str(bindir))
    located = locate_pcb2gcode()
    assert located.path == "/usr/local/bin/pcb2gcode" and located.host
    assert located.command("/out", "--config", "x") == [
        "flatpak-spawn", "--host", "--directory=/out", "/usr/local/bin/pcb2gcode", "--config", "x"]


def test_not_found(isolated, monkeypatch):
    monkeypatch.setenv("SHELL", script(isolated / "fakeshell", "exit 1\n"))
    located = locate_pcb2gcode("/nowhere/pcb2gcode")
    assert located.path is None and located.searched == ["/nowhere/pcb2gcode"]
    text = pcb2gcode_missing_message(located.searched)
    assert "pcb2gcode not found." in text and "/nowhere/pcb2gcode" in text and "command -v pcb2gcode" in text


def test_missing_message_in_flatpak(monkeypatch):
    monkeypatch.setenv("FLATPAK_ID", "org.kicad.KiCad")
    assert "flatpak override --user --talk-name=org.freedesktop.Flatpak org.kicad.KiCad" in pcb2gcode_missing_message([])


def test_job_command():
    req = JobRequest(board_file="b", board_name="b", output_dir="/out", kicad_cli="k", pcb2gcode="/x/pcb2gcode",
                     settings=Settings())
    assert pcb2gcode_command(req, "--config", "m") == ["/x/pcb2gcode", "--config", "m"]
    req.pcb2gcode_host = True
    assert pcb2gcode_command(req)[:3] == ["flatpak-spawn", "--host", "--directory=/out"]
