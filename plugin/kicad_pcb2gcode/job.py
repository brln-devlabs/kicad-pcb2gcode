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
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from . import gerber, preview
from .boardfile import inner_copper_layers, read_board, special_via_kinds
from .export import (
    COPPER_LAYERS,
    OUTLINE_LAYER,
    drill_command,
    gerber_command,
    gerbers_fallback_command,
    gerbers_fallback_file,
    split_drill_files,
    split_separate_drill_files,
)
from .i18n import problem_text, tr
from .millproject import Inputs, mask_settings, mill_diameters, render, validate
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
    pcb2gcode_host: bool = False  # outside a Flatpak sandbox, via flatpak-spawn --host
    pcb2gcode_searched: List[str] = field(default_factory=list)


@dataclass
class JobResult:
    output_dir: str
    sides: str
    inputs: Inputs
    files: List[str] = field(default_factory=list)
    millproject_path: str = ""
    mask_inputs: Optional[Inputs] = None
    npth_inputs: Optional[Inputs] = None


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


def export_drill(req: JobRequest, cam_dir: str, log: Log) -> Dict[str, Optional[str]]:
    """Export the drill file(s). Returns {"merged": …} or {"pth": …, "npth": …}
    with paths below ``cam_dir`` (None where KiCad wrote nothing)."""
    separate = req.settings.drill.holes != "merged"
    drill_dir = os.path.join(cam_dir, "drill")
    shutil.rmtree(drill_dir, ignore_errors=True)
    os.makedirs(drill_dir, exist_ok=True)
    result = _quiet_run(drill_command(req.kicad_cli, req.board_file, drill_dir,
                                      req.settings.general.use_aux_origin, separate=separate))
    if result.returncode != 0:
        raise JobError(
            tr("kicad-cli could not export the drill file:\n{}", "kicad-cli konnte die Bohrdatei nicht exportieren:\n{}").format(
                (result.stdout or "").strip()
            )
        )
    if separate:
        pth, npth, layer_pairs = split_separate_drill_files(drill_dir, req.board_file)
        produced = {"pth": pth, "npth": npth}
    else:
        merged, layer_pairs = split_drill_files(drill_dir, req.board_file)
        produced = {"merged": merged}
    if layer_pairs:
        raise JobError(_special_vias_message(["blind"]) + "\n" + ", ".join(os.path.basename(f) for f in layer_pairs))
    names = {"merged": "drill.drl", "pth": "drill_pth.drl", "npth": "drill_npth.drl"}
    for old in names.values():
        stale = os.path.join(cam_dir, old)
        if os.path.isfile(stale):
            os.remove(stale)
    targets: Dict[str, Optional[str]] = {}
    for kind, path in produced.items():
        if path is None:
            targets[kind] = None
            continue
        target = os.path.join(cam_dir, names[kind])
        os.replace(path, target)
        targets[kind] = target
    shutil.rmtree(drill_dir, ignore_errors=True)
    return targets


def _special_vias_message(kinds: List[str]) -> str:
    names = {"blind": tr("blind/buried", "Blind-/Buried-"), "buried": tr("blind/buried", "Blind-/Buried-"),
             "micro": tr("micro", "Micro-")}
    label = tr(" and ", " und ").join(sorted({names.get(k, k) for k in kinds}))
    return tr(
        "The board uses {} vias. They end in inner layers and cannot be made by milling and drilling.",
        "Das Board verwendet {}Vias. Sie enden in Innenlagen und lassen sich durch Fräsen und Bohren nicht herstellen.",
    ).format(label)


def check_layer_stack(req: JobRequest, cam_dir: str, log: Log) -> None:
    """Refuse boards milling cannot make: inner layers with copper (unless the
    user opted to mill the outer layers only) and blind, buried or micro vias."""
    text = read_board(req.board_file)
    vias = special_via_kinds(text)
    if vias:
        raise JobError(_special_vias_message(vias))
    inner = inner_copper_layers(text)
    if not inner:
        return
    inner_dir = os.path.join(cam_dir, "inner")
    os.makedirs(inner_dir, exist_ok=True)
    used = []
    for layer in inner:
        target = os.path.join(inner_dir, layer.replace(".", "_") + ".gbr")
        export_layer(req, layer, target, log)
        if gerber.layer_stats(target).draws:
            used.append(layer)
    count = len(inner) + 2
    if not used:
        log(tr("Note: the board has {} copper layers, the inner layers are empty.",
               "Hinweis: Das Board hat {} Kupferlagen, die Innenlagen sind leer.").format(count))
        return
    if not req.settings.general.outer_layers_only:
        raise JobError(tr(
            "The board has {} copper layers and {} carry copper. Isolation milling can only make "
            "the top and bottom side.\nTo ignore the inner layers on purpose, tick 'Mill outer "
            "layers only' in the General tab.",
            "Das Board hat {} Kupferlagen, {} sind belegt. Isolationsfräsen kann nur Ober- und "
            "Unterseite herstellen.\nUm die Innenlagen bewusst zu ignorieren, im Reiter Allgemein "
            "„Nur Außenlagen fräsen“ ankreuzen.",
        ).format(count, ", ".join(used)))
    log(tr("Warning: ignoring copper on {} - those connections will be missing.",
           "Warnung: Kupfer auf {} wird ignoriert - diese Verbindungen fehlen.").format(", ".join(used)))


def _rel(path: str, start: str) -> str:
    return os.path.relpath(path, start).replace(os.sep, "/")


def prepare_inputs(req: JobRequest, log: Log) -> "tuple[Inputs, str, Dict[str, Optional[Inputs]]]":
    """Export everything pcb2gcode needs into ``<output>/cam``; return the
    inputs of the main run (paths relative to the output folder), the chosen
    copper sides and the inputs of the extra runs ("npth", "mask"; None where
    a run is not needed)."""
    s = req.settings
    out = req.output_dir
    cam_dir = os.path.join(out, CAM_SUBDIR)
    os.makedirs(cam_dir, exist_ok=True)
    inputs = Inputs()
    check_layer_stack(req, cam_dir, log)

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

    g = s.general
    if g.export_outline or g.zero_start or g.frame_mode:
        # Also needed when the outline is not cut: its rectangle defines the
        # origin and the flip axis.
        target = os.path.join(cam_dir, "outline.gbr")
        log(tr("Exporting {} ...", "Exportiere {} ...").format(OUTLINE_LAYER))
        export_layer(req, OUTLINE_LAYER, target, log)
        inputs.board_box = gerber.outline_box(target)
        box = inputs.board_box
        if box is not None:
            log(tr("Board outline: {:.3f} x {:.3f} mm", "Platinenkontur: {:.3f} x {:.3f} mm").format(box.width, box.height))
        if g.export_outline:
            if box is not None and gerber.layer_stats(target).draws:
                inputs.outline = _rel(target, out)
            else:
                log(tr("No board outline on Edge.Cuts - skipping outline.",
                       "Keine Platinenkontur auf Edge.Cuts - Kontur wird übersprungen."))
        if box is None and g.zero_start and not g.frame_mode:
            log(tr("No board outline: pcb2gcode places the origin itself (with a margin), "
                   "a bottom side is mirrored into negative X.",
                   "Keine Platinenkontur: pcb2gcode legt den Nullpunkt selbst fest (mit Rand), "
                   "eine Unterseite wird in den negativen X-Bereich gespiegelt."))

    npth_inputs = None
    if s.general.export_drill:
        log(tr("Exporting drill file ...", "Exportiere Bohrdatei ..."))
        drills = export_drill(req, cam_dir, log)

        def usable(kind: str) -> Optional[str]:
            path = drills.get(kind)
            return _rel(path, out) if path and gerber.drill_hits(path) else None

        mode = s.drill.holes
        if mode == "merged":
            inputs.drill = usable("merged")
        elif mode in ("pth", "npth"):
            inputs.drill = usable(mode)
            log(tr("Drilling {} holes only.", "Es werden nur {}-Löcher gebohrt.").format(mode.upper()))
        else:  # separate: plated holes in the main run, non-plated ones in a run of their own
            inputs.drill = usable("pth")
            npth = usable("npth")
            if npth:
                npth_inputs = Inputs(drill=npth, board_box=inputs.board_box)
            if not inputs.drill:
                log(tr("No plated holes (PTH).", "Keine durchkontaktierten Löcher (PTH)."))
            if not npth:
                log(tr("No non-plated holes (NPTH).", "Keine nicht durchkontaktierten Löcher (NPTH)."))
        if not inputs.drill and npth_inputs is None:
            log(tr("No holes - skipping drilling.", "Keine Bohrungen - Bohren wird übersprungen."))

    mask_inputs = None
    if s.mask.enabled:
        mask_inputs = Inputs(board_box=inputs.board_box, invert=True)
        for side, layer in (("front", "F.Mask"), ("back", "B.Mask")):
            target = os.path.join(cam_dir, "mask_{}.gbr".format(side))
            log(tr("Exporting {} ...", "Exportiere {} ...").format(layer))
            export_layer(req, layer, target, log)
            if gerber.layer_stats(target).empty:
                log(tr("{} has no openings - skipped.", "{} hat keine Öffnungen - übersprungen.").format(layer))
            else:
                setattr(mask_inputs, side, _rel(target, out))
        if not mask_inputs.mills:
            mask_inputs = None

    if g.frame_mode and inputs.outline:
        inputs.cut_side = frame_final_side(inputs, mask_inputs)
        log(tr("Flip frame: the outline is cut last, with the {} up.",
               "Wenderahmen: Die Kontur wird zum Schluss gefräst, mit der {} oben.").format(_side_name(inputs.cut_side)))

    return inputs, chosen, {"npth": npth_inputs, "mask": mask_inputs}


def _side_name(side: str) -> str:
    return tr("top side", "Oberseite") if side == "front" else tr("bottom side", "Unterseite")


def _mask_order(inputs: Inputs, mask_inputs: Optional[Inputs]) -> List[str]:
    """Mask sides in flip-frame order: the board comes back into the frame
    the way it left the machine, so after milling the bottom it starts there."""
    if mask_inputs is None:
        return []
    order = ["back", "front"] if inputs.back else ["front", "back"]
    return [side for side in order if getattr(mask_inputs, side)]


def frame_final_side(inputs: Inputs, mask_inputs: Optional[Inputs]) -> str:
    """Side facing up in the flip frame after copper, holes and solder mask -
    the outline is cut from there, so the board is not turned once more."""
    masks = _mask_order(inputs, mask_inputs)
    if masks:
        return masks[-1]
    return "back" if inputs.back else "front"


def _job_name(path: str) -> str:
    """"front", "drill", "mask_back" … from a pcb2gcode output file name."""
    stem = os.path.splitext(os.path.basename(path))[0]
    for job in ("mask_front", "mask_back", "npth_drill", "npth_milldrill"):
        if stem.endswith("_" + job):
            return job
    return stem.rsplit("_", 1)[-1]


def frame_steps(files: List[str], inputs: Inputs, flip_axis: str) -> List[str]:
    """Operator instructions for the flip frame, in machining order.

    Copper and holes first. The solder mask is applied afterwards; the board
    goes back into the frame with the bottom up (as it came off the machine),
    the bottom openings are milled, the board is turned and the top openings
    follow."""
    by_job = {_job_name(path): os.path.basename(path) for path in files}
    box = inputs.board_box
    size = "{:.2f} x {:.2f} mm".format(box.width, box.height) if box else "?"
    flip = (tr("left/right (about the vertical centre line)", "links/rechts (um die senkrechte Mittelachse)")
            if flip_axis == "leftright" else
            tr("top/bottom (about the horizontal centre line)", "oben/unten (um die waagerechte Mittelachse)"))
    lines = [
        tr("Flip frame - order of work:", "Wenderahmen - Ablauf:"),
        tr("  Blank {} in the frame, origin X0/Y0 = lower-left corner of the frame.",
           "  Rohling {} in den Rahmen, Nullpunkt X0/Y0 = linke untere Rahmenecke.").format(size),
    ]
    first = [j for j in ("front", "drill", "milldrill", "npth_drill", "npth_milldrill") if j in by_job]
    n = 1
    split = "npth_drill" in by_job or "npth_milldrill" in by_job
    for job in first:
        label = {"front": tr("top side", "Oberseite"),
                 "drill": tr("drill PTH", "bohren PTH") if split else tr("drill", "bohren"),
                 "milldrill": tr("mill holes PTH", "Löcher fräsen PTH") if split else tr("mill holes", "Löcher fräsen"),
                 "npth_drill": tr("drill NPTH", "bohren NPTH"),
                 "npth_milldrill": tr("mill holes NPTH", "Löcher fräsen NPTH")}[job]
        lines.append("  {}. {}  ({})".format(n, by_job[job], label))
        n += 1
    if "back" in by_job:
        lines.append("  {}. {}".format(n, tr("Turn the board over {} - keep the origin.",
                                            "Platine {} wenden - Nullpunkt bleibt.").format(flip)))
        n += 1
        lines.append("  {}. {}  ({})".format(n, by_job["back"], tr("bottom side", "Unterseite")))
        n += 1
    up = "back" if "back" in by_job else "front"
    if "mask_front" in by_job or "mask_back" in by_job:
        bottom_up = "back" in by_job
        order = ["mask_back", "mask_front"] if bottom_up else ["mask_front", "mask_back"]
        labels = {"mask_front": tr("solder mask top", "Lötstopp Oberseite"),
                  "mask_back": tr("solder mask bottom", "Lötstopp Unterseite")}
        present = [job for job in order if job in by_job]
        first_up = present[0].split("_", 1)[1]
        lines.append("  {}. {}".format(n, tr(
            "Apply and cure the solder mask, put the board back into the frame ({} up).",
            "Lötstopplack auftragen und aushärten, Platine wieder in den Rahmen ({} oben).").format(
                tr("bottom", "Unterseite") if first_up == "back" else tr("top", "Oberseite"))))
        n += 1
        up = present[-1].split("_", 1)[1]
        for i, job in enumerate(present):
            if i == 1:
                lines.append("  {}. {}".format(n, tr("Turn the board over {} - keep the origin.",
                                                    "Platine {} wenden - Nullpunkt bleibt.").format(flip)))
                n += 1
            lines.append("  {}. {}  ({})".format(n, by_job[job], labels[job]))
            n += 1
    if "outline" in by_job:
        side = inputs.cut_side or up
        if side != up:  # only when the files were made differently
            lines.append("  {}. {}".format(n, tr("Turn the board over {} - keep the origin.",
                                                "Platine {} wenden - Nullpunkt bleibt.").format(flip)))
            n += 1
        lines.append("  {}. {}  ({})".format(n, by_job["outline"], tr(
            "cut the outline, {} up", "Kontur ausfräsen, {} oben").format(_side_name(side))))
        n += 1
    return lines


_PAUSE = re.compile(r"^(\s*)M0+(?![0-9.])", re.IGNORECASE)


def remove_first_pause(path: str) -> bool:
    """Replace the first M0 (program pause) of a G-code file by a comment.

    pcb2gcode writes a tool-change block with M0 before every tool; the first
    one only pauses right after the operator started the file. Returns True
    if a pause was removed.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            lines = fh.readlines()
    except OSError:
        return False
    for i, line in enumerate(lines):
        stripped = line.split("(", 1)[0].split(";", 1)[0]
        if _PAUSE.match(stripped):
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            lines[i] = "(M0 removed by kicad-pcb2gcode: first tool is loaded before starting the file)" + ending
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.writelines(lines)
            return True
    return False


def rename_outputs(files: List[str], extension: str) -> List[str]:
    """Give pcb2gcode's .ngc files the chosen extension."""
    if extension == "ngc":
        return files
    renamed = []
    for path in files:
        target = os.path.splitext(path)[0] + "." + extension
        os.replace(path, target)
        renamed.append(target)
    return sorted(renamed)


def clean_outputs(output_dir: str, basename: str = "") -> None:
    """Remove G-code from earlier runs so stale files cannot be mistaken for new ones:
    every .ngc (what pcb2gcode writes) and this board's files in any other
    selectable extension."""
    from .settings import FILE_EXTENSIONS

    stale = glob.glob(os.path.join(output_dir, "*.ngc"))
    if basename:
        for ext in FILE_EXTENSIONS:
            stale += glob.glob(os.path.join(output_dir, glob.escape(basename) + "_*." + ext))
    stale += [os.path.join(output_dir, name) for name in ("STEPS.txt", "ABLAUF.txt")]
    for path in stale:
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
        except OSError:
            pass


MASK_PROJECT = "millproject_mask"
NPTH_PROJECT = "millproject_npth"


def pcb2gcode_command(req: JobRequest, *args: str) -> List[str]:
    if req.pcb2gcode_host:
        return ["flatpak-spawn", "--host", "--directory=" + req.output_dir, req.pcb2gcode, *args]
    return [req.pcb2gcode, *args]


def pcb2gcode_missing_message(searched: List[str]) -> str:
    from .export import in_flatpak

    lines = [tr("pcb2gcode not found.", "pcb2gcode nicht gefunden.")]
    if in_flatpak():
        lines.append(tr(
            "KiCad runs as a Flatpak and cannot see programs installed on the system. Allow it to start them "
            "once in a terminal, then restart KiCad:",
            "KiCad läuft als Flatpak und sieht im System installierte Programme nicht. Einmal im Terminal "
            "erlauben und KiCad neu starten:"))
        lines.append("  flatpak override --user --talk-name=org.freedesktop.Flatpak org.kicad.KiCad")
    else:
        lines.append(tr(
            "Enter its full path under General > Program (in a terminal: command -v pcb2gcode).",
            "Den vollständigen Pfad unter Allgemein > Programm eintragen (im Terminal: command -v pcb2gcode)."))
    if searched:
        lines.append(tr("Searched:", "Gesucht in:"))
        lines += ["  " + path for path in searched]
    lines.append("PATH=" + os.environ.get("PATH", ""))
    return "\n".join(lines)


def _run_pcb2gcode(req: JobRequest, cmd: List[str], log: Log) -> None:
    code = _run(cmd, log, cwd=req.output_dir)
    if code != 0:
        raise JobError(tr("pcb2gcode failed (exit code {}). See the log above.",
                          "pcb2gcode ist fehlgeschlagen (Exit-Code {}). Details im Protokoll oben.").format(code))


def basename_for(req: JobRequest) -> str:
    name = req.settings.general.basename or req.board_name
    # pcb2gcode uses it in file names: keep it filesystem-safe
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name).strip("._")
    return safe or "board"


def run_job(req: JobRequest, log: Log = print) -> JobResult:
    if not req.kicad_cli:
        raise JobError(tr("kicad-cli not found.", "kicad-cli nicht gefunden."))
    if not req.pcb2gcode:
        raise JobError(pcb2gcode_missing_message(req.pcb2gcode_searched))
    if not os.path.isfile(req.board_file):
        raise JobError(tr("Board file not found: {}", "Board-Datei nicht gefunden: {}").format(req.board_file))

    os.makedirs(req.output_dir, exist_ok=True)
    inputs, sides, extra = prepare_inputs(req, log)
    basename = basename_for(req)

    # (config file, settings, inputs, basename, label) for every pcb2gcode run
    runs = []
    if not inputs.empty or not any(extra.values()):
        runs.append(("millproject", req.settings, inputs, basename, ""))
    if extra["npth"] is not None:
        runs.append((NPTH_PROJECT, req.settings, extra["npth"], basename + "_npth", tr("NPTH: ", "NPTH: ")))
    if extra["mask"] is not None:
        runs.append((MASK_PROJECT, mask_settings(req.settings), extra["mask"], basename + "_mask",
                     tr("Solder mask: ", "Lötstopp: ")))

    lines = []
    for _, settings, run_inputs, _, label in runs:
        lines += [label + problem_text(p) for p in validate(settings, run_inputs)]
    if lines:
        raise JobError("\n".join(lines))

    if inputs.mills:
        log(tr("Mill diameters: {} mm", "Fräserdurchmesser: {} mm").format(
            ", ".join("{:g}".format(d) for d in mill_diameters(req.settings))))

    used = {config for config, *_ in runs}
    for config in ("millproject", NPTH_PROJECT, MASK_PROJECT):
        path = os.path.join(req.output_dir, config)
        if config not in used and os.path.isfile(path):
            os.remove(path)
    for config, settings, run_inputs, run_basename, _ in runs:
        with open(os.path.join(req.output_dir, config), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(settings, run_inputs, run_basename))
    millproject_path = os.path.join(req.output_dir, "millproject")

    clean_outputs(req.output_dir, basename)
    preview.clear(req.output_dir)
    run_keys = {"millproject": "main", NPTH_PROJECT: "npth", MASK_PROJECT: "mask"}
    for config, _, _, _, label in runs:
        if config == "millproject":
            log(tr("Running pcb2gcode ...", "Starte pcb2gcode ..."))
            _run_pcb2gcode(req, pcb2gcode_command(req), log)
        else:
            log(tr("Running pcb2gcode ({}) ...", "Starte pcb2gcode ({}) ...").format(label.rstrip(": ")))
            _run_pcb2gcode(req, pcb2gcode_command(req, "--config", config), log)
        # pcb2gcode's SVG names carry no board name: keep each run's images apart
        preview.collect_run(req.output_dir, run_keys[config])

    files = sorted(glob.glob(os.path.join(req.output_dir, "*.ngc")))
    files = rename_outputs(files, req.settings.general.file_extension)
    if req.settings.machine.skip_first_pause:
        removed = sum(remove_first_pause(path) for path in files)
        if removed:
            log(tr("Removed the pause at the start of {} file(s).",
                   "Pause am Dateianfang in {} Datei(en) entfernt.").format(removed))
    if not files:
        raise JobError(tr("pcb2gcode finished but wrote no G-code.", "pcb2gcode lief durch, hat aber keinen G-Code geschrieben."))
    log(tr("Done. G-code files:", "Fertig. G-Code-Dateien:"))
    for path in files:
        log("  " + os.path.basename(path))
    if req.settings.general.frame_mode:
        steps = frame_steps(files, inputs, req.settings.general.flip_axis)
        log("")
        for line in steps:
            log(line)
        try:
            with open(os.path.join(req.output_dir, tr("STEPS.txt", "ABLAUF.txt")), "w", encoding="utf-8") as fh:
                fh.write("\n".join(steps) + "\n")
        except OSError:
            pass
    return JobResult(output_dir=req.output_dir, sides=sides, inputs=inputs, files=files,
                     millproject_path=millproject_path, mask_inputs=extra["mask"], npth_inputs=extra["npth"])
