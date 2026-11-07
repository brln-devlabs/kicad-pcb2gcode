"""Minimal inspection of exported Gerber and Excellon files.

Used to decide which copper sides actually need isolation milling and to
skip outline or drill jobs when the board has nothing to cut or drill.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Operation codes may stand alone ("D01*") or follow coordinates ("X100Y200D01*").
_D01 = re.compile(r"D0?1\*")
_D03 = re.compile(r"D0?3\*")
# Excellon hit: a coordinate line, optionally with a G85 slot ("X1Y2G85X3Y4").
_DRILL_HIT = re.compile(r"^\s*(?:G\d+)?X[-+]?[\d.]+(?:Y[-+]?[\d.]+)?", re.MULTILINE | re.IGNORECASE)


@dataclass
class LayerStats:
    draws: int = 0  # interpolations: tracks, zone fills, graphic lines
    flashes: int = 0  # pads and vias

    @property
    def empty(self) -> bool:
        return self.draws == 0 and self.flashes == 0


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="ascii", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def layer_stats(path: str) -> LayerStats:
    lines = []
    for line in _read(path).splitlines():
        stripped = line.strip()
        # aperture definitions ("%ADD10C,0.25*%") and other extended commands
        # never contain operation codes we care about
        if stripped.startswith("%") or stripped.startswith("G04"):
            continue
        lines.append(stripped)
    body = "\n".join(lines)
    return LayerStats(draws=len(_D01.findall(body)), flashes=len(_D03.findall(body)))


def drill_hits(path: str) -> int:
    text = _read(path)
    # Hits follow the header, which ends with "%" (or M95).
    for marker in ("\n%\n", "\r\n%\r\n", "M95"):
        idx = text.find(marker)
        if idx >= 0:
            text = text[idx + len(marker):]
            break
    return len(_DRILL_HIT.findall(text))


def choose_sides(front: LayerStats, back: LayerStats) -> str:
    """Pick "front", "back" or "both" from the content of the two copper layers.

    Traces decide. A layer that only carries THT pads (KiCad plots those on
    both sides) does not need isolation milling. Without traces anywhere, fall
    back to the side that has pads, preferring the back (single-sided THT).
    """
    if front.draws and back.draws:
        return "both"
    if front.draws:
        return "front"
    if back.draws:
        return "back"
    if front.flashes and not back.flashes:
        return "front"
    return "back"
