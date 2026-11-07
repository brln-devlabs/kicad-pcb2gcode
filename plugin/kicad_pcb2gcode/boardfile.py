"""Light-weight look into a .kicad_pcb file (no KiCad API needed).

Only what the plugin must know before exporting: which inner copper layers
exist and whether the board uses blind, buried or micro vias. Works for the
KiCad 6 to 10 file formats (layer names quoted or not, any layer numbering).
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

_INNER = re.compile(r'\(\s*\d+\s+"?(In(\d+)\.Cu)"?\s')
# KiCad writes "(via blind ..." for blind and buried vias, "(via micro ..." for microvias.
_SPECIAL_VIA = re.compile(r"\(via\s+(blind|buried|micro)\b")
_AUX_ORIGIN = re.compile(r"\(aux_axis_origin\s+([-+\d.eE]+)\s+([-+\d.eE]+)\s*\)")


def read_board(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _layers_section(text: str) -> str:
    start = text.find("(layers")
    if start < 0:
        return ""
    end = text.find("(setup", start)
    return text[start:end if end > 0 else len(text)]


def inner_copper_layers(text: str) -> List[str]:
    """Names of the inner copper layers, in stack order ("In1.Cu", "In2.Cu", …)."""
    found = {int(m.group(2)): m.group(1) for m in _INNER.finditer(_layers_section(text))}
    return [found[k] for k in sorted(found)]


def special_via_kinds(text: str) -> List[str]:
    """Sorted kinds of non-through vias used on the board ("blind", "micro")."""
    return sorted({m.group(1) for m in _SPECIAL_VIA.finditer(text)})


def drill_origin(text: str) -> Optional[Tuple[float, float]]:
    """The drill/place file origin in mm, or None while it is not set.

    KiCad keeps it in the setup section as ``(aux_axis_origin X Y)`` and leaves
    the entry out while it is at its default 0/0.
    """
    m = _AUX_ORIGIN.search(text)
    if not m:
        return None
    x, y = float(m.group(1)), float(m.group(2))
    if x == 0 and y == 0:
        return None
    return x, y
