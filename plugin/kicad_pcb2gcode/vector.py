"""Vector scene of an SVG image, prepared once so it can be redrawn every frame.

``wx.svg.SVGimage.RenderToGC`` rebuilds every path, pen and brush from the
parsed SVG on each call - far too slow to redraw a pcb2gcode image 60 times a
second while zooming or dragging. This module turns the parsed shapes
(nanosvg, as exposed by ``wx.svg``) into plain drawing items once:

* straight segments (nanosvg stores every line as a cubic curve) become lines
  again, which are much cheaper to fill and stroke,
* shape opacity is folded into the fill and stroke colours (no layers),
* outline-only shapes with the same pen are merged into one path - pcb2gcode
  draws a thin black centre line on every tool path,
* every item keeps its bounding box, so items outside the view are skipped.

It does not import wx; ``gui`` turns the items into ``wx.GraphicsPath``
objects and draws them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

# nanosvg enum values (wx.svg mirrors them)
PAINT_NONE, PAINT_COLOR, PAINT_LINEAR, PAINT_RADIAL = 0, 1, 2, 3
JOIN_MITER, JOIN_ROUND, JOIN_BEVEL = 0, 1, 2
CAP_BUTT, CAP_ROUND, CAP_SQUARE = 0, 1, 2
FILL_NONZERO, FILL_EVENODD = 0, 1
FLAG_VISIBLE = 1

RGBA = Tuple[int, int, int, int]
# A sub path: (closed, start point, segments). A segment is (x, y) for a line
# or (c1x, c1y, c2x, c2y, x, y) for a cubic curve.
Segment = Tuple[float, ...]
SubPath = Tuple[bool, Tuple[float, float], List[Segment]]


@dataclass(frozen=True)
class Style:
    fill: Optional[RGBA]
    stroke: Optional[RGBA]
    width: float
    join: int
    cap: int
    evenodd: bool


@dataclass
class Item:
    style: Style
    bounds: List[float]  # min x, min y, max x, max y (stroke included)
    paths: List[SubPath] = field(default_factory=list)


def _enum(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _paint(paint, opacity: float) -> Optional[RGBA]:
    """Colour of an SVG paint; gradients are drawn in their first colour."""
    kind = _enum(getattr(paint, "type", PAINT_NONE))
    if kind == PAINT_NONE:
        return None
    rgba = None
    if kind == PAINT_COLOR:
        rgba = getattr(paint, "color_rgba", None)
    else:
        try:
            rgba = list(paint.gradient.stops)[0].color_rgba
        except Exception:
            rgba = None
    if rgba is None:
        return None
    r, g, b, a = (int(v) for v in rgba)
    a = int(round(a * max(0.0, min(1.0, opacity))))
    if a <= 0:
        return None
    return r, g, b, a


def _is_line(x0: float, y0: float, c: Sequence[float], tolerance: float) -> bool:
    """nanosvg writes a line from p0 to p as the curve p0, p0+d/3, p-d/3, p."""
    c1x, c1y, c2x, c2y, x, y = c
    dx, dy = (x - x0) / 3.0, (y - y0) / 3.0
    return (abs(c1x - (x0 + dx)) <= tolerance and abs(c1y - (y0 + dy)) <= tolerance
            and abs(c2x - (x - dx)) <= tolerance and abs(c2y - (y - dy)) <= tolerance)


def sub_path(points: Sequence[Sequence[float]], closed: bool, tolerance: float) -> Optional[SubPath]:
    """Turn nanosvg's point list (start point, then three points per cubic
    curve) into a sub path with lines where the curve is straight."""
    if not points:
        return None
    x0, y0 = float(points[0][0]), float(points[0][1])
    start = (x0, y0)
    segments: List[Segment] = []
    for i in range(1, len(points) - 2, 3):
        c = (float(points[i][0]), float(points[i][1]), float(points[i + 1][0]),
             float(points[i + 1][1]), float(points[i + 2][0]), float(points[i + 2][1]))
        if _is_line(x0, y0, c, tolerance):
            segments.append((c[4], c[5]))
        else:
            segments.append(c)
        x0, y0 = c[4], c[5]
    return closed, start, segments


def _bounds(shape, paths: List[SubPath], width: float) -> List[float]:
    try:
        b = [float(v) for v in shape.bounds]
        if len(b) != 4:
            raise ValueError
    except Exception:
        xs: List[float] = []
        ys: List[float] = []
        for _, (sx, sy), segs in paths:
            xs.append(sx)
            ys.append(sy)
            for s in segs:
                xs.extend(s[0::2])
                ys.extend(s[1::2])
        b = [min(xs), min(ys), max(xs), max(ys)] if xs else [0.0, 0.0, 0.0, 0.0]
    # a full stroke width of margin also covers miter joins of usual angles
    return [b[0] - width, b[1] - width, b[2] + width, b[3] + width]


def build_scene(shapes: Iterable, image_size: Tuple[float, float] = (0.0, 0.0)) -> List[Item]:
    """Drawing items for the parsed SVG shapes, in painting order."""
    span = max(image_size[0], image_size[1], 1.0)
    tolerance = span * 1e-6
    items: List[Item] = []
    merged = {}  # style -> index in items of the merged outline-only item
    for shape in shapes:
        if not _enum(getattr(shape, "flags", FLAG_VISIBLE), FLAG_VISIBLE) & FLAG_VISIBLE:
            continue
        opacity = float(getattr(shape, "opacity", 1.0) or 0.0)
        fill = _paint(shape.fill, opacity)
        width = float(getattr(shape, "strokeWidth", 0.0) or 0.0)
        stroke = _paint(shape.stroke, opacity) if width > 0 else None
        if fill is None and stroke is None:
            continue
        paths = []
        for path in shape.paths:
            sp = sub_path(path.points, bool(getattr(path, "closed", False)), tolerance)
            if sp is not None:
                paths.append(sp)
        if not paths:
            continue
        style = Style(fill, stroke, width if stroke else 0.0,
                      _enum(getattr(shape, "strokeLineJoin", JOIN_MITER)),
                      _enum(getattr(shape, "strokeLineCap", CAP_BUTT)),
                      _enum(getattr(shape, "fillRule", FILL_NONZERO)) == FILL_EVENODD)
        bounds = _bounds(shape, paths, style.width)
        if fill is None:
            # Outlines with the same pen look the same in one path; the merged
            # item moves to the position of its latest member, so everything
            # painted after any member still covers it.
            index = merged.pop(style, None)
            if index is not None:
                item = items[index]
                items[index] = None  # type: ignore[call-overload]
                item.paths.extend(paths)
                item.bounds = [min(item.bounds[0], bounds[0]), min(item.bounds[1], bounds[1]),
                               max(item.bounds[2], bounds[2]), max(item.bounds[3], bounds[3])]
            else:
                item = Item(style, bounds, paths)
            merged[style] = len(items)
            items.append(item)
        else:
            items.append(Item(style, bounds, paths))
            # a filled shape may cover earlier outlines: later ones start a new group
            merged.clear()
    return [item for item in items if item is not None]


def visible(item: Item, view: Tuple[float, float, float, float]) -> bool:
    """Does the item's box touch the view rectangle (image coordinates)?"""
    b = item.bounds
    return b[2] >= view[0] and b[0] <= view[2] and b[3] >= view[1] and b[1] <= view[3]


def view_rect(origin: Tuple[float, float], scale: float, width: float, height: float):
    """The window's area in image coordinates."""
    if scale <= 0:
        return 0.0, 0.0, 0.0, 0.0
    x0, y0 = -origin[0] / scale, -origin[1] / scale
    return x0, y0, x0 + width / scale, y0 + height / scale


def segment_count(items: Iterable[Item]) -> int:
    return sum(len(segs) + 1 for item in items for _, _, segs in item.paths)


# -- level of detail ------------------------------------------------------------
#
# A pcb2gcode image holds a few very long tool paths with tens of thousands of
# points; zoomed out, most points are closer together than a screen pixel.
# Each level keeps only the points needed for a given accuracy, and cuts the
# outlines into pieces sorted into a grid, so that zoomed in only the pieces
# in view are drawn. Pieces of a semi-transparent outline are drawn opaque
# into a layer that is then blended once: overlapping pieces do not get darker
# where they meet, exactly as when the whole outline is stroked at once.

MAX_ERROR_PX = 0.4  # allowed deviation on screen
LEVELS = 7  # level k keeps points to span / 1200 / 2**k; level LEVELS keeps all
GRID = 16  # cells per side for sorting outline pieces
PIECE = 64  # segments per outline piece


@dataclass
class Part:
    bounds: List[float]
    paths: List[SubPath]


@dataclass
class Group:
    """What one drawing item becomes at one level."""

    style: Style
    layer: float  # 1.0: draw directly; below: draw opaque into a layer of this opacity
    bounds: List[float]
    parts: List[Part]


def decimate(path: SubPath, tolerance: float, window: int = 48) -> SubPath:
    """Drop points of straight runs that stay within ``tolerance`` of the
    line through the points kept (a greedy, one-pass simplification).
    Curves, the start and the end are always kept."""
    closed, start, segments = path
    if tolerance <= 0 or len(segments) < 3:
        return path
    t2 = tolerance * tolerance
    out: List[Segment] = []
    ax, ay = start
    pending: List[Tuple[float, float]] = []
    for seg in segments:
        if len(seg) != 2:  # a real curve: flush and keep it
            if pending:
                out.append(pending[-1])
                pending = []
            out.append(seg)
            ax, ay = seg[4], seg[5]
            continue
        x, y = seg
        pending.append((x, y))
        if len(pending) == 1:
            continue
        dx, dy = x - ax, y - ay
        length2 = dx * dx + dy * dy
        fits = len(pending) <= window
        if fits:
            for px, py in pending[:-1]:
                cross = (px - ax) * dy - (py - ay) * dx
                if cross * cross > t2 * length2:
                    fits = False
                    break
        if not fits:
            keep = pending[-2]
            out.append(keep)
            ax, ay = keep
            pending = [(x, y)]
    if pending:
        out.append(pending[-1])
    return closed, start, out


def _path_bounds(paths: List[SubPath], margin: float) -> List[float]:
    xs: List[float] = []
    ys: List[float] = []
    for _, (sx, sy), segs in paths:
        xs.append(sx)
        ys.append(sy)
        for s in segs:
            xs.append(s[-2])
            ys.append(s[-1])
            if len(s) == 6:
                xs.extend((s[0], s[2]))
                ys.extend((s[1], s[3]))
    if not xs:
        return [0.0, 0.0, 0.0, 0.0]
    return [min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin]


def _pieces(path: SubPath, size: int) -> List[SubPath]:
    closed, start, segments = path
    if len(segments) <= size:
        return [path]
    out = []
    current = start
    for i in range(0, len(segments), size):
        chunk = segments[i:i + size]
        out.append((False, current, chunk))
        current = (chunk[-1][-2], chunk[-1][-1])
    if closed:  # close the ring with a last line back to the start
        out[-1][2].append(start)
    return out


class Scene:
    """Drawing items of one image, at several levels of detail (built on demand)."""

    def __init__(self, items: List[Item], image_size: Tuple[float, float]):
        self.items = items
        self.width, self.height = image_size
        self.span = max(image_size[0], image_size[1], 1e-9)
        self._levels: dict = {}

    @classmethod
    def from_shapes(cls, shapes: Iterable, image_size: Tuple[float, float]) -> "Scene":
        return cls(build_scene(shapes, image_size), image_size)

    def tolerance(self, level: int) -> float:
        return 0.0 if level >= LEVELS else self.span / 1200.0 / 2 ** level

    def level_for(self, scale: float) -> int:
        """The coarsest level that is still exact to MAX_ERROR_PX on screen."""
        for level in range(LEVELS):
            if self.tolerance(level) * scale <= MAX_ERROR_PX:
                return level
        return LEVELS

    def has_level(self, level: int) -> bool:
        return level in self._levels

    def groups(self, level: int) -> List[Group]:
        if level not in self._levels:
            self._levels[level] = self._build(level)
        return self._levels[level]

    def _build(self, level: int) -> List[Group]:
        tol = self.tolerance(level)
        cell_w = self.width / GRID or 1.0
        cell_h = self.height / GRID or 1.0
        groups = []
        for item in self.items:
            style = item.style
            paths = [decimate(p, tol) for p in item.paths] if tol else item.paths
            margin = style.width
            if style.fill is not None:
                groups.append(Group(style, 1.0, list(item.bounds), [Part(list(item.bounds), paths)]))
                continue
            cells: dict = {}
            for path in paths:
                for piece in _pieces(path, PIECE):
                    b = _path_bounds([piece], margin)
                    key = (int(((b[0] + b[2]) / 2) // cell_w), int(((b[1] + b[3]) / 2) // cell_h))
                    cell = cells.get(key)
                    if cell is None:
                        cells[key] = Part(b, [piece])
                    else:
                        cell.paths.append(piece)
                        cb = cell.bounds
                        cell.bounds = [min(cb[0], b[0]), min(cb[1], b[1]), max(cb[2], b[2]), max(cb[3], b[3])]
            alpha = style.stroke[3] if style.stroke else 255
            # one part is one stroke, which blends overlaps once anyway
            layer = alpha / 255.0 if alpha < 255 and len(cells) > 1 else 1.0
            groups.append(Group(style, layer, list(item.bounds), list(cells.values())))
        return groups
