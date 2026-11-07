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
