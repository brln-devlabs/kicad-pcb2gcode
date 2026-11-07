import math

import pytest

from kicad_pcb2gcode.tools import fmt, parse_diameter_list, vbit_width


def test_vbit_width_geometry():
    # 30° V-bit, 0.1 mm tip, 0.08 mm deep: 0.1 + 2 * 0.08 * tan(15°)
    expected = 0.1 + 2 * 0.08 * math.tan(math.radians(15))
    assert vbit_width(0.1, 30, -0.08) == pytest.approx(expected)
    assert vbit_width(0.1, 30, 0.08) == pytest.approx(expected)  # sign of depth irrelevant
    assert vbit_width(0.0, 90, 0.1) == pytest.approx(0.2)


@pytest.mark.parametrize("tip, angle", [(0.1, 0), (0.1, 180), (-0.1, 30)])
def test_vbit_width_rejects_nonsense(tip, angle):
    with pytest.raises(ValueError):
        vbit_width(tip, angle, 0.1)


@pytest.mark.parametrize(
    "value, text",
    [
        (True, "true"),
        (False, "false"),
        (4, "4"),
        (1.0, "1"),
        (-0.08, "-0.08"),
        (0.142872, "0.14287"),
        (10000.0, "10000"),
        (-0.000001, "0"),
        (1e-7, "0"),
        (2.50, "2.5"),
    ],
)
def test_fmt(value, text):
    assert fmt(value) == text


def test_parse_diameter_list():
    assert parse_diameter_list("") == []
    assert parse_diameter_list("0.8, 1.0;1.2mm  1.5 MM") == [0.8, 1.0, 1.2, 1.5]
    for bad in ("0.8, abc", "0.8, -1", "0", "inf"):
        with pytest.raises(ValueError):
            parse_diameter_list(bad)
