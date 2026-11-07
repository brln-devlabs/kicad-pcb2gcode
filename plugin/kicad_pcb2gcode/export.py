"""Command lines for kicad-cli and discovery of the external programs.

KiCad 9 and 10 cannot plot through the IPC API, so the plugin exports with
``kicad-cli``, which ships with every KiCad installation.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
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


def in_flatpak() -> bool:
    """True when running inside a Flatpak sandbox (KiCad from Flathub)."""
    return os.path.exists("/.flatpak-info") or "FLATPAK_ID" in os.environ


def _quiet(cmd: List[str], timeout: float) -> str:
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                                text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _last_path(output: str) -> Optional[str]:
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("/"):
            return line
    return None


def login_shell_lookup(name: str) -> Optional[str]:
    """Look ``name`` up the way a terminal would. Programs started from the
    desktop menu do not see PATH additions from ~/.bashrc or ~/.profile."""
    if sys.platform == "win32" or in_flatpak():
        return None
    shell = os.environ.get("SHELL") or "/bin/sh"
    for flag in ("-lc", "-ic"):
        found = _last_path(_quiet([shell, flag, "command -v " + name], timeout=5))
        if found and _is_executable(found):
            return found
    return None


def host_lookup(name: str) -> Optional[str]:
    """From inside a Flatpak: where ``name`` lives on the host system."""
    return _last_path(_quiet(["flatpak-spawn", "--host", "sh", "-lc", "command -v " + name], timeout=10))


def host_is_executable(path: str) -> bool:
    return bool(_quiet(["flatpak-spawn", "--host", "sh", "-c", 'test -x "$1" && echo yes', "sh", path], timeout=10))


def pcb2gcode_candidates(configured: str = "") -> List[str]:
    candidates = []
    if configured:
        candidates.append(os.path.expanduser(configured))
    found = shutil.which("pcb2gcode")
    if found:
        candidates.append(found)
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA"), r"C:\Program Files"):
            if root:
                candidates.append(os.path.join(root, "pcb2gcode", _exe("pcb2gcode")))
                candidates.append(os.path.join(root, "pcb2gcodeGUI", _exe("pcb2gcode")))
    elif sys.platform == "darwin":
        candidates.extend(["/opt/homebrew/bin/pcb2gcode", "/usr/local/bin/pcb2gcode"])
    else:
        candidates.extend([
            "/usr/bin/pcb2gcode",
            "/usr/local/bin/pcb2gcode",
            os.path.join(home, ".local", "bin", "pcb2gcode"),
            os.path.join(home, "bin", "pcb2gcode"),
            "/home/linuxbrew/.linuxbrew/bin/pcb2gcode",
            os.path.join(home, ".linuxbrew", "bin", "pcb2gcode"),
            "/opt/pcb2gcode/bin/pcb2gcode",
        ])
    return list(dict.fromkeys(candidates))


@dataclass
class Located:
    """Where pcb2gcode was found; ``host`` means outside the Flatpak sandbox,
    to be started with ``flatpak-spawn --host``."""

    path: Optional[str]
    host: bool = False
    searched: List[str] = field(default_factory=list)

    def command(self, cwd: str, *args: str) -> List[str]:
        if self.host:
            return ["flatpak-spawn", "--host", "--directory=" + cwd, self.path or "pcb2gcode", *args]
        return [self.path or "pcb2gcode", *args]


def locate_pcb2gcode(configured: str = "") -> Located:
    candidates = pcb2gcode_candidates(configured)
    for path in candidates:
        if _is_executable(path):
            return Located(path, searched=candidates)
    found = login_shell_lookup("pcb2gcode")
    if found:
        return Located(found, searched=candidates)
    if in_flatpak():
        configured_path = os.path.expanduser(configured) if configured else ""
        if configured_path and host_is_executable(configured_path):
            return Located(configured_path, host=True, searched=candidates)
        found = host_lookup("pcb2gcode")
        if found:
            return Located(found, host=True, searched=candidates)
    return Located(None, searched=candidates)


def find_pcb2gcode(configured: str = "") -> Optional[str]:
    return locate_pcb2gcode(configured).path
