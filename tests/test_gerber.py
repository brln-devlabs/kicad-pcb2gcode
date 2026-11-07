import pytest

from kicad_pcb2gcode.gerber import LayerStats, choose_sides, drill_hits, layer_stats

TRACES = """%TF.GenerationSoftware,KiCad,Pcbnew,9.0.0*%
%FSLAX46Y46*%
%MOMM*%
G04 Aperture D01 in a comment must not count*
%ADD10C,0.250000*%
%ADD11R,1.700000X1.700000*%
D10*
X100000000Y-50000000D02*
X120000000Y-50000000D01*
X130000000Y-60000000D01*
D11*
X100000000Y-50000000D03*
X130000000Y-60000000D03*
M02*
"""

PADS_ONLY = """%FSLAX46Y46*%
%MOMM*%
%ADD11C,1.700000*%
D11*
X100000000Y-50000000D03*
X130000000Y-60000000D03*
M02*
"""

DRILL = """M48
; DRILL file {KiCad 9.0.0}
FMAT,2
METRIC
T1C0.800
T2C1.000
%
G90
G05
T1
X100.0Y-50.0
X130.0Y-60.0
T2
X110.0Y-55.0
G85X120.0Y-55.0
M30
"""

DRILL_EMPTY = """M48
METRIC
%
G90
G05
M30
"""


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


def test_layer_stats_counts_draws_and_flashes(tmp_path):
    stats = layer_stats(write(tmp_path, "f.gbr", TRACES))
    assert stats == LayerStats(draws=2, flashes=2)
    assert not stats.empty


def test_layer_stats_pads_only(tmp_path):
    assert layer_stats(write(tmp_path, "b.gbr", PADS_ONLY)) == LayerStats(draws=0, flashes=2)


def test_layer_stats_missing_file(tmp_path):
    assert layer_stats(str(tmp_path / "nope.gbr")).empty


def test_drill_hits(tmp_path):
    assert drill_hits(write(tmp_path, "a.drl", DRILL)) == 4
    assert drill_hits(write(tmp_path, "b.drl", DRILL_EMPTY)) == 0


def test_choose_sides():
    traces, pads, empty = LayerStats(5, 3), LayerStats(0, 3), LayerStats()
    assert choose_sides(traces, traces) == "both"
    assert choose_sides(traces, pads) == "front"
    assert choose_sides(pads, traces) == "back"
    assert choose_sides(pads, pads) == "back"  # THT pads only: classic bottom-side board
    assert choose_sides(pads, empty) == "front"
    assert choose_sides(empty, empty) == "back"


def _mm(v):
    return str(int(round(v * 1e6)))


def rounded_rect(x0, y0, x1, y1, r):
    lines = ["%TF.FileFunction,Profile,NP*%", "%FSLAX46Y46*%", "G04 Gerber Fmt 4.6*", "%MOMM*%",
             "%LPD*%", "G01*", "%ADD10C,0.100000*%", "D10*", "G75*",
             "X{}Y{}D02*".format(_mm(x0 + r), _mm(y0)), "X{}Y{}D01*".format(_mm(x1 - r), _mm(y0)),
             "G03*", "X{}Y{}I0J{}D01*".format(_mm(x1), _mm(y0 + r), _mm(r)), "G01*",
             "X{}Y{}D01*".format(_mm(x1), _mm(y1 - r)),
             "G03*", "X{}Y{}I{}J0D01*".format(_mm(x1 - r), _mm(y1), _mm(-r)), "G01*",
             "X{}Y{}D01*".format(_mm(x0 + r), _mm(y1)),
             "G03*", "X{}Y{}I0J{}D01*".format(_mm(x0), _mm(y1 - r), _mm(-r)), "G01*",
             "X{}Y{}D01*".format(_mm(x0), _mm(y0 + r)),
             "G03*", "X{}Y{}I{}J0D01*".format(_mm(x0 + r), _mm(y0), _mm(r)), "G01*", "M02*"]
    return "\n".join(lines) + "\n"


def test_outline_box_rounded_rectangle(tmp_path):
    from kicad_pcb2gcode.gerber import outline_box

    box = outline_box(write(tmp_path, "o.gbr", rounded_rect(100, -80, 140, -50, 2)))
    assert (box.min_x, box.min_y, box.max_x, box.max_y) == (100, -80, 140, -50)
    assert (box.width, box.height) == (40, 30)


def test_outline_box_circle_and_bulging_arc(tmp_path):
    from kicad_pcb2gcode.gerber import outline_box

    circle = "%FSLAX46Y46*%\n%MOMM*%\nG75*\nX10000000Y0D02*\nG02*\nX10000000Y0I-10000000J0D01*\nM02*\n"
    box = outline_box(write(tmp_path, "c.gbr", circle))
    assert (box.min_x, box.min_y, box.max_x, box.max_y) == pytest.approx((-10, -10, 10, 10))
    # quarter arc from (10,0) counter-clockwise to (0,10) bulges to x=10,y=10 only
    quarter = "%FSLAX46Y46*%\n%MOMM*%\nG75*\nX10000000Y0D02*\nG03*\nX0Y10000000I-10000000J0D01*\nM02*\n"
    box = outline_box(write(tmp_path, "q.gbr", quarter))
    assert (box.min_x, box.min_y, box.max_x, box.max_y) == pytest.approx((0, 0, 10, 10))
    # the same arc clockwise goes the long way round
    long_way = quarter.replace("G03", "G02")
    box = outline_box(write(tmp_path, "l.gbr", long_way))
    assert (box.min_x, box.min_y, box.max_x, box.max_y) == pytest.approx((-10, -10, 10, 10))


def test_outline_box_inch_and_empty(tmp_path):
    from kicad_pcb2gcode.gerber import outline_box

    inch = "%FSLAX25Y25*%\n%MOIN*%\nX0Y0D02*\nX100000Y50000D01*\nM02*\n"
    box = outline_box(write(tmp_path, "i.gbr", inch))
    assert (box.width, box.height) == pytest.approx((25.4, 12.7))
    assert outline_box(write(tmp_path, "e.gbr", PADS_ONLY.replace("D03", "D02"))) is None
    assert outline_box(str(tmp_path / "missing.gbr")) is None
