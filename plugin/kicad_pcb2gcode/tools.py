"""Small numeric helpers shared by the CLI, the dialog and the millproject builder."""

from __future__ import annotations

import math
import re
from typing import List


def fmt(value) -> str:
    """Format a value for pcb2gcode: booleans as true/false, numbers as plain
    decimals with at most five places, no exponent, no trailing zeros, never -0."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = "{:.5f}".format(float(value)).rstrip("0").rstrip(".")
    if text in ("-0", "", "-"):
        text = "0"
    return text


def parse_diameter_list(text: str) -> List[float]:
    """Parse "0.8, 1.0;1.2mm 1.5" into [0.8, 1.0, 1.2, 1.5].

    Raises ValueError naming the offending item.
    """
    result: List[float] = []
    for raw in text.replace(";", ",").replace(" ", ",").replace("\t", ",").split(","):
        item = raw.strip()
        if not item:
            continue
        number = item[:-2].strip() if item.lower().endswith("mm") else item
        if not number:
            continue
        try:
            value = float(number)
        except ValueError:
            raise ValueError(item) from None
        if not value > 0 or math.isinf(value):
            raise ValueError(item)
        result.append(value)
    return result


_OVERLAP = re.compile(r"^([0-9]*\.?[0-9]+)\s*(%|mm|in)?$", re.IGNORECASE)


def parse_overlap(text: str) -> str:
    """Normalise a milling overlap for pcb2gcode.

    Accepts a percentage of the tool width ("20%", or a bare "20") or a length
    ("0.05mm", "0.002in"); a decimal comma is accepted too. Returns e.g. "20%"
    or "0.05mm". Raises ValueError for anything else, or for 100 % and more.
    """
    m = _OVERLAP.match(text.strip().replace(",", "."))
    if not m:
        raise ValueError(text)
    value = float(m.group(1))
    unit = (m.group(2) or "%").lower()
    if unit == "%" and value >= 100:
        raise ValueError(text)
    return fmt(value) + unit
