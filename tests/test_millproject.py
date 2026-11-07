import pytest

from kicad_pcb2gcode.millproject import Inputs, build_options, mill_diameter, render, validate
from kicad_pcb2gcode.settings import Settings

ALL = Inputs(front="cam/front.gbr", back="cam/back.gbr", drill="cam/drill.drl", outline="cam/outline.gbr")


def options(settings=None, inputs=ALL):
    return dict(build_options(settings or Settings(), inputs, "board"))


def test_defaults_are_grbl_safe():
    opts = options()
    assert opts["metric"] == "true"
    assert opts["metricoutput"] == "true"
    for key in ("nog64", "nog81", "nog91-1", "nom6"):
        assert opts[key] == "true", key
    assert opts["output-dir"] == "."
    assert opts["basename"] == "board"


def test_inputs_and_sections():
    opts = options()
    assert opts["front"] == "cam/front.gbr"
    assert opts["back"] == "cam/back.gbr"
    assert opts["drill"] == "cam/drill.drl"
    assert opts["outline"] == "cam/outline.gbr"
    assert opts["zwork"] == "-0.08"
    assert opts["mill-diameters"] == "0.14287"  # 30° V-bit, 0.1 tip, 0.08 deep
    assert opts["isolation-width"] == "0.3"
    assert opts["milling-overlap"] == "20%"
    assert opts["fill-outline"] == "true"
    assert opts["bridgesnum"] == "4"
    assert opts["zbridges"] == "-1"


def test_sections_are_omitted_without_inputs():
    opts = options(inputs=Inputs(back="cam/back.gbr"))
    assert "back" in opts and "front" not in opts
    for key in ("drill", "zdrill", "outline", "zcut", "bridgesnum"):
        assert key not in opts
    opts = options(inputs=Inputs(drill="cam/drill.drl"))
    for key in ("zwork", "mill-diameters", "mill-feed"):
        assert key not in opts


def test_end_mill_and_single_pass():
    s = Settings()
    s.isolation.tool_type = "endmill"
    s.isolation.mill_diameter = 0.2
    s.isolation.isolation_width = 0
    opts = options(s)
    assert opts["mill-diameters"] == "0.2"
    assert "isolation-width" not in opts
    assert "milling-overlap" not in opts
    assert mill_diameter(s) == 0.2


def test_optional_drill_options():
    s = Settings()
    s.drill.drills_available = "0.8; 1.0 1.2mm"
    s.drill.milldrill = True
    s.drill.drill_side = "back"
    opts = options(s)
    assert opts["drills-available"] == "0.8,1,1.2"
    assert opts["milldrill-diameter"] == "1"
    assert opts["min-milldrill-hole-diameter"] == "1.5"
    assert opts["drill-side"] == "back"
    assert "onedrill" not in opts


def test_no_tabs():
    s = Settings()
    s.outline.bridgesnum = 0
    opts = options(s)
    assert opts["bridgesnum"] == "0"
    assert "bridges" not in opts and "zbridges" not in opts


def test_switched_off_flags_are_not_written():
    # older pcb2gcode versions reject unknown options even when set to false
    s = Settings()
    s.machine.nom6 = False
    s.general.zero_start = False
    opts = options(s)
    assert "nom6" not in opts
    assert "zero-start" not in opts
    assert "voronoi" not in opts
    s.isolation.voronoi = True
    assert options(s)["voronoi"] == "true"


def test_render_and_extra_options_override():
    s = Settings()
    s.machine.extra_options = "# comment\n\nzsafe=5\n--spinup-time=3\nvoronoi\nspinup-time=4\n"
    text = render(s, ALL, "board")
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    keys = [line.split("=", 1)[0] for line in lines]
    assert len(keys) == len(set(keys)), "pcb2gcode rejects duplicate options"
    assert "zsafe=5" in lines
    assert "voronoi=true" in lines
    assert "spinup-time=4" in lines
    assert text.endswith("\n")


def test_validate_accepts_defaults():
    assert validate(Settings(), ALL) == []


@pytest.mark.parametrize(
    "mutate, problem",
    [
        (lambda s: setattr(s.isolation, "zwork", 0.1), "zwork_negative"),
        (lambda s: setattr(s.general, "zsafe", 0), "zsafe_positive"),
        (lambda s: setattr(s.isolation, "vbit_angle", 0), "vbit_invalid"),
        (lambda s: setattr(s.isolation, "milling_overlap", 100), "overlap_range"),
        (lambda s: setattr(s.drill, "zdrill", 1), "zdrill_negative"),
        (lambda s: setattr(s.drill, "drills_available", "x"), "drills_available_invalid"),
        (lambda s: setattr(s.outline, "zcut", 0), "zcut_negative"),
        (lambda s: setattr(s.outline, "zbridges", -5), "bridges_invalid"),
        (lambda s: setattr(s.outline, "cut_infeed", 0), "infeed_positive"),
    ],
)
def test_validate_reports_problems(mutate, problem):
    s = Settings()
    mutate(s)
    assert problem in validate(s, ALL)


def test_validate_nothing_to_do():
    assert validate(Settings(), Inputs()) == ["nothing_to_do"]


def test_validate_ignores_unused_sections():
    s = Settings()
    s.outline.zcut = 1  # invalid, but no outline is cut
    assert validate(s, Inputs(back="cam/back.gbr")) == []
