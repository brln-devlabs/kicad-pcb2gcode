import pytest

from kicad_pcb2gcode.millproject import Inputs, build_options, mill_diameters, render, validate
from kicad_pcb2gcode.settings import Settings

ALL = Inputs(front="cam/front.gbr", back="cam/back.gbr", drill="cam/drill.drl", outline="cam/outline.gbr")


def options(settings=None, inputs=ALL):
    return dict(build_options(settings or Settings(), inputs, "board"))


# The pcb2gcodeGUI configuration the defaults are taken from (Common, Mill,
# Drill and Outline sections; the autoleveller is not used with GRBL).
PCB2GCODEGUI_CONFIG = """
metric=true
metricoutput=true
nog64=true
tolerance=0.0100
zchange=10.0000
zsafe=5.0000
mill-diameters=0.154
mill-feed=1200
mill-speed=24000
offset=0.1000
zwork=-0.2500
drill-feed=300
drill-speed=24000
nog81=true
onedrill=true
zdrill=-2.5000
bridges=0.5000
cut-feed=800
cut-infeed=2.5000
cut-speed=24000
cut-vertfeed=60
cutter-diameter=1.5000
zbridges=-0.6000
zcut=-2.5000
"""
# zero-start=true: replaced by exact x-offset/y-offset on the board outline
# isolation-width=2.0000: 1 mm here - with copper pours 2 mm mills hardly more but takes far longer


def test_defaults_match_the_pcb2gcodegui_config():
    opts = options()
    for line in PCB2GCODEGUI_CONFIG.strip().splitlines():
        key, value = line.split("=")
        assert key in opts, key
        if value in ("true", "false"):
            assert opts[key] == value, key
        else:
            assert float(opts[key]) == float(value), (key, opts[key])
    # values the config left to pcb2gcode's defaults, written explicitly here
    assert opts["mill-vertfeed"] == "600"  # pcb2gcode: half the feed rate
    assert opts["milling-overlap"] == "50%"
    assert opts["bridgesnum"] == "2"
    assert float(opts["isolation-width"]) == 1.0


def test_defaults_are_grbl_safe():
    opts = options()
    for key in ("nog64", "nog81", "nom6"):  # GRBL knows neither G64, G81 nor M6
        assert opts[key] == "true", key
    assert "nog91-1" not in opts  # GRBL understands G91.1
    assert opts["output-dir"] == "."
    assert opts["basename"] == "board"


def test_inputs():
    opts = options()
    assert opts["front"] == "cam/front.gbr"
    assert opts["back"] == "cam/back.gbr"
    assert opts["drill"] == "cam/drill.drl"
    assert opts["outline"] == "cam/outline.gbr"
    assert opts["fill-outline"] == "true"


def test_offset_and_tolerance_can_be_switched_off():
    s = Settings()
    s.isolation.offset = 0
    s.machine.tolerance = 0
    opts = options(s)
    assert "offset" not in opts and "tolerance" not in opts


def test_sections_are_omitted_without_inputs():
    opts = options(inputs=Inputs(back="cam/back.gbr"))
    assert "back" in opts and "front" not in opts
    for key in ("drill", "zdrill", "outline", "zcut", "bridgesnum"):
        assert key not in opts
    opts = options(inputs=Inputs(drill="cam/drill.drl"))
    for key in ("zwork", "mill-diameters", "mill-feed"):
        assert key not in opts


def test_single_pass():
    s = Settings()
    s.isolation.isolation_width = 0
    opts = options(s)
    assert opts["mill-diameters"] == "0.154"
    assert "isolation-width" not in opts
    assert "milling-overlap" not in opts


def test_several_mill_diameters_and_length_overlap():
    s = Settings()
    s.isolation.mill_diameters = "0.15, 0.4mm"
    s.isolation.isolation_width = 0
    s.isolation.milling_overlap = "0,05 mm"
    opts = options(s)
    assert mill_diameters(s) == [0.15, 0.4]
    assert opts["mill-diameters"] == "0.15,0.4"
    assert opts["milling-overlap"] == "0.05mm"  # several tools need the overlap


def test_thermal_reliefs_only_matter_with_voronoi():
    s = Settings()
    s.isolation.preserve_thermal_reliefs = False
    assert "preserve-thermal-reliefs" not in options(s)
    s.isolation.voronoi = True
    assert options(s)["preserve-thermal-reliefs"] == "false"


def test_optional_drill_options():
    s = Settings()
    s.drill.drills_available = "0.8; 1.0 1.2mm"
    s.drill.milldrill = True
    s.drill.drill_side = "back"
    opts = options(s)
    assert opts["drills-available"] == "0.8,1,1.2"
    assert opts["milldrill-diameter"] == "3"
    assert opts["min-milldrill-hole-diameter"] == "3"
    assert opts["zmilldrill"] == "-2.5"
    assert opts["drill-side"] == "back"
    assert opts["onedrill"] == "true"


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
        (lambda s: setattr(s.isolation, "mill_diameters", ""), "mill_diameters_invalid"),
        (lambda s: setattr(s.isolation, "mill_diameters", "0.15, x"), "mill_diameters_invalid"),
        (lambda s: setattr(s.isolation, "milling_overlap", "100%"), "overlap_invalid"),
        (lambda s: setattr(s.drill, "zdrill", 1), "zdrill_negative"),
        (lambda s: setattr(s.drill, "drills_available", "x"), "drills_available_invalid"),
        (lambda s: setattr(s.outline, "zcut", 0), "zcut_negative"),
        (lambda s: setattr(s.outline, "zbridges", -5), "bridges_invalid"),
        (lambda s: setattr(s.outline, "cut_infeed", 0), "infeed_positive"),
        (lambda s: setattr(s.isolation, "offset", -0.1), "offset_range"),
        (lambda s: setattr(s.machine, "tolerance", -1), "tolerance_range"),
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
