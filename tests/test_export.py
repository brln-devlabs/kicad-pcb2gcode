import os

from kicad_pcb2gcode.export import (
    drill_command,
    find_drill_file,
    find_pcb2gcode,
    gerber_command,
    gerbers_fallback_file,
)
from kicad_pcb2gcode.kicad_bridge import resolve_board_path


def test_gerber_command():
    cmd = gerber_command("kicad-cli", "b.kicad_pcb", "F.Cu", "out/front.gbr", False)
    assert cmd[:4] == ["kicad-cli", "pcb", "export", "gerber"]
    assert cmd[cmd.index("--output") + 1] == "out/front.gbr"
    assert cmd[cmd.index("--layers") + 1] == "F.Cu"
    assert "--no-x2" in cmd and "--no-netlist" in cmd
    assert "--use-drill-file-origin" not in cmd
    assert cmd[-1] == "b.kicad_pcb"
    assert "--use-drill-file-origin" in gerber_command("k", "b", "F.Cu", "o", True)


def test_drill_command():
    cmd = drill_command("kicad-cli", "b.kicad_pcb", "out", False)
    assert cmd[cmd.index("--excellon-units") + 1] == "mm"
    assert cmd[cmd.index("--drill-origin") + 1] == "absolute"
    assert cmd[cmd.index("--output") + 1].endswith(os.sep)
    assert drill_command("k", "b", "o", True)[-2] == "plot"


def test_fallback_file_name():
    assert gerbers_fallback_file("out", "/x/my.kicad_pcb", "Edge.Cuts") == os.path.join("out", "my-Edge_Cuts.gbr")


def test_find_drill_file(tmp_path):
    assert find_drill_file(str(tmp_path)) is None
    (tmp_path / "b-NPTH.drl").write_text("")
    assert find_drill_file(str(tmp_path)).endswith("b-NPTH.drl")
    (tmp_path / "b.drl").write_text("")
    assert find_drill_file(str(tmp_path)).endswith("b.drl")


def test_find_pcb2gcode_prefers_configured(tmp_path):
    exe = tmp_path / "pcb2gcode"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    assert find_pcb2gcode(str(exe)) == str(exe)


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_resolve_board_path_variants(tmp_path, monkeypatch):
    proj = str(tmp_path)
    doc = Obj(board_filename="b.kicad_pcb", project=Obj(path=proj))
    assert resolve_board_path(Obj(document=doc)) == os.path.join(proj, "b.kicad_pcb")

    doc = Obj(board_filename="b.kicad_pcb", project=Obj(path=os.path.join(proj, "b.kicad_pro")))
    assert resolve_board_path(Obj(document=doc)) == os.path.join(proj, "b.kicad_pcb")

    absolute = os.path.join(proj, "x.kicad_pcb")
    assert resolve_board_path(Obj(document=Obj(board_filename=absolute, project=None))) == absolute

    monkeypatch.setenv("KIPRJMOD", proj)
    (tmp_path / "only.kicad_pcb").write_text("")
    assert resolve_board_path(Obj(document=Obj(board_filename="", project=None))) == os.path.join(proj, "only.kicad_pcb")
