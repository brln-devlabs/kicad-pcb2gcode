"""Settings window (wxPython).

The plugin runs in its own process, so it owns a ``wx.App``. KiCad creates the
plugin's virtual environment with access to the system site-packages, which is
where wxPython comes from (bundled with KiCad on Windows and macOS, the
``python3-wxgtk4.0`` package on Linux).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import wx

from . import __version__
from .app import BoardContext, generate, open_folder
from .i18n import tr
from .job import JobError
from .settings import AppConfig, Settings, save_config


# -- form description ---------------------------------------------------------


@dataclass
class Field:
    section: str
    name: str
    label: Tuple[str, str]  # (en, de)
    kind: str  # float | int | bool | choice | text | multiline
    unit: str = ""
    choices: Sequence[Tuple[str, Tuple[str, str]]] = ()  # (value, (en, de))
    tip: Tuple[str, str] = ("", "")


@dataclass
class Heading:
    label: Tuple[str, str]


Row = Union[Field, Heading]

SIDE_CHOICES = (("auto", ("Automatic", "Automatisch")), ("front", ("Top", "Oberseite")), ("back", ("Bottom", "Unterseite")))

PAGES: List[Tuple[Tuple[str, str], List[Row]]] = [
    (("General", "Allgemein"), [
        Heading(("Job", "Auftrag")),
        Field("general", "sides", ("Copper sides", "Kupferseiten"), "choice", choices=(
            ("auto", ("Automatic (sides with traces)", "Automatisch (Seiten mit Leiterbahnen)")),
            ("front", ("Top (F.Cu)", "Oberseite (F.Cu)")),
            ("back", ("Bottom (B.Cu)", "Unterseite (B.Cu)")),
            ("both", ("Both sides", "Beide Seiten")),
        )),
        Field("general", "export_drill", ("Drill holes", "Löcher bohren"), "bool"),
        Field("general", "export_outline", ("Cut board outline (Edge.Cuts)", "Kontur ausfräsen (Edge.Cuts)"), "bool"),
        Field("general", "include_unsaved", ("Include unsaved changes", "Ungespeicherte Änderungen einbeziehen"), "bool",
              tip=("Exports a copy of the board as currently open in KiCad.",
                   "Exportiert eine Kopie des Boards, wie es gerade in KiCad geöffnet ist.")),
        Field("general", "outer_layers_only", ("Mill outer layers only (ignore inner layers)",
                                               "Nur Außenlagen fräsen (Innenlagen ignorieren)"), "bool",
              tip=("For boards with more than two copper layers: mill F.Cu/B.Cu anyway. "
                   "Connections on inner layers will be missing.",
                   "Für Boards mit mehr als zwei Kupferlagen: trotzdem F.Cu/B.Cu fräsen. "
                   "Verbindungen auf Innenlagen fehlen dann.")),
        Heading(("Output", "Ausgabe")),
        Field("general", "output_subdir", ("Output folder", "Ausgabeordner"), "text",
              tip=("Relative to the board file, or an absolute path.", "Relativ zur Board-Datei oder absoluter Pfad.")),
        Field("general", "basename", ("File name prefix", "Dateinamen-Präfix"), "text",
              tip=("Empty: board name.", "Leer: Name des Boards.")),
        Field("general", "open_folder_after", ("Open folder when done", "Ordner danach öffnen"), "bool"),
        Heading(("Coordinates and heights", "Koordinaten und Höhen")),
        Field("general", "zero_start", ("Board corner at X0/Y0", "Platinenecke auf X0/Y0"), "bool",
              tip=("Moves the lower-left corner of the board to the origin.",
                   "Verschiebt die linke untere Platinenecke in den Nullpunkt.")),
        Field("general", "use_aux_origin", ("Use drill/place file origin", "Bohr-/Platzierungsursprung verwenden"), "bool"),
        Field("general", "zsafe", ("Safe height", "Sicherheitshöhe"), "float", "mm"),
        Field("general", "zchange", ("Tool change height", "Werkzeugwechselhöhe"), "float", "mm"),
    ]),
    (("Isolation", "Isolation"), [
        Heading(("Tool", "Werkzeug")),
        Field("isolation", "mill_diameters", ("Available mill diameters", "Verfügbare Fräserdurchmesser"), "text", "mm",
              tip=("Width the tool cuts at the milling depth. Several, comma separated (e.g. 0.15, 0.4), "
                   "clear wider areas with additional tools.",
                   "Breite, die das Werkzeug in der Frästiefe schneidet. Mehrere mit Komma getrennt "
                   "(z. B. 0.15, 0.4) räumen breitere Bereiche mit weiteren Werkzeugen.")),
        Field("isolation", "zwork", ("Milling depth", "Frästiefe"), "float", "mm",
              tip=("Negative, e.g. -0.08", "Negativ, z. B. -0,08")),
        Heading(("Feeds and speeds", "Vorschub und Drehzahl")),
        Field("isolation", "mill_feed", ("Feed rate", "Vorschub"), "float", "mm/min"),
        Field("isolation", "mill_vertfeed", ("Plunge rate", "Eintauchvorschub"), "float", "mm/min"),
        Field("isolation", "mill_speed", ("Spindle speed", "Spindeldrehzahl"), "float", "1/min"),
        Heading(("Paths", "Bahnen")),
        Field("isolation", "isolation_width", ("Isolation width", "Isolationsbreite"), "float", "mm",
              tip=("0 = a single pass. Larger values add passes for easier soldering.",
                   "0 = ein Durchgang. Größere Werte fügen Bahnen hinzu und erleichtern das Löten.")),
        Field("isolation", "milling_overlap", ("Milling overlap", "Überlappung"), "text", "",
              tip=("Percent of the tool width (20%) or a length (0.05mm).",
                   "Prozent der Werkzeugbreite (20%) oder eine Länge (0.05mm).")),
        Field("isolation", "voronoi", ("Voronoi regions (keep most copper)", "Voronoi-Bereiche (maximal Kupfer behalten)"), "bool"),
        Field("isolation", "preserve_thermal_reliefs", ("Preserve thermal reliefs (Voronoi)", "Wärmefallen erhalten (Voronoi)"), "bool"),
        Field("isolation", "mill_feed_direction", ("Milling direction", "Fräsrichtung"), "choice", choices=(
            ("any", ("Any (fastest)", "Beliebig (am schnellsten)")),
            ("climb", ("Climb", "Gleichlauf")),
            ("conventional", ("Conventional", "Gegenlauf")),
        )),
    ]),
    (("Drilling", "Bohren"), [
        Field("drill", "zdrill", ("Drill depth", "Bohrtiefe"), "float", "mm"),
        Field("drill", "drill_feed", ("Plunge rate", "Bohrvorschub"), "float", "mm/min"),
        Field("drill", "drill_speed", ("Spindle speed", "Spindeldrehzahl"), "float", "1/min"),
        Field("drill", "drill_side", ("Drill from", "Bohren von"), "choice", choices=SIDE_CHOICES),
        Field("drill", "drills_available", ("Available drills", "Verfügbare Bohrer"), "text", "mm",
              tip=("Comma separated, e.g. 0.8, 1.0, 1.2. Empty: one tool per hole size.",
                   "Mit Komma getrennt, z. B. 0.8, 1.0, 1.2. Leer: ein Werkzeug pro Lochgröße.")),
        Field("drill", "onedrill", ("Use one drill for all holes", "Ein Bohrer für alle Löcher"), "bool"),
        Heading(("Mill large holes", "Große Löcher fräsen")),
        Field("drill", "milldrill", ("Mill holes instead of drilling", "Löcher fräsen statt bohren"), "bool"),
        Field("drill", "milldrill_diameter", ("Milling tool diameter", "Fräserdurchmesser"), "float", "mm"),
        Field("drill", "min_milldrill_hole_diameter", ("Mill holes from", "Löcher fräsen ab"), "float", "mm"),
        Field("drill", "zmilldrill", ("Milling depth", "Frästiefe"), "float", "mm"),
    ]),
    (("Outline", "Kontur"), [
        Field("outline", "cutter_diameter", ("Cutter diameter", "Fräserdurchmesser"), "float", "mm"),
        Field("outline", "zcut", ("Cut depth", "Schnitttiefe"), "float", "mm"),
        Field("outline", "cut_infeed", ("Depth per pass", "Zustellung pro Durchgang"), "float", "mm"),
        Field("outline", "cut_feed", ("Feed rate", "Vorschub"), "float", "mm/min"),
        Field("outline", "cut_vertfeed", ("Plunge rate", "Eintauchvorschub"), "float", "mm/min"),
        Field("outline", "cut_speed", ("Spindle speed", "Spindeldrehzahl"), "float", "1/min"),
        Field("outline", "cut_side", ("Cut from", "Fräsen von"), "choice", choices=SIDE_CHOICES),
        Heading(("Holding tabs", "Haltestege")),
        Field("outline", "bridgesnum", ("Number of tabs", "Anzahl"), "int"),
        Field("outline", "bridges", ("Tab width", "Stegbreite"), "float", "mm"),
        Field("outline", "zbridges", ("Cut depth at tabs", "Schnitttiefe an Stegen"), "float", "mm"),
    ]),
    (("Machine", "Maschine"), [
        Heading(("G-code dialect (defaults suit GRBL)", "G-Code-Dialekt (Voreinstellung passt für GRBL)")),
        Field("machine", "nog64", ("No G64 (path blending)", "Kein G64 (Bahnüberschleifen)"), "bool"),
        Field("machine", "nog81", ("No G81 (drilling cycle)", "Kein G81 (Bohrzyklus)"), "bool"),
        Field("machine", "nog91_1", ("No G91.1", "Kein G91.1"), "bool"),
        Field("machine", "nom6", ("No M6 (tool change)", "Kein M6 (Werkzeugwechsel)"), "bool",
              tip=("GRBL 1.1 rejects M6. Turn off for grblHAL with a tool changer.",
                   "GRBL 1.1 lehnt M6 ab. Für grblHAL mit Werkzeugwechsler ausschalten.")),
        Heading(("Extra pcb2gcode options", "Zusätzliche pcb2gcode-Optionen")),
        Field("machine", "extra_options", ("One option per line", "Eine Option pro Zeile"), "multiline",
              tip=("e.g. spinup-time=3 - overrides generated options of the same name.",
                   "z. B. spinup-time=3 - überschreibt gleichnamige erzeugte Optionen.")),
    ]),
]


def _t(pair: Tuple[str, str]) -> str:
    return tr(pair[0], pair[1])


def _parse_number(text: str) -> float:
    return float(text.strip().replace(",", "."))


def _format_number(value: float) -> str:
    text = "{:.4f}".format(value).rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


# -- dialog -------------------------------------------------------------------


class Pcb2GcodeDialog(wx.Dialog):
    def __init__(self, parent: Optional[wx.Window], ctx: BoardContext, settings: Settings, cfg: AppConfig):
        super().__init__(
            parent,
            title="pcb2gcode – " + ctx.board_name,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.ctx = ctx
        self.cfg = cfg
        self.loaded = settings.copy()
        self.controls: Dict[Tuple[str, str], Tuple[Field, wx.Window]] = {}
        self.running = False
        self.last_output: Optional[str] = None

        root = wx.BoxSizer(wx.VERTICAL)

        header = wx.StaticText(self, label=ctx.board_path)
        header.SetToolTip(ctx.board_path)
        root.Add(header, 0, wx.ALL | wx.EXPAND, 8)

        self.notebook = wx.Notebook(self)
        for title, rows in PAGES:
            self.notebook.AddPage(self._build_page(title, rows), _t(title))
        root.Add(self.notebook, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

        self.log_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL, size=(-1, 150))
        self.log_ctrl.SetFont(wx.Font(wx.FontInfo(9).Family(wx.FONTFAMILY_TELETYPE)))
        root.Add(self.log_ctrl, 0, wx.ALL | wx.EXPAND, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self.btn_generate = wx.Button(self, label=tr("Generate G-code", "G-Code erzeugen"))
        self.btn_generate.SetDefault()
        self.btn_folder = wx.Button(self, label=tr("Open output folder", "Ausgabeordner öffnen"))
        self.btn_defaults = wx.Button(self, label=tr("Save as default", "Als Standard speichern"))
        self.btn_reset = wx.Button(self, label=tr("Reset", "Zurücksetzen"))
        self.btn_reset.SetToolTip(tr("Load the built-in defaults into the form.", "Lädt die eingebauten Voreinstellungen ins Formular."))
        self.btn_close = wx.Button(self, wx.ID_CLOSE, label=tr("Close", "Schließen"))
        buttons.Add(self.btn_generate, 0, wx.RIGHT, 6)
        buttons.Add(self.btn_folder, 0, wx.RIGHT, 6)
        buttons.AddStretchSpacer(1)
        buttons.Add(self.btn_defaults, 0, wx.RIGHT, 6)
        buttons.Add(self.btn_reset, 0, wx.RIGHT, 6)
        buttons.Add(self.btn_close, 0)
        root.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)

        self.SetSizer(root)
        self.SetMinSize(wx.Size(640, 600))
        self.SetSize(wx.Size(720, 720))
        self.CentreOnScreen()

        self.btn_generate.Bind(wx.EVT_BUTTON, self.on_generate)
        self.btn_folder.Bind(wx.EVT_BUTTON, self.on_open_folder)
        self.btn_defaults.Bind(wx.EVT_BUTTON, self.on_save_defaults)
        self.btn_reset.Bind(wx.EVT_BUTTON, self.on_reset)
        self.btn_close.Bind(wx.EVT_BUTTON, lambda evt: self.Close())
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.set_form(settings)
        self._update_folder_button()
        self._log(tr("Ready. kicad-pcb2gcode {}", "Bereit. kicad-pcb2gcode {}").format(__version__))

    # -- building -------------------------------------------------------

    def _build_page(self, title: Tuple[str, str], rows: List[Row]) -> wx.Window:
        page = wx.ScrolledWindow(self.notebook)
        page.SetScrollRate(0, 12)
        grid = wx.FlexGridSizer(0, 3, 6, 10)
        grid.AddGrowableCol(1, 1)

        if title[0] == "General":
            self._add_pcb2gcode_row(page, grid)

        for row in rows:
            if isinstance(row, Heading):
                label = wx.StaticText(page, label=_t(row.label))
                font = label.GetFont()
                font.SetWeight(wx.FONTWEIGHT_BOLD)
                label.SetFont(font)
                grid.Add(label, 0, wx.TOP, 8)
                grid.AddSpacer(0)
                grid.AddSpacer(0)
                continue
            self._add_field(page, grid, row)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(grid, 1, wx.ALL | wx.EXPAND, 10)
        page.SetSizer(outer)
        return page

    def _add_pcb2gcode_row(self, page: wx.Window, grid: wx.FlexGridSizer) -> None:
        heading = wx.StaticText(page, label="pcb2gcode")
        font = heading.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        heading.SetFont(font)
        grid.Add(heading, 0)
        grid.AddSpacer(0)
        grid.AddSpacer(0)
        grid.Add(wx.StaticText(page, label=tr("Program", "Programm")), 0, wx.ALIGN_CENTER_VERTICAL)
        self.pcb2gcode_ctrl = wx.TextCtrl(page, value=self.cfg.pcb2gcode_path)
        self.pcb2gcode_ctrl.SetHint(tr("Empty: search PATH", "Leer: im PATH suchen"))
        grid.Add(self.pcb2gcode_ctrl, 1, wx.EXPAND)
        browse = wx.Button(page, label="…", size=wx.Size(36, -1))
        browse.SetToolTip(tr("Choose the pcb2gcode program", "pcb2gcode-Programm auswählen"))
        browse.Bind(wx.EVT_BUTTON, self.on_browse_pcb2gcode)
        grid.Add(browse, 0)

    def _add_field(self, page: wx.Window, grid: wx.FlexGridSizer, field: Field) -> None:
        tip = _t(field.tip) if field.tip[0] else ""
        if field.kind == "bool":
            grid.AddSpacer(0)
            ctrl: wx.Window = wx.CheckBox(page, label=_t(field.label))
            ctrl.Bind(wx.EVT_CHECKBOX, self.on_form_changed)
            grid.Add(ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.AddSpacer(0)
        else:
            grid.Add(wx.StaticText(page, label=_t(field.label)), 0, wx.ALIGN_CENTER_VERTICAL)
            if field.kind == "choice":
                ctrl = wx.Choice(page, choices=[_t(label) for _, label in field.choices])
                ctrl.Bind(wx.EVT_CHOICE, self.on_form_changed)
            elif field.kind == "multiline":
                ctrl = wx.TextCtrl(page, style=wx.TE_MULTILINE, size=wx.Size(-1, 90))
            else:
                ctrl = wx.TextCtrl(page)
                if field.kind in ("float", "int"):
                    ctrl.Bind(wx.EVT_TEXT, self.on_form_changed)
            grid.Add(ctrl, 1, wx.EXPAND)
            grid.Add(wx.StaticText(page, label=field.unit), 0, wx.ALIGN_CENTER_VERTICAL)
        if tip:
            ctrl.SetToolTip(tip)
        self.controls[(field.section, field.name)] = (field, ctrl)

    # -- form <-> settings ----------------------------------------------

    def set_form(self, settings: Settings) -> None:
        for (section, name), (field, ctrl) in self.controls.items():
            value = getattr(getattr(settings, section), name)
            if field.kind == "bool":
                ctrl.SetValue(bool(value))
            elif field.kind == "choice":
                values = [v for v, _ in field.choices]
                ctrl.SetSelection(values.index(value) if value in values else 0)
            elif field.kind in ("float", "int"):
                ctrl.ChangeValue(_format_number(value) if field.kind == "float" else str(value))
            else:
                ctrl.ChangeValue(str(value))
        self.on_form_changed(None)

    def read_form(self) -> Tuple[Settings, List[str]]:
        """Settings from the form plus a list of fields that could not be parsed."""
        settings = Settings()
        errors: List[str] = []
        for (section, name), (field, ctrl) in self.controls.items():
            target = getattr(settings, section)
            value: Any
            if field.kind == "bool":
                value = bool(ctrl.GetValue())
            elif field.kind == "choice":
                index = ctrl.GetSelection()
                value = field.choices[index][0] if index >= 0 else field.choices[0][0]
            elif field.kind in ("float", "int"):
                try:
                    number = _parse_number(ctrl.GetValue())
                    value = int(round(number)) if field.kind == "int" else number
                except ValueError:
                    errors.append(_t(field.label))
                    continue
            else:
                value = ctrl.GetValue()
            setattr(target, name, value)
        settings.sanitize()
        return settings, errors

    def on_form_changed(self, event: Optional[wx.Event]) -> None:
        if event is not None:
            event.Skip()
        voronoi = self.controls[("isolation", "voronoi")][1].GetValue()
        self.controls[("isolation", "preserve_thermal_reliefs")][1].Enable(bool(voronoi))

    # -- actions ----------------------------------------------------------

    def _log(self, line: str) -> None:
        self.log_ctrl.AppendText(line + "\n")

    def _update_folder_button(self) -> None:
        settings, _ = self.read_form()
        self.btn_folder.Enable(os.path.isdir(self.ctx.output_dir(settings)))

    def _set_running(self, running: bool) -> None:
        self.running = running
        for btn in (self.btn_generate, self.btn_defaults, self.btn_reset, self.btn_close):
            btn.Enable(not running)
        self.notebook.Enable(not running)
        self.SetCursor(wx.Cursor(wx.CURSOR_WAIT if running else wx.CURSOR_DEFAULT))

    def _apply_pcb2gcode_path(self) -> None:
        path = self.pcb2gcode_ctrl.GetValue().strip()
        if path != self.cfg.pcb2gcode_path:
            self.cfg.pcb2gcode_path = path
            try:
                save_config(self.cfg)
            except OSError as exc:
                self._log(tr("Warning: could not save configuration: {}", "Warnung: Konfiguration nicht gespeichert: {}").format(exc))

    def on_browse_pcb2gcode(self, event: wx.Event) -> None:
        wildcard = "pcb2gcode (*.exe)|*.exe|*.*|*.*" if os.name == "nt" else "*"
        with wx.FileDialog(self, tr("Choose pcb2gcode", "pcb2gcode auswählen"), wildcard=wildcard,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.pcb2gcode_ctrl.SetValue(dlg.GetPath())

    def on_generate(self, event: wx.Event) -> None:
        settings, errors = self.read_form()
        if errors:
            wx.MessageBox(
                tr("Please enter numbers in these fields:\n", "Bitte Zahlen in diese Felder eintragen:\n") + "\n".join(errors),
                "pcb2gcode", wx.OK | wx.ICON_WARNING, self)
            return
        self._apply_pcb2gcode_path()
        self.loaded = settings.copy()
        self.log_ctrl.Clear()
        self._set_running(True)
        cfg = self.cfg

        def log(line: str) -> None:
            wx.CallAfter(self._log, line)

        def work() -> None:
            try:
                result = generate(self.ctx, settings, cfg, log)
                wx.CallAfter(self._finished, result.output_dir, None, settings)
            except JobError as exc:
                wx.CallAfter(self._finished, None, str(exc), settings)
            except Exception as exc:  # unexpected: show it rather than die silently
                wx.CallAfter(self._finished, None, "{}: {}".format(type(exc).__name__, exc), settings)

        threading.Thread(target=work, daemon=True).start()

    def _finished(self, output_dir: Optional[str], error: Optional[str], settings: Settings) -> None:
        self._set_running(False)
        self._update_folder_button()
        if error:
            self._log("")
            self._log(tr("Error: ", "Fehler: ") + error)
            wx.MessageBox(error, tr("pcb2gcode – error", "pcb2gcode – Fehler"), wx.OK | wx.ICON_ERROR, self)
            return
        self.last_output = output_dir
        if output_dir and settings.general.open_folder_after:
            open_folder(output_dir)

    def on_open_folder(self, event: wx.Event) -> None:
        settings, _ = self.read_form()
        open_folder(self.last_output or self.ctx.output_dir(settings))

    def on_save_defaults(self, event: wx.Event) -> None:
        settings, errors = self.read_form()
        if errors:
            wx.MessageBox("\n".join(errors), "pcb2gcode", wx.OK | wx.ICON_WARNING, self)
            return
        self.cfg.defaults = settings.copy()
        self.cfg.pcb2gcode_path = self.pcb2gcode_ctrl.GetValue().strip()
        try:
            save_config(self.cfg)
            self._log(tr("Saved as default for new boards.", "Als Standard für neue Boards gespeichert."))
        except OSError as exc:
            wx.MessageBox(str(exc), "pcb2gcode", wx.OK | wx.ICON_ERROR, self)

    def on_reset(self, event: wx.Event) -> None:
        self.set_form(Settings())
        self._log(tr("Built-in defaults loaded (not saved yet).", "Eingebaute Voreinstellungen geladen (noch nicht gespeichert)."))

    def on_close(self, event: wx.CloseEvent) -> None:
        if self.running and event.CanVeto():
            event.Veto()
            return
        settings, errors = self.read_form()
        if not errors and settings.to_dict() != self.loaded.to_dict():
            try:
                from .settings import save_board_settings

                save_board_settings(settings, self.ctx.board_path)
            except OSError:
                pass
        self._apply_pcb2gcode_path()
        if self.IsModal():
            self.EndModal(wx.ID_CLOSE)
        else:
            self.Destroy()


def run(ctx: BoardContext, settings: Settings, cfg: AppConfig) -> int:
    app = wx.App(False)
    dlg = Pcb2GcodeDialog(None, ctx, settings, cfg)
    app.SetTopWindow(dlg)
    dlg.Raise()
    dlg.ShowModal()
    dlg.Destroy()
    return 0
