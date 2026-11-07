"""The export → pcb2gcode pipeline, independent of KiCad's API and of any GUI.

Layout of the output folder (``<project>/gcode`` by default)::

    gcode/
      millproject          configuration handed to pcb2gcode
      <name>_front.ngc     … G-code written by pcb2gcode
      cam/                 intermediate files
        front.gbr back.gbr outline.gbr drill.drl
        <name>.kicad_pcb   copy of the open board (when exported from KiCad)
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from . import gerber
from .export import (
    COPPER_LAYERS,
    OUTLINE_LAYER,
    drill_command,
    find_drill_file,
    gerber_command,
    gerbers_fallback_command,
    gerbers_fallback_file,
)
from .i18n import problem_text, tr
from .millproject import Inputs, mill_diameter, render, validate
from .settings import Settings

Log = Callable[[str], None]
CAM_SUBDIR = "cam"


class JobError(Exception):
    """A failure with a message meant for the user."""


@dataclass
class JobRequest:
    board_file: str  # the .kicad_pcb kicad-cli reads (original or fresh copy)
    board_name: str  # used as pcb2gcode basename unless the settings override it
    output_dir: str
    kicad_cli: str
    pcb2gcode: str
    settings: Settings


@dataclass
class JobResult:
    output_dir: str
    sides: str
    inputs: Inputs
    files: List[str] = field(default_factory=list)
    millproject_path: str = ""


def _popen_kwargs() -> dict:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: no console flashing up
    return kwargs


def _run(cmd: List[str], log: Log, cwd: Optional[str] = None) -> int:
    """Run a command, streaming its merged output line by line into ``log``."""
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **_popen_kwargs(),
        )
    except OSError as exc:
        raise JobError(tr("Cannot start {}: {}", "Kann {} nicht starten: {}").format(cmd[0], exc)) from exc
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            log("  " + line)
    return proc.wait()


def _quiet_run(cmd: List[str]) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_popen_kwargs(),
    )


def export_layer(req: JobRequest, layer: str, target: str, log: Log) -> None:
    aux = req.settings.general.use_aux_origin
    cam_dir = os.path.dirname(target)
    result = _quiet_run(gerber_command(req.kicad_cli, req.board_file, layer, target, aux))
    if result.returncode == 0 and os.path.isfile(target):
        return
    # Fall back to the multi-file command and rename its output.
    fallback = _quiet_run(gerbers_fallback_command(req.kicad_cli, req.board_file, layer, cam_dir, aux))
    produced = gerbers_fallback_file(cam_dir, req.board_file, layer)
    if fallback.returncode == 0 and os.path.isfile(produced):
        os.replace(produced, target)
        return
    details = (result.stdout or "").strip() or (fallback.stdout or "").strip()
    raise JobError(
        tr("kicad-cli could not export layer {}:\n{}", "kicad-cli konnte die Lage {} nicht exportieren:\n{}").format(
            layer, details
        )
    )


def export_drill(req: JobRequest, cam_dir: str, log: Log) -> Optional[str]:
    drill_dir = os.path.join(cam_dir, "drill")
    shutil.rmtree(drill_dir, ignore_errors=True)
    os.makedirs(drill_dir, exist_ok=True)
    result = _quiet_run(drill_command(req.kicad_cli, req.board_file, drill_dir, req.settings.general.use_aux_origin))
    if result.returncode != 0:
        raise JobError(
            tr("kicad-cli could not export the drill file:\n{}", "kicad-cli konnte die Bohrdatei nicht exportieren:\n{}").format(
                (result.stdout or "").strip()
            )
        )
    produced = find_drill_file(drill_dir)
    if not produced:
        return None
    target = os.path.join(cam_dir, "drill.drl")
    os.replace(produced, target)
    shutil.rmtree(drill_dir, ignore_errors=True)
    return target


def _rel(path: str, start: str) -> str:
    return os.path.relpath(path, start).replace(os.sep, "/")


def prepare_inputs(req: JobRequest, log: Log) -> "tuple[Inputs, str]":
    """Export everything pcb2gcode needs into ``<output>/cam``; return the
    inputs (paths relative to the output folder) and the chosen sides."""
    s = req.settings
    out = req.output_dir
    cam_dir = os.path.join(out, CAM_SUBDIR)
    os.makedirs(cam_dir, exist_ok=True)
    inputs = Inputs()

    wanted = s.general.sides
    sides_to_export = ["front", "back"] if wanted in ("auto", "both") else [wanted]
    copper = {}
    for side in sides_to_export:
        layer = COPPER_LAYERS[side]
        target = os.path.join(cam_dir, side + ".gbr")
        log(tr("Exporting {} ...", "Exportiere {} ...").format(layer))
        export_layer(req, layer, target, log)
        copper[side] = target

    if wanted == "auto":
        front = gerber.layer_stats(copper["front"])
        back = gerber.layer_stats(copper["back"])
        chosen = gerber.choose_sides(front, back)
        names = {"front": tr("front (F.Cu)", "Oberseite (F.Cu)"),
                 "back": tr("back (B.Cu)", "Unterseite (B.Cu)"),
                 "both": tr("both sides", "beide Seiten")}
        log(tr("Copper with traces: {} -> milling {}.", "Kupfer mit Leiterbahnen: {} -> fräse {}.").format(
            "F.Cu {}/B.Cu {}".format(front.draws, back.draws), names[chosen]))
    else:
        chosen = wanted
        stats = gerber.layer_stats(copper[chosen]) if chosen != "both" else None
        if stats is not None and stats.empty:
            log(tr("Warning: {} is empty.", "Warnung: {} ist leer.").format(COPPER_LAYERS[chosen]))

    if chosen in ("front", "both"):
        inputs.front = _rel(copper["front"], out)
    if chosen in ("back", "both"):
        inputs.back = _rel(copper["back"], out)

    if s.general.export_outline:
        target = os.path.join(cam_dir, "outline.gbr")
        log(tr("Exporting {} ...", "Exportiere {} ...").format(OUTLINE_LAYER))
        export_layer(req, OUTLINE_LAYER, target, log)
        if gerber.layer_stats(target).draws:
            inputs.outline = _rel(target, out)
        else:
            log(tr("No board outline on Edge.Cuts - skipping outline.",
                   "Keine Platinenkontur auf Edge.Cuts - Kontur wird übersprungen."))

    if s.general.export_drill:
        log(tr("Exporting drill file ...", "Exportiere Bohrdatei ..."))
        drill = export_drill(req, cam_dir, log)
        if drill and gerber.drill_hits(drill):
            inputs.drill = _rel(drill, out)
        else:
            log(tr("No holes - skipping drilling.", "Keine Bohrungen - Bohren wird übersprungen."))

    return inputs, chosen


def clean_outputs(output_dir: str) -> None:
    """Remove G-code from earlier runs so stale files cannot be mistaken for new ones."""
    for path in glob.glob(os.path.join(output_dir, "*.ngc")):
        try:
            os.remove(path)
        except OSError:
            pass


def basename_for(req: JobRequest) -> str:
    name = req.settings.general.basename or req.board_name
    # pcb2gcode uses it in file names: keep it filesystem-safe
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name).strip("._")
    return safe or "board"


def run_job(req: JobRequest, log: Log = print) -> JobResult:
    if not req.kicad_cli:
        raise JobError(tr("kicad-cli not found.", "kicad-cli nicht gefunden."))
    if not req.pcb2gcode:
        raise JobError(tr(
            "pcb2gcode not found. Install it or set its path in the settings.",
            "pcb2gcode nicht gefunden. Bitte installieren oder den Pfad in den Einstellungen angeben.",
        ))
    if not os.path.isfile(req.board_file):
        raise JobError(tr("Board file not found: {}", "Board-Datei nicht gefunden: {}").format(req.board_file))

    os.makedirs(req.output_dir, exist_ok=True)
    inputs, sides = prepare_inputs(req, log)

    problems = validate(req.settings, inputs)
    if problems:
        raise JobError("\n".join(problem_text(p) for p in problems))

    if inputs.mills:
        log(tr("Effective tool width: {:.3f} mm", "Effektive Werkzeugbreite: {:.3f} mm").format(mill_diameter(req.settings)))

    basename = basename_for(req)
    millproject_path = os.path.join(req.output_dir, "millproject")
    with open(millproject_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render(req.settings, inputs, basename))

    clean_outputs(req.output_dir)
    log(tr("Running pcb2gcode ...", "Starte pcb2gcode ..."))
    code = _run([req.pcb2gcode], log, cwd=req.output_dir)
    if code != 0:
        raise JobError(tr("pcb2gcode failed (exit code {}). See the log above.",
                          "pcb2gcode ist fehlgeschlagen (Exit-Code {}). Details im Protokoll oben.").format(code))

    files = sorted(glob.glob(os.path.join(req.output_dir, "*.ngc")))
    if not files:
        raise JobError(tr("pcb2gcode finished but wrote no G-code.", "pcb2gcode lief durch, hat aber keinen G-Code geschrieben."))
    log(tr("Done. G-code files:", "Fertig. G-Code-Dateien:"))
    for path in files:
        log("  " + os.path.basename(path))
    return JobResult(output_dir=req.output_dir, sides=sides, inputs=inputs, files=files, millproject_path=millproject_path)
