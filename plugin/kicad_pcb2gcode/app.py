"""Glue between KiCad, the settings files, the pipeline and the user interface."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from . import __version__
from .boardfile import drill_origin, read_board
from .export import find_kicad_cli, locate_pcb2gcode
from .i18n import tr
from .job import CAM_SUBDIR, JobError, JobRequest, JobResult, Log, run_job
from .settings import AppConfig, Settings, load_board_settings, load_config, save_board_settings


@dataclass
class BoardContext:
    board_path: str
    kicad_cli: Optional[str] = None
    session: Optional[object] = None  # kicad_bridge.KiCadSession when launched from KiCad

    @property
    def board_name(self) -> str:
        return os.path.splitext(os.path.basename(self.board_path))[0]

    def output_dir(self, settings: Settings) -> str:
        sub = os.path.expanduser(settings.general.output_subdir)
        if os.path.isabs(sub):
            return sub
        return os.path.join(os.path.dirname(os.path.abspath(self.board_path)), sub)

    def drill_origin_set(self) -> Optional[bool]:
        """Is KiCad's drill/place file origin set (away from 0/0)? Asks the
        running KiCad first, then reads the saved board. None if unknown."""
        if self.session is not None:
            try:
                answer = self.session.drill_origin_set()  # type: ignore[attr-defined]
            except Exception:
                answer = None
            if answer is not None:
                return answer
        text = read_board(self.board_path)
        if not text:
            return None
        return drill_origin(text) is not None

    def board_to_export(self, settings: Settings, log: Log) -> str:
        """The file kicad-cli should read: a fresh copy of the open board when
        possible, so unsaved edits are included and the user's file is untouched."""
        if self.session is not None and settings.general.include_unsaved:
            target = os.path.join(self.output_dir(settings), CAM_SUBDIR, self.board_name + ".kicad_pcb")
            try:
                ok = self.session.save_copy(target)  # type: ignore[attr-defined]
            except Exception:
                ok = False
            if ok:
                log(tr("Using the board as open in KiCad (unsaved changes included).",
                       "Verwende das Board wie in KiCad geöffnet (inkl. ungespeicherter Änderungen)."))
                return target
            log(tr("Note: this KiCad version cannot export the open board; using the saved file. "
                   "Save first (Ctrl+S) if you have unsaved changes.",
                   "Hinweis: Diese KiCad-Version kann das geöffnete Board nicht exportieren; verwende die "
                   "gespeicherte Datei. Bei ungespeicherten Änderungen vorher speichern (Strg+S)."))
        return self.board_path


def build_request(ctx: BoardContext, settings: Settings, cfg: AppConfig, log: Log) -> JobRequest:
    kicad_cli = find_kicad_cli(ctx.kicad_cli) or ""
    located = locate_pcb2gcode(cfg.pcb2gcode_path)
    pcb2gcode = located.path or ""
    if cfg.pcb2gcode_path and pcb2gcode and os.path.abspath(pcb2gcode) != os.path.abspath(os.path.expanduser(cfg.pcb2gcode_path)):
        log(tr("Configured pcb2gcode not usable, using {}", "Konfiguriertes pcb2gcode nicht nutzbar, verwende {}").format(pcb2gcode))
    if pcb2gcode:
        log(tr("pcb2gcode: {}{}", "pcb2gcode: {}{}").format(
            pcb2gcode, tr(" (outside the Flatpak sandbox)", " (außerhalb der Flatpak-Sandbox)") if located.host else ""))
    return JobRequest(
        board_file=ctx.board_to_export(settings, log),
        board_name=ctx.board_name,
        output_dir=ctx.output_dir(settings),
        kicad_cli=kicad_cli,
        pcb2gcode=pcb2gcode,
        settings=settings.copy(),
        pcb2gcode_host=located.host,
        pcb2gcode_searched=located.searched,
    )


def generate(ctx: BoardContext, settings: Settings, cfg: AppConfig, log: Log) -> JobResult:
    """Save the board's settings, then export and run pcb2gcode."""
    log("kicad-pcb2gcode {}".format(__version__))
    try:
        path = save_board_settings(settings, ctx.board_path)
        log(tr("Settings saved to {}", "Einstellungen gespeichert in {}").format(os.path.basename(path)))
    except OSError as exc:
        log(tr("Warning: could not save settings: {}", "Warnung: Einstellungen nicht gespeichert: {}").format(exc))
    if ctx.drill_origin_set() is False:
        log(drill_origin_hint(settings))
    req = build_request(ctx, settings, cfg, log)
    log(tr("Output folder: {}", "Ausgabeordner: {}").format(req.output_dir))
    return run_job(req, log)


def drill_origin_hint(settings: Settings) -> str:
    """One-line note that the drill/place origin is not set."""
    text = tr("Note: the drill/place file origin is not set (it is at 0/0).",
              "Hinweis: Der Bohr-/Platzierungsursprung ist nicht gesetzt (liegt bei 0/0).")
    g = settings.general
    if g.use_aux_origin and not (g.zero_start or g.frame_mode):
        text += " " + tr("Coordinates are measured from the sheet corner.",
                         "Koordinaten beziehen sich auf die Blattecke.")
    return text


def drill_origin_tip() -> str:
    return tr(
        "Set it in KiCad with Place > Drill/Place File Origin. It matters when 'Use drill/place file "
        "origin' is on and 'Board corner at X0/Y0' is off; with the board corner at X0/Y0 the G-code "
        "does not depend on it.",
        "Setzen in KiCad über Platzieren > Bohr-/Platzierungsursprung. Er zählt, wenn "
        "'Bohr-/Platzierungsursprung verwenden' an und 'Platinenecke auf X0/Y0' aus ist; mit der "
        "Platinenecke auf X0/Y0 hängt der G-Code nicht davon ab.",
    )


def open_folder(path: str) -> None:
    if not os.path.isdir(path):
        return
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def _show_error(message: str) -> None:
    print(message, file=sys.stderr)
    try:
        import wx

        app = wx.App(False)
        wx.MessageBox(message, "pcb2gcode", wx.OK | wx.ICON_ERROR)
        app.Destroy()
    except Exception:
        pass


def _headless(ctx: BoardContext, settings: Settings, cfg: AppConfig) -> int:
    """Run with the saved settings when no GUI toolkit is available."""
    lines = []

    def log(line: str) -> None:
        lines.append(line)
        print(line, flush=True)

    code = 0
    try:
        generate(ctx, settings, cfg, log)
    except JobError as exc:
        log(tr("Error: ", "Fehler: ") + str(exc))
        code = 1
    out = ctx.output_dir(settings)
    try:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "kicad-pcb2gcode.log"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass
    return code


def main_ipc() -> int:
    """Entry point when KiCad launches the plugin from the PCB editor toolbar."""
    from .kicad_bridge import BridgeError, connect

    try:
        session = connect()
    except BridgeError as exc:
        _show_error(str(exc))
        return 1

    cfg = load_config()
    settings = load_board_settings(cfg, session.board_path)
    ctx = BoardContext(board_path=session.board_path, kicad_cli=session.kicad_cli, session=session)

    try:
        from . import gui
    except ImportError:
        print(tr("wxPython is not available - running with saved settings.",
                 "wxPython nicht verfügbar - verwende gespeicherte Einstellungen."), flush=True)
        return _headless(ctx, settings, cfg)
    return gui.run(ctx, settings, cfg)


def main_standalone(board_path: str, use_gui: bool, overrides: Optional[dict] = None,
                    kicad_cli: Optional[str] = None, pcb2gcode: Optional[str] = None) -> int:
    """Entry point for ``python -m kicad_pcb2gcode BOARD`` (no running KiCad needed)."""
    board_path = os.path.abspath(board_path)
    if not os.path.isfile(board_path):
        print(tr("Board file not found: {}", "Board-Datei nicht gefunden: {}").format(board_path), file=sys.stderr)
        return 2
    cfg = load_config()
    if pcb2gcode:
        cfg.pcb2gcode_path = pcb2gcode
    settings = load_board_settings(cfg, board_path)
    if overrides:
        settings.update_from_dict(overrides)
    ctx = BoardContext(board_path=board_path, kicad_cli=kicad_cli)
    if use_gui:
        from . import gui

        return gui.run(ctx, settings, cfg)
    return _headless(ctx, settings, cfg)
