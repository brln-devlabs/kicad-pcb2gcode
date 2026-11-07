import pytest

from kicad_pcb2gcode.tools import fmt, parse_diameter_list, parse_overlap


@pytest.mark.parametrize(
    "text, normalised",
    [("20%", "20%"), ("20", "20%"), (" 12.5 % ", "12.5%"), ("0,05mm", "0.05mm"),
     ("0.002IN", "0.002in"), ("0%", "0%"), ("12mm", "12mm")],
)
def test_parse_overlap(text, normalised):
    assert parse_overlap(text) == normalised


@pytest.mark.parametrize("text", ["", "100%", "150", "-5%", "abc", "5cm", "1.2.3"])
def test_parse_overlap_rejects(text):
    with pytest.raises(ValueError):
        parse_overlap(text)


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
