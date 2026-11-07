"""Command lines for kicad-cli and discovery of the external programs.

KiCad 9 and 10 cannot plot through the IPC API, so the plugin exports with
``kicad-cli``, which ships with every KiCad installation.
"""

from __future__ import annotations

import glob
import os
import shutil
import sys
from typing import List, Optional

COPPER_LAYERS = {"front": "F.Cu", "back": "B.Cu"}
OUTLINE_LAYER = "Edge.Cuts"


def gerber_command(kicad_cli: str, board: str, layer: str, output_file: str, use_aux_origin: bool) -> List[str]:
    """Plot one layer into one Gerber file (``kicad-cli pcb export gerber``)."""
    cmd = [
        kicad_cli, "pcb", "export", "gerber",
        "--output", output_file,
        "--layers", layer,
        "--no-x2",
        "--no-netlist",
    ]
    if use_aux_origin:
        cmd.append("--use-drill-file-origin")
    cmd.append(board)
    return cmd


def gerbers_fallback_command(
    kicad_cli: str, board: str, layer: str, output_dir: str, use_aux_origin: bool
) -> List[str]:
    """Same plot through ``kicad-cli pcb export gerbers`` (plural), used if the
    single-file command is unavailable in a future KiCad version."""
    cmd = [
        kicad_cli, "pcb", "export", "gerbers",
        "--output", output_dir + os.sep,
        "--layers", layer,
        "--no-x2",
        "--no-netlist",
        "--no-protel-ext",
    ]
    if use_aux_origin:
        cmd.append("--use-drill-file-origin")
    cmd.append(board)
    return cmd


def gerbers_fallback_file(output_dir: str, board: str, layer: str) -> str:
    """File name kicad-cli gives a layer plotted with ``export gerbers``."""
    stem = os.path.splitext(os.path.basename(board))[0]
    return os.path.join(output_dir, "{}-{}.gbr".format(stem, layer.replace(".", "_")))


def drill_command(kicad_cli: str, board: str, output_dir: str, use_aux_origin: bool,
                  separate: bool = False) -> List[str]:
    """Excellon drill file(s), metric, decimal coordinates, oval holes as G85
    slots; PTH and NPTH merged into one file or written separately."""
    cmd = [
        kicad_cli, "pcb", "export", "drill",
        "--output", output_dir + os.sep,
        "--format", "excellon",
        "--excellon-units", "mm",
        "--excellon-zeros-format", "decimal",
        "--excellon-oval-format", "alternate",
        "--drill-origin", "plot" if use_aux_origin else "absolute",
    ]
    if separate:
        cmd.append("--excellon-separate-th")
    cmd.append(board)
    return cmd


def find_drill_file(output_dir: str, board: Optional[str] = None) -> Optional[str]:
    """The drill file with the through holes (``<board>.drl``)."""
    merged, _ = split_drill_files(output_dir, board)
    return merged


def split_separate_drill_files(output_dir: str, board: str) -> "tuple[Optional[str], Optional[str], List[str]]":
    """Files of ``--excellon-separate-th``: ``<board>-PTH.drl``, ``<board>-NPTH.drl``
    and anything else (layer-pair files of blind/buried vias)."""
    stem = os.path.splitext(os.path.basename(board))[0]
    files = sorted(glob.glob(os.path.join(output_dir, "*.drl")))
    pth = os.path.join(output_dir, stem + "-PTH.drl")
    npth = os.path.join(output_dir, stem + "-NPTH.drl")
    others = [f for f in files if f not in (pth, npth)]
    return (pth if pth in files else None), (npth if npth in files else None), others


def split_drill_files(output_dir: str, board: Optional[str] = None) -> "tuple[Optional[str], List[str]]":
    """Split kicad-cli's drill output into the through-hole file and the rest.

    KiCad writes ``<board>.drl`` for through holes and one extra file per
    layer pair (``<board>-F_Cu-In1_Cu.drl`` and similar) for blind, buried
    and micro vias. Extra files mean the board cannot be made by milling.
    """
    files = sorted(glob.glob(os.path.join(output_dir, "*.drl")))
    if not files:
        return None, []
    if board:
        exact = os.path.join(output_dir, os.path.splitext(os.path.basename(board))[0] + ".drl")
        if exact in files:
            return exact, [f for f in files if f != exact]
    plain = [f for f in files if not f.endswith(("-NPTH.drl", "-PTH.drl"))]
    merged = min(plain or files, key=len)  # the layer-pair files carry longer suffixes
    return merged, [f for f in files if f != merged]


# -- program discovery --------------------------------------------------------


def _is_executable(path: str) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def _exe(name: str) -> str:
    return name + ".exe" if sys.platform == "win32" else name


def kicad_cli_candidates() -> List[str]:
    found = shutil.which("kicad-cli")
    candidates = [found] if found else []
    if sys.platform == "win32":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), r"C:\Program Files"):
            if root:
                pattern = os.path.join(root, "KiCad", "*", "bin", "kicad-cli.exe")
                candidates.extend(sorted(glob.glob(pattern), reverse=True))
    elif sys.platform == "darwin":
        candidates.append("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
        candidates.extend(sorted(glob.glob("/Applications/KiCad*/KiCad.app/Contents/MacOS/kicad-cli"), reverse=True))
    else:
        candidates.extend(["/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli"])
    return candidates


def find_kicad_cli(preferred: Optional[str] = None) -> Optional[str]:
    for path in ([preferred] if preferred else []) + kicad_cli_candidates():
        if _is_executable(path):
            return path
    return None


def pcb2gcode_candidates(configured: str = "") -> List[str]:
    candidates = []
    if configured:
        candidates.append(os.path.expanduser(configured))
    found = shutil.which("pcb2gcode")
    if found:
        candidates.append(found)
    if sys.platform == "win32":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA"), r"C:\Program Files"):
            if root:
                candidates.append(os.path.join(root, "pcb2gcode", _exe("pcb2gcode")))
                candidates.append(os.path.join(root, "pcb2gcodeGUI", _exe("pcb2gcode")))
    elif sys.platform == "darwin":
        candidates.extend(["/opt/homebrew/bin/pcb2gcode", "/usr/local/bin/pcb2gcode"])
    else:
        candidates.extend(["/usr/bin/pcb2gcode", "/usr/local/bin/pcb2gcode", os.path.expanduser("~/.local/bin/pcb2gcode")])
    return candidates


def find_pcb2gcode(configured: str = "") -> Optional[str]:
    for path in pcb2gcode_candidates(configured):
        if _is_executable(path):
            return path
    return None
