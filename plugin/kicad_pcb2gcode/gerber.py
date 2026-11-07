"""Minimal inspection of exported Gerber and Excellon files.

Used to decide which copper sides actually need isolation milling and to
skip outline or drill jobs when the board has nothing to cut or drill.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

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


@dataclass(frozen=True)
class Box:
    """Axis-aligned rectangle in Gerber coordinates, millimetres."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y


_FORMAT = re.compile(r"%FS[LT]?[AI]?X(\d)(\d)Y(\d)(\d)\*%")
_STATEMENT = re.compile(
    r"^(?:G0?([123])\*?)?"
    r"(?:X([+-]?\d+))?(?:Y([+-]?\d+))?(?:I([+-]?\d+))?(?:J([+-]?\d+))?"
    r"(?:D0?([123]))?$"
)


def _arc_points(sx, sy, ex, ey, cx, cy, clockwise):
    """Start, end and every axis extreme the arc sweeps through."""
    r = math.hypot(sx - cx, sy - cy)
    a0 = math.atan2(sy - cy, sx - cx)
    a1 = math.atan2(ey - cy, ex - cx)
    if clockwise:
        a0, a1 = a1, a0  # walk counter-clockwise from a0 to a1
    sweep = (a1 - a0) % (2 * math.pi)
    if sweep < 1e-12 and math.hypot(ex - sx, ey - sy) < 1e-9:
        sweep = 2 * math.pi  # start == end: full circle
    points = [(sx, sy), (ex, ey)]
    for k in range(4):
        angle = k * math.pi / 2
        if (angle - a0) % (2 * math.pi) <= sweep + 1e-12:
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def outline_box(path: str) -> Optional[Box]:
    """Bounding rectangle of the drawn outline (line centres, arcs included).

    This is the board size KiCad uses for manufacturing, independent of the
    line width on Edge.Cuts. Returns None if the file has no drawn geometry.
    """
    text = _read(path)
    fmt = _FORMAT.search(text)
    x_dec = int(fmt.group(2)) if fmt else 6
    y_dec = int(fmt.group(4)) if fmt else 6
    scale = 25.4 if "%MOIN*%" in text else 1.0
    clockwise = False
    interpolation = "line"
    x = y = 0.0
    xs: list = []
    ys: list = []

    def add(px: float, py: float) -> None:
        xs.append(px)
        ys.append(py)

    for raw in text.split("*"):
        st = raw.strip().replace("\n", "").replace("\r", "")
        if not st or st.startswith("%") or st.startswith("G04") or "%" in st:
            continue
        m = _STATEMENT.match(st)
        if not m:
            continue
        g, sx, sy, si, sj, d = m.groups()
        if g == "1":
            interpolation = "line"
        elif g in ("2", "3"):
            interpolation = "arc"
            clockwise = g == "2"
        nx = int(sx) / 10 ** x_dec * scale if sx is not None else x
        ny = int(sy) / 10 ** y_dec * scale if sy is not None else y
        if d == "1":
            if interpolation == "arc":
                cx = x + (int(si) / 10 ** x_dec * scale if si else 0.0)
                cy = y + (int(sj) / 10 ** y_dec * scale if sj else 0.0)
                for px, py in _arc_points(x, y, nx, ny, cx, cy, clockwise):
                    add(px, py)
            else:
                add(x, y)
                add(nx, ny)
        elif d == "3":
            add(nx, ny)
        if d is not None or sx is not None or sy is not None:
            x, y = nx, ny
    if not xs:
        return None
    return Box(min(xs), min(ys), max(xs), max(ys))


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
