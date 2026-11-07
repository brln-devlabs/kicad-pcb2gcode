"""End-to-end pipeline test with fake kicad-cli and pcb2gcode executables."""

import os
import stat
import sys

import pytest

from kicad_pcb2gcode.app import BoardContext, generate
from kicad_pcb2gcode.job import JobError, JobRequest, basename_for, run_job
from kicad_pcb2gcode.settings import AppConfig, Settings, board_settings_path

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="fake tools are POSIX scripts")

FAKES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakes")


def fake(name):
    path = os.path.join(FAKES, name)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def board(tmp_path):
    path = tmp_path / "proj" / "my board.kicad_pcb"
    path.parent.mkdir()
    path.write_text("(kicad_pcb)")
    return str(path)


def request(board, settings=None):
    return JobRequest(
        board_file=board,
        board_name="my board",
        output_dir=os.path.join(os.path.dirname(board), "gcode"),
        kicad_cli=fake("kicad-cli"),
        pcb2gcode=fake("pcb2gcode"),
        settings=settings or Settings(),
    )


def test_auto_sides_mill_the_side_with_traces(board):
    log = []
    result = run_job(request(board), log.append)
    assert result.sides == "back"
    assert result.inputs.back == "cam/back.gbr"
    assert result.inputs.front is None
    names = sorted(os.path.basename(f) for f in result.files)
    assert names == ["my_board_back.ngc", "my_board_drill.ngc", "my_board_outline.ngc"]
    millproject = open(result.millproject_path).read()
    assert "back=cam/back.gbr" in millproject
    assert "drill=cam/drill.drl" in millproject
    assert any("Processing back" in line for line in log)


def test_explicit_both_sides(board):
    s = Settings()
    s.general.sides = "both"
    result = run_job(request(board, s), lambda line: None)
    assert result.inputs.front and result.inputs.back


def test_skip_drill_and_outline(board):
    s = Settings()
    s.general.export_drill = False
    s.general.export_outline = False
    result = run_job(request(board, s), lambda line: None)
    assert [os.path.basename(f) for f in result.files] == ["my_board_back.ngc"]


def test_stale_gcode_is_removed(board):
    out = os.path.join(os.path.dirname(board), "gcode")
    os.makedirs(out)
    open(os.path.join(out, "old_front.ngc"), "w").close()
    result = run_job(request(board), lambda line: None)
    assert "old_front.ngc" not in [os.path.basename(f) for f in result.files]


def test_gerbers_fallback(board, monkeypatch):
    monkeypatch.setenv("FAKE_NO_SINGLE_GERBER", "1")
    result = run_job(request(board), lambda line: None)
    assert result.sides == "back"
    assert os.path.isfile(os.path.join(result.output_dir, "cam", "back.gbr"))


def test_aux_origin_reaches_kicad_cli(board, tmp_path, monkeypatch):
    calls = tmp_path / "calls.txt"
    monkeypatch.setenv("FAKE_CLI_LOG", str(calls))
    s = Settings()
    s.general.use_aux_origin = True
    run_job(request(board, s), lambda line: None)
    text = calls.read_text()
    assert "--use-drill-file-origin" in text
    assert "--drill-origin plot" in text


def test_pcb2gcode_failure_is_reported(board, monkeypatch):
    monkeypatch.setenv("FAKE_PCB2GCODE_FAIL", "1")
    log = []
    with pytest.raises(JobError) as err:
        run_job(request(board), log.append)
    assert "exit code 3" in str(err.value)
    assert any("simulated failure" in line for line in log)


def test_invalid_settings_stop_before_pcb2gcode(board):
    s = Settings()
    s.isolation.zwork = 0.5
    with pytest.raises(JobError) as err:
        run_job(request(board, s), lambda line: None)
    assert "below zero" in str(err.value)
    assert not os.path.exists(os.path.join(os.path.dirname(board), "gcode", "millproject"))


def test_missing_programs(board):
    req = request(board)
    req.pcb2gcode = ""
    with pytest.raises(JobError, match="pcb2gcode not found"):
        run_job(req, lambda line: None)


FOUR_LAYERS = '(kicad_pcb (layers (0 "F.Cu" signal) (4 "In1.Cu" signal) (6 "In2.Cu" signal) (2 "B.Cu" signal)) (setup)'


def test_inner_layers_with_copper_stop_the_job(board):
    with open(board, "w") as fh:
        fh.write(FOUR_LAYERS + " INNER_TRACES)")
    with pytest.raises(JobError) as err:
        run_job(request(board), lambda line: None)
    assert "4 copper layers" in str(err.value)
    assert "In1.Cu, In2.Cu" in str(err.value)
    assert "Mill outer layers only" in str(err.value)


def test_inner_layers_can_be_ignored_on_purpose(board):
    with open(board, "w") as fh:
        fh.write(FOUR_LAYERS + " INNER_TRACES)")
    s = Settings()
    s.general.outer_layers_only = True
    log = []
    result = run_job(request(board, s), log.append)
    assert result.files
    assert any("ignoring copper on In1.Cu, In2.Cu" in line for line in log)


def test_empty_inner_layers_only_give_a_note(board):
    with open(board, "w") as fh:
        fh.write(FOUR_LAYERS + ")")
    log = []
    assert run_job(request(board), log.append).files
    assert any("inner layers are empty" in line for line in log)


def test_blind_vias_stop_the_job(board):
    with open(board, "w") as fh:
        fh.write(FOUR_LAYERS + ' (via blind (at 0 0) (layers "F.Cu" "In1.Cu")))')
    s = Settings()
    s.general.outer_layers_only = True  # the override does not cover vias
    with pytest.raises(JobError, match="blind/buried vias"):
        run_job(request(board, s), lambda line: None)


def test_layer_pair_drill_files_stop_the_job(board):
    with open(board, "w") as fh:
        fh.write("(kicad_pcb LAYERPAIR_DRILL)")
    with pytest.raises(JobError) as err:
        run_job(request(board), lambda line: None)
    assert "my board-F_Cu-In1_Cu.drl" in str(err.value)


def test_basename_is_filesystem_safe(board):
    s = Settings()
    s.general.basename = "a/b c?"
    assert basename_for(request(board, s)) == "a_b_c"
    assert basename_for(request(board)) == "my_board"


def test_generate_saves_board_settings(board):
    ctx = BoardContext(board_path=board, kicad_cli=fake("kicad-cli"))
    cfg = AppConfig(pcb2gcode_path=fake("pcb2gcode"))
    s = Settings()
    s.isolation.zwork = -0.1
    result = generate(ctx, s, cfg, lambda line: None)
    assert result.files
    assert os.path.isfile(board_settings_path(board))


class FakeSession:
    def __init__(self, ok):
        self.ok = ok
        self.targets = []

    def save_copy(self, target):
        self.targets.append(target)
        if self.ok:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w") as fh:
                fh.write("(kicad_pcb)")
        return self.ok


def test_open_board_copy_is_exported(board):
    session = FakeSession(ok=True)
    ctx = BoardContext(board_path=board, kicad_cli=fake("kicad-cli"), session=session)
    log = []
    target = ctx.board_to_export(Settings(), log.append)
    assert target == session.targets[0]
    assert target.endswith(os.path.join("gcode", "cam", "my board.kicad_pcb"))


def test_falls_back_to_saved_board(board):
    ctx = BoardContext(board_path=board, kicad_cli=fake("kicad-cli"), session=FakeSession(ok=False))
    log = []
    assert ctx.board_to_export(Settings(), log.append) == board
    assert any("Save first" in line for line in log)


def test_unsaved_changes_can_be_switched_off(board):
    session = FakeSession(ok=True)
    s = Settings()
    s.general.include_unsaved = False
    ctx = BoardContext(board_path=board, session=session)
    assert ctx.board_to_export(s, lambda line: None) == board
    assert session.targets == []


def test_flip_frame(board):
    s = Settings()
    s.general.frame_mode = True
    s.general.sides = "both"
    log = []
    result = run_job(request(board, s), log.append)
    names = sorted(os.path.basename(f) for f in result.files)
    assert names == ["my_board_back.ngc", "my_board_drill.ngc", "my_board_front.ngc"]  # no outline
    millproject = open(result.millproject_path).read()
    assert "outline=" not in millproject
    assert "drill-side=front" in millproject
    assert "x-offset=0" in millproject and "mirror-axis=5" in millproject  # fake outline 10 x 10 mm
    steps = open(os.path.join(result.output_dir, "STEPS.txt")).read().splitlines()
    order = [line.split(".", 1)[1].strip() for line in steps if line.strip()[:2].rstrip(".").isdigit()]
    assert order[0].startswith("my_board_front.ngc")
    assert order[1].startswith("my_board_drill.ngc")
    assert order[2].startswith("Turn the board over left/right")
    assert order[3].startswith("my_board_back.ngc")
    assert any("Board outline: 10.000 x 10.000 mm" in line for line in log)


def test_outline_defines_origin_even_when_not_cut(board):
    s = Settings()
    s.general.export_outline = False
    result = run_job(request(board, s), lambda line: None)
    millproject = open(result.millproject_path).read()
    assert "x-offset=" in millproject and "outline=" not in millproject
