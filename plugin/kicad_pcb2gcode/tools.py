"""Small numeric helpers shared by the CLI, the dialog and the millproject builder."""

from __future__ import annotations

import math
from typing import List


def vbit_width(tip: float, angle_deg: float, depth: float) -> float:
    """Width a V-bit cuts at the copper surface.

    ``depth`` may be passed as the (negative) ``zwork`` value; its magnitude is used.
    width = tip + 2 * depth * tan(angle / 2)
    """
    if not 0 < angle_deg < 180:
        raise ValueError("V-bit angle must be between 0 and 180 degrees")
    if tip < 0:
        raise ValueError("V-bit tip width must not be negative")
    return tip + 2.0 * abs(depth) * math.tan(math.radians(angle_deg) / 2.0)


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
