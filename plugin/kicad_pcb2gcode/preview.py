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
