"""Talking to the running KiCad through the IPC API (kicad-python / ``kipy``).

Everything here is defensive: the API is young and differs slightly between
KiCad 9 and 10, so each step has a fallback and failures turn into messages
instead of tracebacks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from .i18n import tr


class BridgeError(Exception):
    """Connecting to KiCad or finding the board failed; message is for the user."""


@dataclass
class KiCadSession:
    kicad: Any
    board: Any
    board_path: str  # the .kicad_pcb file on disk
    kicad_cli: Optional[str]
    version: str = ""

    @property
    def board_name(self) -> str:
        return os.path.splitext(os.path.basename(self.board_path))[0]

    @property
    def project_dir(self) -> str:
        return os.path.dirname(self.board_path)

    def save_copy(self, target: str) -> bool:
        """Ask KiCad to write the open board, unsaved edits included, to ``target``.

        Returns False if this KiCad / kicad-python cannot do it; the caller then
        exports the file on disk instead.
        """
        save_as = getattr(self.board, "save_as", None)
        if save_as is None:
            return False
        os.makedirs(os.path.dirname(target), exist_ok=True)
        attempts = (
            lambda: save_as(target, overwrite=True, include_project=True),
            lambda: save_as(target, True, True),
            lambda: save_as(target),
        )
        for attempt in attempts:
            try:
                attempt()
            except TypeError:
                continue  # different signature, try the next form
            except Exception:
                return False
            return os.path.isfile(target)
        return False


def _first(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return ""


def resolve_board_path(board: Any) -> str:
    """Absolute path of the board file, assembled from what the API offers."""
    doc = getattr(board, "document", None)
    filename = _first(getattr(doc, "board_filename", None), getattr(board, "name", None))
    project_dir = ""
    project = getattr(doc, "project", None)
    project_dir = _first(getattr(project, "path", None))
    if not project_dir:
        try:
            project_dir = _first(getattr(board.get_project(), "path", None))
        except Exception:
            project_dir = ""
    if not project_dir:
        project_dir = os.environ.get("KIPRJMOD", "")
    if project_dir.endswith(".kicad_pro"):
        project_dir = os.path.dirname(project_dir)

    if filename and os.path.isabs(filename):
        return filename
    if filename and project_dir:
        return os.path.join(project_dir, filename)
    if project_dir:
        # Last resort: the only board in the project folder.
        boards = [f for f in os.listdir(project_dir) if f.endswith(".kicad_pcb")]
        if len(boards) == 1:
            return os.path.join(project_dir, boards[0])
    return ""


def connect() -> KiCadSession:
    try:
        from kipy import KiCad
    except ImportError as exc:
        raise BridgeError(tr(
            "The kicad-python package is missing. Use Preferences > Plugins > "
            "'Recreate Plugin Environment' in KiCad.",
            "Das Paket kicad-python fehlt. In KiCad unter Einstellungen > Plugins "
            "'Plugin-Umgebung neu erstellen' ausführen.",
        )) from exc

    try:
        kicad = KiCad(client_name="kicad-pcb2gcode", timeout_ms=15000)
    except TypeError:
        kicad = KiCad()
    except Exception as exc:
        raise BridgeError(tr(
            "Cannot connect to KiCad. Enable Preferences > Plugins > 'Enable KiCad API'.\n{}",
            "Keine Verbindung zu KiCad. Bitte Einstellungen > Plugins > 'KiCad-API aktivieren' einschalten.\n{}",
        ).format(exc)) from exc

    try:
        board = kicad.get_board()
    except Exception as exc:
        raise BridgeError(tr(
            "No board is open in the PCB editor.\n{}", "Im Leiterplatteneditor ist kein Board geöffnet.\n{}"
        ).format(exc)) from exc

    board_path = resolve_board_path(board)
    if not board_path:
        raise BridgeError(tr(
            "The board has not been saved yet. Save it once, then run the plugin again.",
            "Das Board wurde noch nie gespeichert. Bitte einmal speichern und das Plugin erneut starten.",
        ))

    kicad_cli = None
    try:
        kicad_cli = kicad.get_kicad_binary_path("kicad-cli") or None
    except Exception:
        kicad_cli = None

    version = ""
    try:
        version = str(kicad.get_version())
    except Exception:
        pass

    return KiCadSession(kicad=kicad, board=board, board_path=board_path, kicad_cli=kicad_cli, version=version)
