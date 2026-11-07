"""Settings window (wxPython).

The plugin runs in its own process, so it owns a ``wx.App``. KiCad creates the
plugin's virtual environment with access to the system site-packages, which is
where wxPython comes from (bundled with KiCad on Windows and macOS, the
``python3-wxgtk4.0`` package on Linux).
"""

from __future__ import annotations

import os
import pathlib
import threading
import time
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

import wx

try:  # SVG rendering arrived with wxPython 4.1 (KiCad 9/10 bundle 4.2)
    import wx.svg

    HAVE_SVG = True
except ImportError:
    HAVE_SVG = False

from . import __version__
from .app import BoardContext, drill_origin_tip, generate, open_folder
from .form import PAGES, Field, Heading, Row, format_number, parse_number, label_text
from .i18n import tr
from .job import JobError
from . import vector
from .preview import ease_fraction, ease_scale, fit_view, list_previews, wheel_factor, zoom_at
from .settings import AppConfig, Settings, save_config


# -- preview ------------------------------------------------------------------


class _WxScene:
    """The preview image as ready-made ``wx.GraphicsPath`` objects with their
    pens and brushes, built once per image and drawn as vectors every frame."""

    def __init__(self, svg: Any):
        renderer = wx.GraphicsRenderer.GetDefaultRenderer()
        items = vector.build_scene(svg.shapes, (svg.width, svg.height))
        pens: Dict[Any, Any] = {}
        brushes: Dict[Any, Any] = {}
        self.items: List[Tuple[vector.Item, Any, Any, Any, int]] = []
        for item in items:
            style = item.style
            pen = brush = None
            if style.stroke is not None:
                key = (style.stroke, style.width, style.join, style.cap)
                if key not in pens:
                    pens[key] = self._pen(renderer, style)
                pen = pens[key]
            if style.fill is not None:
                if style.fill not in brushes:
                    brushes[style.fill] = renderer.CreateBrush(wx.Brush(wx.Colour(*style.fill)))
                brush = brushes[style.fill]
            path = renderer.CreatePath()
            for closed, (sx, sy), segments in item.paths:
                path.MoveToPoint(sx, sy)
                for seg in segments:
                    if len(seg) == 2:
                        path.AddLineToPoint(seg[0], seg[1])
                    else:
                        path.AddCurveToPoint(*seg)
                if closed:
                    path.CloseSubpath()
            rule = wx.ODDEVEN_RULE if style.evenodd else wx.WINDING_RULE
            self.items.append((item, path, pen, brush, rule))

    @staticmethod
    def _pen(renderer: Any, style: "vector.Style") -> Any:
        colour = wx.Colour(*style.stroke)
        join = {vector.JOIN_ROUND: wx.JOIN_ROUND, vector.JOIN_BEVEL: wx.JOIN_BEVEL}.get(style.join, wx.JOIN_MITER)
        cap = {vector.CAP_ROUND: wx.CAP_ROUND, vector.CAP_SQUARE: wx.CAP_PROJECTING}.get(style.cap, wx.CAP_BUTT)
        try:
            return renderer.CreatePen(wx.GraphicsPenInfo(colour).Width(style.width).Join(join).Cap(cap))
        except AttributeError:  # wx older than 3.1.1: integer widths only
            pen = wx.Pen(colour, max(1, int(round(style.width))))
            pen.SetJoin(join)
            pen.SetCap(cap)
            return renderer.CreatePen(pen)

    def draw(self, gc: Any, view: Tuple[float, float, float, float]) -> None:
        current_pen = current_brush = None
        for item, path, pen, brush, rule in self.items:
            if not vector.visible(item, view):
                continue
            if brush is not None:
                if brush is not current_brush:
                    gc.SetBrush(brush)
                    current_brush = brush
                gc.FillPath(path, rule)
            if pen is not None:
                if pen is not current_pen:
                    gc.SetPen(pen)
                    current_pen = pen
                gc.StrokePath(path)


class PreviewPanel(wx.Panel):
    """Shows the SVG images pcb2gcode wrote: copper with tool paths, holes,
    outline, solder mask and clearance problems, like pcb2gcodeGUI does.

    Mouse wheel zooms smoothly around the pointer, dragging with the left or
    middle button moves the view, a double click fits the image again. Every
    frame - also while zooming and dragging - is drawn as vectors from paths
    prepared once per image (see ``vector``), so it is sharp at any zoom.
    """

    FRAME_MS = 10
    CACHE = 8  # prepared images kept, so switching layers is instant

    def __init__(self, parent: wx.Window):
        super().__init__(parent)
        self.entries: List[Tuple[str, str]] = []
        self._svg: Any = None
        self._scene: Optional[_WxScene] = None
        self._scenes: Dict[Tuple[str, float, int], Optional[_WxScene]] = {}
        self._path = ""
        # view: screen position of the image's (0, 0) and pixels per image unit
        self._origin = (0.0, 0.0)
        self._scale = 1.0
        self._fit_scale = 1.0
        self._fitted = True  # follow window size until the user zooms or pans
        self._drag: Optional[Tuple[Tuple[int, int], Tuple[float, float]]] = None
        # zoom animation: target scale, the image point that stays under the
        # pointer, and the time of the last frame
        self._target = 1.0
        self._anchor: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None
        self._last_frame = 0.0

        title = wx.StaticText(self, label=tr("Preview", "Vorschau"))
        font = title.GetFont()
        font.SetWeight(wx.FONTWEIGHT_BOLD)
        title.SetFont(font)
        self.choice = wx.Choice(self, choices=[])
        self.btn_fit = wx.Button(self, label="⤢", size=wx.Size(36, -1))
        self.btn_fit.SetToolTip(tr("Fit to window (or double-click)", "Einpassen (oder Doppelklick)"))
        self.btn_open = wx.Button(self, label="↗", size=wx.Size(36, -1))
        self.btn_open.SetToolTip(tr("Open the image in the web browser", "Bild im Webbrowser öffnen"))
        self.canvas = wx.Panel(self, style=wx.BORDER_SIMPLE | wx.WANTS_CHARS)
        self.canvas.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.canvas.SetMinSize(wx.Size(320, 240))
        self.canvas.SetToolTip(tr("Mouse wheel: zoom - drag: move - double-click: fit",
                                  "Mausrad: zoomen - ziehen: verschieben - Doppelklick: einpassen"))

        top = wx.BoxSizer(wx.HORIZONTAL)
        top.Add(self.choice, 1, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 6)
        top.Add(self.btn_fit, 0, wx.RIGHT, 4)
        top.Add(self.btn_open, 0)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(title, 0, wx.BOTTOM, 6)
        sizer.Add(top, 0, wx.EXPAND | wx.BOTTOM, 6)
        sizer.Add(self.canvas, 1, wx.EXPAND)
        self.SetSizer(sizer)

        self._anim = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_frame, self._anim)

        self.choice.Bind(wx.EVT_CHOICE, lambda evt: self._load())
        self.btn_fit.Bind(wx.EVT_BUTTON, lambda evt: self.fit())
        self.btn_open.Bind(wx.EVT_BUTTON, self.on_open)
        self.canvas.Bind(wx.EVT_PAINT, self.on_paint)
        self.canvas.Bind(wx.EVT_SIZE, self.on_size)
        self.canvas.Bind(wx.EVT_MOUSEWHEEL, self.on_wheel)
        for evt in (wx.EVT_LEFT_DOWN, wx.EVT_MIDDLE_DOWN):
            self.canvas.Bind(evt, self.on_press)
        for evt in (wx.EVT_LEFT_UP, wx.EVT_MIDDLE_UP):
            self.canvas.Bind(evt, self.on_release)
        self.canvas.Bind(wx.EVT_MOTION, self.on_motion)
        self.canvas.Bind(wx.EVT_LEFT_DCLICK, lambda evt: self.fit())
        self.canvas.Bind(wx.EVT_MOUSE_CAPTURE_LOST, lambda evt: self._end_drag())
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        self.show([])

    # -- content ----------------------------------------------------------

    def show(self, entries: List[Tuple[str, str]]) -> None:
        """Replace the list of images; keeps the selected layer if it is still there."""
        previous = self.choice.GetStringSelection() if self.entries else ""
        self.entries = entries
        self.choice.Clear()
        for label, _ in entries:
            self.choice.Append(label)
        labels = [label for label, _ in entries]
        if entries:
            self.choice.SetSelection(labels.index(previous) if previous in labels else 0)
        for ctrl in (self.choice, self.btn_open, self.btn_fit):
            ctrl.Enable(bool(entries))
        self._load()

    def _load(self) -> None:
        index = self.choice.GetSelection()
        self._path = self.entries[index][1] if self.entries and index >= 0 else ""
        self._svg = None
        self._scene = None
        if self._path and HAVE_SVG:
            try:
                self._svg = wx.svg.SVGimage.CreateFromFile(self._path)
            except Exception:
                self._svg = None
            if self._has_image():
                self._scene = self._prepare(self._path)
        self.fit()

    def _prepare(self, path: str) -> Optional[_WxScene]:
        """Paths of the image, from the cache when the file is unchanged."""
        try:
            stat = os.stat(path)
            key = (path, stat.st_mtime, stat.st_size)
        except OSError:
            key = (path, 0.0, 0)
        if key not in self._scenes:
            busy = wx.BusyCursor()
            try:
                scene: Optional[_WxScene] = _WxScene(self._svg)
            except Exception:
                scene = None  # unusual wx.svg: draw with RenderToGC instead
            del busy
            for old in [k for k in self._scenes if k[0] == path]:
                del self._scenes[old]
            while len(self._scenes) >= self.CACHE:
                del self._scenes[next(iter(self._scenes))]
            self._scenes[key] = scene
        return self._scenes[key]

    def _has_image(self) -> bool:
        return self._svg is not None and self._svg.width > 0 and self._svg.height > 0

    def _message(self) -> str:
        if not self.entries:
            return tr("No preview yet - it appears after generating.",
                      "Noch keine Vorschau - sie erscheint nach dem Erzeugen.")
        if not HAVE_SVG:
            return tr("The preview needs wxPython 4.1 or newer.\nOpen the image with ↗.",
                      "Die Vorschau braucht wxPython 4.1 oder neuer.\nBild mit ↗ öffnen.")
        return tr("This image cannot be shown.", "Dieses Bild lässt sich nicht anzeigen.")

    # -- view -------------------------------------------------------------

    def _redraw(self) -> None:
        self.canvas.Refresh(eraseBackground=False)

    def fit(self) -> None:
        self._anim.Stop()
        self._anchor = None
        width, height = self.canvas.GetClientSize()
        if self._has_image():
            ox, oy, scale = fit_view(self._svg.width, self._svg.height, width, height)
        else:
            ox, oy, scale = 0.0, 0.0, 1.0
        self._origin, self._scale, self._fit_scale, self._target = (ox, oy), scale, scale, scale
        self._fitted = True
        self._redraw()

    def on_size(self, event: wx.SizeEvent) -> None:
        event.Skip()
        if self._fitted:
            self.fit()
        else:
            self._redraw()

    def on_wheel(self, event: wx.MouseEvent) -> None:
        if not self._has_image():
            return
        x, y = event.GetPosition()
        # the image point under the pointer stays there during the whole glide
        image_point = ((x - self._origin[0]) / self._scale, (y - self._origin[1]) / self._scale)
        self._anchor = ((float(x), float(y)), image_point)
        factor = wheel_factor(event.GetWheelRotation(), event.GetWheelDelta())
        self._target = zoom_at(0.0, 0.0, self._target, 0.0, 0.0, factor, self._fit_scale)[2]
        self._fitted = False
        if not self._anim.IsRunning():
            self._last_frame = time.perf_counter()
            self._anim.Start(self.FRAME_MS)

    def on_frame(self, event: wx.TimerEvent) -> None:
        now = time.perf_counter()
        # time based: a slow frame moves further, so the glide keeps its pace
        fraction = ease_fraction(min(now - self._last_frame, 0.1))
        self._last_frame = now
        self._scale, done = ease_scale(self._scale, self._target, fraction)
        if self._anchor is not None:
            (sx, sy), (ix, iy) = self._anchor
            self._origin = (sx - ix * self._scale, sy - iy * self._scale)
        if done:
            self._anim.Stop()
            self._anchor = None
        self._redraw()

    def _finish_zoom(self) -> None:
        """Stop the glide where it is, so a drag starts from what is on screen."""
        if self._anim.IsRunning():
            self._anim.Stop()
            self._target = self._scale
            self._anchor = None

    def on_press(self, event: wx.MouseEvent) -> None:
        if not self._has_image():
            return
        self._finish_zoom()
        self._drag = (tuple(event.GetPosition()), self._origin)
        self.canvas.SetCursor(wx.Cursor(wx.CURSOR_SIZING))
        if not self.canvas.HasCapture():
            self.canvas.CaptureMouse()

    def on_motion(self, event: wx.MouseEvent) -> None:
        if self._drag is None or not event.Dragging():
            return
        (sx, sy), (ox, oy) = self._drag
        x, y = event.GetPosition()
        self._origin = (ox + x - sx, oy + y - sy)
        self._fitted = False
        self._redraw()

    def on_release(self, event: wx.MouseEvent) -> None:
        if self._drag is not None:
            self._end_drag()

    def _end_drag(self) -> None:
        self._drag = None
        self.canvas.SetCursor(wx.NullCursor)
        if self.canvas.HasCapture():
            self.canvas.ReleaseMouse()

    def on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self:
            self._anim.Stop()
        event.Skip()

    # -- drawing ----------------------------------------------------------

    def on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.AutoBufferedPaintDC(self.canvas)
        dc.SetBackground(wx.Brush(wx.Colour(255, 255, 255)))
        dc.Clear()
        width, height = self.canvas.GetClientSize()
        if not self._has_image():
            dc.SetTextForeground(wx.Colour(120, 120, 120))
            dc.DrawLabel(self._message(), wx.Rect(0, 0, width, height), wx.ALIGN_CENTER)
            return
        gc = wx.GraphicsContext.Create(dc)
        if gc is not None:
            gc.SetAntialiasMode(wx.ANTIALIAS_DEFAULT)
            gc.Translate(self._origin[0], self._origin[1])
            gc.Scale(self._scale, self._scale)
            if self._scene is not None:
                self._scene.draw(gc, vector.view_rect(self._origin, self._scale, width, height))
            else:
                self._svg.RenderToGC(gc)
            del gc
        if not self._fitted:
            zoom = "{:.0f} %".format(100.0 * self._scale / self._fit_scale)
            dc.SetTextForeground(wx.Colour(120, 120, 120))
            tw, th = dc.GetTextExtent(zoom)
            dc.DrawText(zoom, width - tw - 6, height - th - 4)

    def on_open(self, event: wx.Event) -> None:
        if self._path and os.path.isfile(self._path):
            webbrowser.open(pathlib.Path(self._path).resolve().as_uri())


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
        root.Add(header, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 8)

        # Subtle note, not a dialog: the drill/place origin is still at 0/0.
        self.origin_hint: Optional[wx.StaticText] = None
        if ctx.drill_origin_set() is False:
            hint = wx.StaticText(self, label="\u26a0 " + tr(
                "Drill/place file origin is not set", "Bohr-/Platzierungsursprung ist nicht gesetzt"))
            font = hint.GetFont()
            font.SetPointSize(max(font.GetPointSize() - 1, 7))
            hint.SetFont(font)
            hint.SetForegroundColour(wx.Colour(176, 120, 0))
            hint.SetToolTip(drill_origin_tip())
            root.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
            self.origin_hint = hint
        root.AddSpacer(8)

        self.notebook = wx.Notebook(self)
        for title, rows in PAGES:
            self.notebook.AddPage(self._build_page(title, rows), label_text(title))
        self.preview = PreviewPanel(self)
        body = wx.BoxSizer(wx.HORIZONTAL)
        body.Add(self.notebook, 3, wx.EXPAND)
        body.Add(self.preview, 2, wx.EXPAND | wx.LEFT, 10)
        root.Add(body, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 8)

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
        # Never narrower than the button row needs (German labels are long).
        best = self.GetBestSize()
        self.SetMinSize(wx.Size(max(960, best.width), 640))
        self.SetSize(wx.Size(max(1200, best.width), 780))
        self.CentreOnScreen()

        self.btn_generate.Bind(wx.EVT_BUTTON, self.on_generate)
        self.btn_folder.Bind(wx.EVT_BUTTON, self.on_open_folder)
        self.btn_defaults.Bind(wx.EVT_BUTTON, self.on_save_defaults)
        self.btn_reset.Bind(wx.EVT_BUTTON, self.on_reset)
        self.btn_close.Bind(wx.EVT_BUTTON, lambda evt: self.Close())
        self.Bind(wx.EVT_CLOSE, self.on_close)

        self.set_form(settings)
        self._update_folder_button()
        self._refresh_preview(settings)  # images of the last run, if any
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
                label = wx.StaticText(page, label=label_text(row.label))
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
        tip = label_text(field.tip) if field.tip[0] else ""
        if field.kind == "bool":
            grid.AddSpacer(0)
            ctrl: wx.Window = wx.CheckBox(page, label=label_text(field.label))
            ctrl.Bind(wx.EVT_CHECKBOX, self.on_form_changed)
            grid.Add(ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.AddSpacer(0)
        else:
            grid.Add(wx.StaticText(page, label=label_text(field.label)), 0, wx.ALIGN_CENTER_VERTICAL)
            if field.kind == "choice":
                ctrl = wx.Choice(page, choices=[label_text(label) for _, label in field.choices])
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
                ctrl.ChangeValue(format_number(value) if field.kind == "float" else str(value))
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
                    number = parse_number(ctrl.GetValue())
                    value = int(round(number)) if field.kind == "int" else number
                except ValueError:
                    errors.append(label_text(field.label))
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
        # The flip frame fixes these: corner at X0/Y0, no outline cut, drilling from the top.
        frame = bool(self.controls[("general", "frame_mode")][1].GetValue())
        for key in (("general", "zero_start"), ("general", "export_outline"), ("drill", "drill_side")):
            self.controls[key][1].Enable(not frame)
        mask = bool(self.controls[("mask", "enabled")][1].GetValue())
        for (section, name), (_, ctrl) in self.controls.items():
            if section == "mask" and name != "enabled":
                ctrl.Enable(mask)

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

    def _refresh_preview(self, settings: Settings) -> None:
        try:
            self.preview.show(list_previews(self.ctx.output_dir(settings)))
        except OSError:
            self.preview.show([])

    def _finished(self, output_dir: Optional[str], error: Optional[str], settings: Settings) -> None:
        self._set_running(False)
        self._update_folder_button()
        self._refresh_preview(settings)
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
