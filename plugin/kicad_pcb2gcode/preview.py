"""Preview images: the SVG files pcb2gcode writes next to the G-code.

pcb2gcode draws, for every layer it processes, the copper together with the
tool paths (``processed_<layer>.svg``), the drill holes (``original_drill.svg``)
and, when a clearance could not be kept, the problem spots
(``contentions_<layer>.svg``). The names carry no board name, so each
pcb2gcode run would overwrite the images of the previous one. After every run
the plugin moves them to ``<output>/preview/<run>/`` and the window lists them
from there.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
from typing import List, Tuple

from .i18n import tr

PREVIEW_DIR = "preview"
RUNS = ("main", "npth", "mask")

_LAYER_LABELS = {
    "front": ("Top side (F.Cu)", "Oberseite (F.Cu)"),
    "back": ("Bottom side (B.Cu)", "Unterseite (B.Cu)"),
    "outline": ("Outline", "Kontur"),
    "drill": ("Drill", "Bohren"),
    "milldrill": ("Mill holes", "Löcher fräsen"),
}
_RUN_PREFIX = {
    "main": ("", ""),
    "npth": ("NPTH: ", "NPTH: "),
    "mask": ("Solder mask: ", "Lötstopp: "),
}
_MASK_LABELS = {
    "front": ("Solder mask top", "Lötstopp Oberseite"),
    "back": ("Solder mask bottom", "Lötstopp Unterseite"),
}

# processed_front.svg, processed_front_final.svg, processed_front_final_1.svg,
# contentions_back.svg, original_drill.svg ...
_NAME = re.compile(r"^(processed|contentions|original)_(front|back|outline|drill|milldrill)(_final)?(?:_(\d+))?\.svg$")


def preview_root(output_dir: str) -> str:
    return os.path.join(output_dir, PREVIEW_DIR)


def clear(output_dir: str) -> None:
    """Remove the images of earlier runs, and pcb2gcode's loose SVG files."""
    shutil.rmtree(preview_root(output_dir), ignore_errors=True)
    for path in glob.glob(os.path.join(output_dir, "*.svg")):
        try:
            os.remove(path)
        except OSError:
            pass


def collect_run(output_dir: str, run: str) -> List[str]:
    """Move the SVG files the last pcb2gcode run wrote into preview/<run>/."""
    target_dir = os.path.join(preview_root(output_dir), run)
    moved = []
    for path in sorted(glob.glob(os.path.join(output_dir, "*.svg"))):
        os.makedirs(target_dir, exist_ok=True)
        target = os.path.join(target_dir, os.path.basename(path))
        os.replace(path, target)
        moved.append(target)
    return moved


def _choose(files: List[str]) -> List[Tuple[str, str, str]]:
    """Pick one image per (kind, layer): the combined "_final" image of the
    last tool when there are several tools, else the plain one."""
    best = {}
    for path in files:
        m = _NAME.match(os.path.basename(path))
        if not m:
            continue  # traced_*, outp*_* debug images and the like
        kind, layer, final, index = m.group(1), m.group(2), bool(m.group(3)), int(m.group(4) or 0)
        rank = (final, index)
        key = (kind, layer)
        if key not in best or rank > best[key][0]:
            best[key] = (rank, path)
    return [(kind, layer, path) for (kind, layer), (_, path) in best.items()]


_ORDER = ["front", "back", "drill", "milldrill", "outline"]


def list_previews(output_dir: str) -> List[Tuple[str, str]]:
    """(label, path) of the images to show, in machining order; problem
    images ("contentions") come first so they are not overlooked."""
    entries = []
    for run_index, run in enumerate(RUNS):
        files = glob.glob(os.path.join(preview_root(output_dir), run, "*.svg"))
        for kind, layer, path in _choose(files):
            if kind == "original" and layer in ("front", "back", "outline"):
                continue
            if run == "mask" and layer in _MASK_LABELS:
                label = tr(*_MASK_LABELS[layer])
            else:
                label = tr(*_RUN_PREFIX[run]) + tr(*_LAYER_LABELS[layer])
            if kind == "contentions":
                label = "⚠ " + tr("Clearance not kept - ", "Abstand nicht eingehalten - ") + label
                sort_key = (0, run_index, _ORDER.index(layer))
            else:
                sort_key = (1, run_index, _ORDER.index(layer))
            entries.append((sort_key, label, path))
    entries.sort()
    return [(label, path) for _, label, path in entries]


# -- view geometry (zoom and pan), kept free of wx so it can be tested ---------

MIN_ZOOM = 0.5  # relative to "fit to window"
MAX_ZOOM = 60.0


def fit_view(image_w: float, image_h: float, view_w: float, view_h: float, margin: float = 8.0):
    """(origin_x, origin_y, scale) that shows the whole image centred."""
    if image_w <= 0 or image_h <= 0 or view_w <= 2 * margin or view_h <= 2 * margin:
        return 0.0, 0.0, 1.0
    scale = min((view_w - 2 * margin) / image_w, (view_h - 2 * margin) / image_h)
    return (view_w - image_w * scale) / 2.0, (view_h - image_h * scale) / 2.0, scale


def zoom_at(origin_x: float, origin_y: float, scale: float, point_x: float, point_y: float,
            factor: float, fit_scale: float):
    """Zoom by ``factor`` keeping the image point under (point_x, point_y) in
    place; the zoom stays between MIN_ZOOM and MAX_ZOOM times ``fit_scale``."""
    new_scale = min(max(scale * factor, fit_scale * MIN_ZOOM), fit_scale * MAX_ZOOM)
    ratio = new_scale / scale
    return point_x - (point_x - origin_x) * ratio, point_y - (point_y - origin_y) * ratio, new_scale


def wheel_factor(rotation: int, delta: int) -> float:
    """1.25 per notch of the mouse wheel; touchpads send fractions of a notch."""
    steps = rotation / float(delta or 120)
    return 1.25 ** steps


def ease_scale(current: float, target: float, fraction: float = 0.35):
    """One animation step from ``current`` towards ``target`` scale, evenly
    in log space so zooming in and out feel the same. Returns (scale, done)."""
    import math

    if current <= 0 or target <= 0 or abs(math.log(target / current)) < 0.003:
        return target, True
    return current * (target / current) ** fraction, False


def ease_fraction(seconds: float, time_constant: float = 0.06) -> float:
    """Share of the remaining way to cover in ``seconds``: exponential easing
    by time, so the glide looks the same however fast frames are drawn."""
    import math

    if seconds <= 0:
        return 0.0
    return 1.0 - math.exp(-seconds / time_constant)


# -- tiles ------------------------------------------------------------------
#
# For heavy images the window keeps exact renderings in square tiles. Two
# kinds: "exact" tiles at the current zoom, aligned to the screen pixels, so
# moving the view just shows already drawn pixels; and a pyramid of zoom
# levels sqrt(2) apart, used while the zoom glides. The pyramid level drawn is
# always the next one at or above the current zoom, so its pixels are only
# ever shrunk (by at most sqrt(2)), never enlarged.

TILE = 256


def pyramid_scale(base: float, level: int) -> float:
    return base * 2.0 ** (level / 2.0)


def pyramid_level(scale: float, base: float) -> int:
    """Lowest pyramid level whose scale is at least ``scale``."""
    import math

    if scale <= 0 or base <= 0:
        return 0
    return int(math.ceil(2.0 * math.log2(scale / base) - 1e-9))


def _tile_span(lo: float, hi: float, size: int = TILE) -> range:
    import math

    if hi <= lo:
        return range(0)
    return range(int(math.floor(lo / size)), int(math.floor((hi - 1e-9) / size)) + 1)


def pyramid_tiles(view: Tuple[float, float, float, float], level_scale: float,
                  image_w: float, image_h: float) -> List[Tuple[int, int]]:
    """Pyramid tiles (tx, ty) at ``level_scale`` covering ``view`` (image
    coordinates), limited to the image."""
    x0, y0 = max(view[0], 0.0) * level_scale, max(view[1], 0.0) * level_scale
    x1, y1 = min(view[2], image_w) * level_scale, min(view[3], image_h) * level_scale
    return [(tx, ty) for ty in _tile_span(y0, y1) for tx in _tile_span(x0, x1)]


def exact_grid(origin: Tuple[float, float]):
    """(integer screen offset, fraction) of the screen-aligned tile grid for a
    view whose image (0, 0) lies at ``origin``. Moving the view by whole pixels
    keeps the fraction, so the tiles stay valid."""
    import math

    ix, iy = math.floor(origin[0]), math.floor(origin[1])
    return (ix, iy), (round(origin[0] - ix, 6), round(origin[1] - iy, 6))


def exact_tiles(origin: Tuple[float, float], scale: float, view_w: float, view_h: float,
                image_w: float, image_h: float, margin: int = 0) -> List[Tuple[int, int]]:
    """Screen-aligned tiles covering the window (plus ``margin`` tiles around),
    limited to the image, nearest to the window centre first."""
    (ix, iy), (fx, fy) = exact_grid(origin)
    x0 = max(-ix - margin * TILE, fx)
    y0 = max(-iy - margin * TILE, fy)
    x1 = min(view_w - ix + margin * TILE, fx + image_w * scale)
    y1 = min(view_h - iy + margin * TILE, fy + image_h * scale)
    tiles = [(tx, ty) for ty in _tile_span(y0, y1) for tx in _tile_span(x0, x1)]
    cx, cy = view_w / 2.0 - ix, view_h / 2.0 - iy
    tiles.sort(key=lambda t: ((t[0] + 0.5) * TILE - cx) ** 2 + ((t[1] + 0.5) * TILE - cy) ** 2)
    return tiles
