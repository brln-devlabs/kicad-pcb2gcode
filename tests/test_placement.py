"""Origin and flip axis: checked against pcb2gcode's own coordinate formulas.

The two functions below transcribe how pcb2gcode turns input coordinates into
G-code coordinates (src/ngc_exporter.cpp for milling, src/drill.cpp for
drilling, single tile). The tests feed them the options this plugin writes and
check that a board turned over about its centre line lands exactly where the
top side was.
"""

import pytest

from kicad_pcb2gcode.gerber import Box
from kicad_pcb2gcode.millproject import Inputs, build_options, placement_options, validate
from kicad_pcb2gcode.settings import Settings

BOX = Box(100.0, -80.0, 140.0, -50.0)  # 40 x 30 mm, KiCad-like coordinates


def opts_for(settings, box=BOX):
    raw = dict(placement_options(settings, box))
    return {
        "zero_start": bool(raw.get("zero-start", False)),
        "x_offset": float(raw.get("x-offset", 0)),
        "y_offset": float(raw.get("y-offset", 0)),
        "mirror_axis": float(raw.get("mirror-axis", 0)),
        "mirror_yaxis": bool(raw.get("mirror-yaxis", False)),
    }


def pcb2gcode_mill(x, y, back, o, bbox_min=(BOX.min_x, BOX.min_y)):
    xoffset = bbox_min[0] if o["zero_start"] else 0.0
    yoffset = bbox_min[1] if o["zero_start"] else 0.0
    xoffset -= o["x_offset"]
    yoffset -= o["y_offset"]
    if back:
        if o["mirror_yaxis"]:
            yoffset = -yoffset - 2 * o["mirror_axis"]
        else:
            xoffset = -xoffset - 2 * o["mirror_axis"]
    gx = -x if back and not o["mirror_yaxis"] else x  # mirror_toolpath()
    gy = -y if back and o["mirror_yaxis"] else y
    return gx - xoffset, gy - yoffset


def pcb2gcode_drill(x, y, from_back, o, bbox_min=(BOX.min_x, BOX.min_y)):
    xoffset = (bbox_min[0] if o["zero_start"] else 0.0) - o["x_offset"]
    yoffset = (bbox_min[1] if o["zero_start"] else 0.0) - o["y_offset"]
    gx = x if (not from_back or o["mirror_yaxis"]) else 2 * (xoffset + o["mirror_axis"]) - x
    gy = y if (not from_back or not o["mirror_yaxis"]) else 2 * (yoffset + o["mirror_axis"]) - y
    return gx - xoffset, gy - yoffset


POINTS = [(100, -80), (140, -50), (100, -50), (140, -80), (112.5, -61.25)]


def test_top_side_starts_at_board_corner():
    o = opts_for(Settings())
    for x, y in POINTS:
        assert pcb2gcode_mill(x, y, False, o) == pytest.approx((x - 100, y + 80))
        assert pcb2gcode_drill(x, y, False, o) == pytest.approx((x - 100, y + 80))


def test_bottom_side_turned_left_right_about_the_centre():
    o = opts_for(Settings())
    for x, y in POINTS:
        expected = (BOX.max_x - x, y - BOX.min_y)
        assert pcb2gcode_mill(x, y, True, o) == pytest.approx(expected)
        assert pcb2gcode_drill(x, y, True, o) == pytest.approx(expected)


def test_bottom_side_turned_top_bottom_about_the_centre():
    s = Settings()
    s.general.flip_axis = "topbottom"
    o = opts_for(s)
    for x, y in POINTS:
        expected = (x - BOX.min_x, BOX.max_y - y)
        assert pcb2gcode_mill(x, y, True, o) == pytest.approx(expected)
        assert pcb2gcode_drill(x, y, True, o) == pytest.approx(expected)


def test_both_sides_cover_the_same_rectangle():
    o = opts_for(Settings())
    for back in (False, True):
        xs, ys = zip(*(pcb2gcode_mill(x, y, back, o) for x, y in POINTS))
        assert min(xs) == pytest.approx(0) and max(xs) == pytest.approx(BOX.width)
        assert min(ys) == pytest.approx(0) and max(ys) == pytest.approx(BOX.height)


def test_a_hole_drilled_from_the_top_meets_the_bottom_copper():
    # In the flip frame holes are drilled before turning over. After turning,
    # the hole sits where the bottom-side G-code expects its pad.
    o = opts_for(Settings())
    x, y = 112.5, -61.25
    hx, hy = pcb2gcode_drill(x, y, False, o)  # position on the top
    turned = (BOX.width - hx, hy)  # left/right turn inside the frame
    assert turned == pytest.approx(pcb2gcode_mill(x, y, True, o))


def test_without_outline_pcb2gcode_places_the_origin():
    assert placement_options(Settings(), None) == [("zero-start", True)]


def test_zero_start_off_leaves_coordinates_alone():
    s = Settings()
    s.general.zero_start = False
    assert placement_options(s, BOX) == []


def test_frame_mode_forces_corner_origin_and_top_drilling():
    s = Settings()
    s.general.frame_mode = True
    s.general.zero_start = False  # ignored in the frame
    s.drill.drill_side = "back"  # ignored in the frame
    opts = dict(build_options(s, Inputs(front="f", back="b", drill="d", board_box=BOX), "x"))
    assert opts["x-offset"] == "-100"
    assert opts["y-offset"] == "80"
    assert opts["mirror-axis"] == "20"
    assert opts["drill-side"] == "front"
    assert "zero-start" not in opts


def test_frame_mode_needs_an_outline():
    s = Settings()
    s.general.frame_mode = True
    assert "frame_needs_outline" in validate(s, Inputs(front="f"))
    assert validate(s, Inputs(front="f", board_box=BOX)) == []
