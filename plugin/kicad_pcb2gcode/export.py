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


def drill_command(kicad_cli: str, board: str, output_dir: str, use_aux_origin: bool) -> List[str]:
    """Excellon drill file, metric, decimal coordinates, PTH and NPTH merged,
    oval holes as G85 slots."""
    return [
        kicad_cli, "pcb", "export", "drill",
        "--output", output_dir + os.sep,
        "--format", "excellon",
        "--excellon-units", "mm",
        "--excellon-zeros-format", "decimal",
        "--excellon-oval-format", "alternate",
        "--drill-origin", "plot" if use_aux_origin else "absolute",
        board,
    ]


def find_drill_file(output_dir: str) -> Optional[str]:
    """The merged drill file kicad-cli wrote (``<board>.drl``)."""
    files = sorted(glob.glob(os.path.join(output_dir, "*.drl")))
    merged = [f for f in files if not f.endswith(("-NPTH.drl", "-PTH.drl"))]
    if merged:
        return merged[0]
    return files[0] if files else None


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
