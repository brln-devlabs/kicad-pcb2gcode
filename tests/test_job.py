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
    assert names == ["my_board_back.ngc", "my_board_drill.ngc", "my_board_mask_back.ngc",
                     "my_board_mask_front.ngc", "my_board_outline.ngc"]
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
    assert [os.path.basename(f) for f in result.files] == [
        "my_board_back.ngc", "my_board_mask_back.ngc", "my_board_mask_front.ngc"]


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


def test_exports_use_the_drill_origin_by_default(board, tmp_path, monkeypatch):
    calls = tmp_path / "calls.txt"
    monkeypatch.setenv("FAKE_CLI_LOG", str(calls))
    run_job(request(board), lambda line: None)
    lines = calls.read_text().splitlines()
    gerbers = [line for line in lines if line.startswith("pcb export gerber ")]
    assert gerbers and all("--use-drill-file-origin" in line for line in gerbers)
    assert any("--drill-origin plot" in line for line in lines)


def test_drill_origin_can_be_switched_off(board, tmp_path, monkeypatch):
    calls = tmp_path / "calls.txt"
    monkeypatch.setenv("FAKE_CLI_LOG", str(calls))
    s = Settings()
    s.general.use_aux_origin = False
    run_job(request(board, s), lambda line: None)
    text = calls.read_text()
    assert "--use-drill-file-origin" not in text
    assert "--drill-origin absolute" in text


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
    assert names == ["my_board_back.ngc", "my_board_drill.ngc", "my_board_front.ngc",
                     "my_board_mask_back.ngc", "my_board_mask_front.ngc", "my_board_outline.ngc"]
    millproject = open(result.millproject_path).read()
    assert "outline=cam/outline.gbr" in millproject
    assert "cut-side=front" in millproject  # cut out first, top side up
    assert "drill-side=front" in millproject
    assert "x-offset=0" in millproject and "mirror-axis=5" in millproject  # fake outline 10 x 10 mm
    steps = open(os.path.join(result.output_dir, "STEPS.txt")).read().splitlines()
    order = [line.split(".", 1)[1].strip() for line in steps if line.strip()[:2].rstrip(".").isdigit()]
    assert order[0] == "my_board_outline.ngc  (cut the outline, top side up - before the flip frame)"
    assert order[1].startswith("Put the board (10.00 x 10.00 mm) into the frame, top side up")
    assert order[2].startswith("my_board_front.ngc")
    assert order[3].startswith("my_board_drill.ngc")
    assert order[4].startswith("Turn the board over left/right")
    assert order[5].startswith("my_board_back.ngc")
    assert order[6].startswith("Apply and cure the solder mask") and "(bottom up)" in order[6]
    assert order[7].startswith("my_board_mask_back.ngc")
    assert order[8].startswith("Turn the board over left/right")
    assert order[9].startswith("my_board_mask_front.ngc")
    assert len(order) == 10
    assert any("Board outline: 10.000 x 10.000 mm" in line for line in log)
    assert any("outline is cut first, from the top" in line for line in log)


def test_flip_frame_outline_is_cut_from_the_top(board):
    s = Settings()
    s.general.frame_mode = True
    s.general.sides = "both"
    s.outline.cut_side = "back"  # ignored in the frame
    s.mask.enabled = False
    result = run_job(request(board, s), lambda line: None)
    assert "cut-side=front" in open(result.millproject_path).read()


def test_flip_frame_without_outline_cut(board):
    s = Settings()
    s.general.frame_mode = True
    s.general.export_outline = False
    result = run_job(request(board, s), lambda line: None)
    millproject = open(result.millproject_path).read()
    assert "outline=" not in millproject and "x-offset=" in millproject
    assert not any(f.endswith("_outline.ngc") for f in result.files)
    steps = open(os.path.join(result.output_dir, "STEPS.txt")).read()
    assert "Blank 10.00 x 10.00 mm in the frame" in steps


def test_outline_defines_origin_even_when_not_cut(board):
    s = Settings()
    s.general.export_outline = False
    result = run_job(request(board, s), lambda line: None)
    millproject = open(result.millproject_path).read()
    assert "x-offset=" in millproject and "outline=" not in millproject


def read_options(path):
    opts = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            opts[key] = value
    return opts


def test_solder_mask_run(board):
    result = run_job(request(board), lambda line: None)
    copper = read_options(result.millproject_path)
    mask = read_options(os.path.join(result.output_dir, "millproject_mask"))
    assert mask["invert-gerbers"] == "true"
    assert mask["eulerian-paths"] == "false"  # no gain for the rings, but most of the run time
    assert mask["front"] == "cam/mask_front.gbr" and mask["back"] == "cam/mask_back.gbr"
    assert mask["basename"] == "my_board_mask"
    assert mask["zwork"] == "-0.03" and mask["mill-diameters"] == "0.1"
    assert "offset" not in mask and "voronoi" not in mask
    for key in ("drill", "outline", "zdrill", "zcut"):
        assert key not in mask
    for key in ("x-offset", "y-offset", "mirror-axis", "zsafe", "nog64", "nom6"):  # same placement and dialect
        assert mask[key] == copper[key], key
    assert "invert-gerbers" not in copper and "eulerian-paths" not in copper


def test_solder_mask_can_be_switched_off(board):
    s = Settings()
    s.mask.enabled = False
    result = run_job(request(board, s), lambda line: None)
    assert not any("mask" in os.path.basename(f) for f in result.files)
    assert not os.path.exists(os.path.join(result.output_dir, "millproject_mask"))


def test_mask_without_openings_is_skipped(board):
    with open(board, "w") as fh:
        fh.write("(kicad_pcb NO_MASK_OPENINGS)")
    log = []
    result = run_job(request(board), log.append)
    assert result.mask_inputs is None
    assert any("F.Mask has no openings" in line for line in log)


def test_invalid_mask_settings_are_reported_as_such(board):
    s = Settings()
    s.mask.zwork = 0.1
    with pytest.raises(JobError, match="Solder mask: Milling depth must be below zero"):
        run_job(request(board, s), lambda line: None)


class OriginSession:
    def __init__(self, answer):
        self.answer = answer

    def drill_origin_set(self):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def save_copy(self, target):
        return False


def test_drill_origin_from_kicad_or_board_file(board):
    ctx = BoardContext(board_path=board)
    assert ctx.drill_origin_set() is False  # board file without aux_axis_origin
    with open(board, "w") as fh:
        fh.write("(kicad_pcb (setup (aux_axis_origin 50 60)))")
    assert ctx.drill_origin_set() is True
    # the running KiCad wins over the saved file (unsaved changes) ...
    assert BoardContext(board_path=board, session=OriginSession(False)).drill_origin_set() is False
    # ... unless the API cannot answer
    assert BoardContext(board_path=board, session=OriginSession(None)).drill_origin_set() is True
    assert BoardContext(board_path=board, session=OriginSession(RuntimeError())).drill_origin_set() is True
    assert BoardContext(board_path=board + ".missing").drill_origin_set() is None


def test_unset_drill_origin_is_noted_in_the_log(board):
    ctx = BoardContext(board_path=board, kicad_cli=fake("kicad-cli"))
    cfg = AppConfig(pcb2gcode_path=fake("pcb2gcode"))
    log = []
    generate(ctx, Settings(), cfg, log.append)
    assert any("drill/place file origin is not set" in line for line in log)
    assert not any("sheet corner" in line for line in log)  # irrelevant with the board corner at X0/Y0
    s = Settings()
    s.general.use_aux_origin = True
    s.general.zero_start = False
    log = []
    generate(ctx, s, cfg, log.append)
    assert any("measured from the sheet corner" in line for line in log)


def run_with_holes(board, mode):
    s = Settings()
    s.drill.holes = mode
    s.mask.enabled = False
    return run_job(request(board, s), lambda line: None)


def test_holes_merged_is_the_default(board):
    result = run_with_holes(board, "merged")
    assert result.inputs.drill == "cam/drill.drl" and result.npth_inputs is None
    assert Settings().drill.holes == "merged"


def test_holes_separate(board):
    result = run_with_holes(board, "separate")
    names = sorted(os.path.basename(f) for f in result.files)
    assert "my_board_drill.ngc" in names and "my_board_npth_drill.ngc" in names
    main = read_options(result.millproject_path)
    npth = read_options(os.path.join(result.output_dir, "millproject_npth"))
    assert main["drill"] == "cam/drill_pth.drl"
    assert npth["drill"] == "cam/drill_npth.drl" and npth["basename"] == "my_board_npth"
    for key in ("front", "back", "outline"):
        assert key not in npth
    for key in ("x-offset", "y-offset", "mirror-axis", "zdrill", "drill-feed"):  # same placement and tool
        assert npth[key] == main[key], key


def test_holes_pth_or_npth_only(board):
    pth = run_with_holes(board, "pth")
    assert pth.inputs.drill == "cam/drill_pth.drl" and pth.npth_inputs is None
    npth = run_with_holes(board, "npth")
    assert npth.inputs.drill == "cam/drill_npth.drl"
    assert not os.path.exists(os.path.join(npth.output_dir, "millproject_npth"))


def test_separate_without_npth_holes(board):
    with open(board, "w") as fh:
        fh.write("(kicad_pcb NO_NPTH)")
    result = run_with_holes(board, "separate")
    assert result.npth_inputs is None
    assert not any("npth" in os.path.basename(f) for f in result.files)


def test_flip_frame_with_separate_holes(board):
    s = Settings()
    s.general.frame_mode = True
    s.general.sides = "both"
    s.drill.holes = "separate"
    s.mask.enabled = False
    result = run_job(request(board, s), lambda line: None)
    steps = open(os.path.join(result.output_dir, "STEPS.txt")).read()
    assert steps.index("my_board_drill.ngc  (drill PTH)") < steps.index("my_board_npth_drill.ngc  (drill NPTH)")
    assert steps.index("my_board_npth_drill.ngc") < steps.index("Turn the board over")
    npth = read_options(os.path.join(result.output_dir, "millproject_npth"))
    assert npth["drill-side"] == "front"


def test_first_pause_is_kept_by_default(board):
    result = run_job(request(board), lambda line: None)
    text = open(result.files[0]).read()
    assert text.count("M0      (Temporary machine stop.)") == 2


def test_first_pause_can_be_removed(board):
    s = Settings()
    s.machine.skip_first_pause = True
    log = []
    result = run_job(request(board, s), log.append)
    for path in result.files:
        text = open(path).read()
        assert text.count("M0      (Temporary machine stop.)") == 1, path  # the later tool change keeps its pause
        assert "(M0 removed by kicad-pcb2gcode" in text
        assert text.index("(M0 removed") < text.index("T2")
        assert "M3 ( Spindle on clockwise. )" in text and "M5      (Spindle stop.)" in text
    assert any("Removed the pause at the start of {} file(s)".format(len(result.files)) in line for line in log)


def test_remove_first_pause_details(tmp_path):
    from kicad_pcb2gcode.job import remove_first_pause

    path = tmp_path / "a.ngc"
    path.write_bytes(b"(M0 in a comment does not count)\r\nM03 S1000\r\nM05\r\nM00 ; pause\r\nM0\r\n")
    assert remove_first_pause(str(path))
    lines = path.read_bytes().split(b"\r\n")
    assert lines[0] == b"(M0 in a comment does not count)"
    assert lines[1] == b"M03 S1000" and lines[2] == b"M05"
    assert lines[3].startswith(b"(M0 removed")
    assert lines[4] == b"M0"
    empty = tmp_path / "b.ngc"
    empty.write_text("G21\nM2\n")
    assert not remove_first_pause(str(empty))


def test_file_extension(board):
    s = Settings()
    s.general.file_extension = "nc"
    result = run_job(request(board, s), lambda line: None)
    assert result.files and all(f.endswith(".nc") for f in result.files)
    assert not [f for f in os.listdir(result.output_dir) if f.endswith(".ngc")]


def test_switching_extension_removes_old_files_of_this_board_only(board):
    out = os.path.join(os.path.dirname(board), "gcode")
    os.makedirs(out)
    for name in ("my_board_back.gcode", "my_board_drill.tap", "notes.txt", "other_board_back.nc"):
        open(os.path.join(out, name), "w").close()
    s = Settings()
    s.general.file_extension = "txt"
    result = run_job(request(board, s), lambda line: None)
    left = set(os.listdir(out))
    assert "my_board_back.gcode" not in left and "my_board_drill.tap" not in left
    assert {"notes.txt", "other_board_back.nc"} <= left
    assert "my_board_back.txt" in left and os.path.join(out, "my_board_back.txt") in result.files


def test_flip_frame_steps_use_the_chosen_extension(board):
    s = Settings()
    s.general.frame_mode = True
    s.general.sides = "both"
    s.general.file_extension = "gcode"
    s.mask.enabled = False
    result = run_job(request(board, s), lambda line: None)
    steps = open(os.path.join(result.output_dir, "STEPS.txt")).read()
    assert "my_board_front.gcode  (top side)" in steps and "my_board_back.gcode  (bottom side)" in steps


def test_unknown_extension_falls_back():
    s = Settings.from_dict({"general": {"file_extension": ".EXE"}})
    assert s.general.file_extension == "ngc"
    assert Settings.from_dict({"general": {"file_extension": ".NC"}}).general.file_extension == "nc"


def test_previews_after_a_run(board, monkeypatch):
    from kicad_pcb2gcode.preview import list_previews

    monkeypatch.setenv("FAKE_CONTENTIONS", "1")
    result = run_job(request(board), lambda line: None)
    labels = [label for label, _ in list_previews(result.output_dir)]
    assert labels[0].startswith("⚠")  # clearance problem first
    assert "Bottom side (B.Cu)" in labels and "Drill" in labels and "Outline" in labels
    assert "Solder mask top" in labels and "Solder mask bottom" in labels
    assert not [f for f in os.listdir(result.output_dir) if f.endswith(".svg")]


def test_log_shows_how_long_pcb2gcode_took(board):
    log = []
    run_job(request(board), log.append)
    assert any(line.startswith("  (pcb2gcode took ") for line in log)


def test_isolation_hint_for_copper_pours(tmp_path):
    from kicad_pcb2gcode.job import isolation_hint

    board = tmp_path / "b.kicad_pcb"
    board.write_text('(kicad_pcb (zone (net 1) (net_name "GND") (layer "B.Cu") (connect_pads (clearance 1))\n'
                     '  (polygon (pts (xy 0 0) (xy 1 0) (xy 1 1)))))\n')
    s = Settings()
    req = request(str(board), s)
    log = []
    isolation_hint(req, "both", log.append)
    assert len(log) == 1 and "copper pours on B.Cu leave gaps of 1 mm" in log[0]
    assert "isolation width of 2 mm" in log[0] and "0.5 to 1 mm" in log[0]
    log.clear()
    isolation_hint(req, "front", log.append)  # no pour on the milled side
    s.isolation.isolation_width = 1.0
    isolation_hint(request(str(board), s), "both", log.append)  # narrow enough
    assert log == []
