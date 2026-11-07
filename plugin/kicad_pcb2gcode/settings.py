"""Settings model with defaults tuned for GRBL, plus JSON persistence.

Two files are involved:

* ``config.json`` in the user's config directory holds machine-local things
  (where pcb2gcode lives) and the user's default job settings, written by
  "Save as default";
* ``<board>.pcb2gcode.json`` next to the board holds the job settings of that
  board. It is written on every run, so a project remembers its machining
  setup and the file can be committed together with the design.

Loading picks built-in defaults, then the user defaults, then the board file.
Unknown keys are ignored and missing or invalid values fall back, so older or
newer files never break the plugin.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict, Optional

SETTINGS_VERSION = 1
BOARD_SETTINGS_SUFFIX = ".pcb2gcode.json"
CONFIG_FILE_NAME = "config.json"

SIDES = ("auto", "front", "back", "both")
SIDE_CHOICES = ("auto", "front", "back")
FEED_DIRECTIONS = ("any", "climb", "conventional")
FLIP_AXES = ("leftright", "topbottom")


@dataclass
class GeneralSettings:
    output_subdir: str = "gcode"
    basename: str = ""  # empty: use the board file name
    sides: str = "auto"  # auto | front | back | both
    export_drill: bool = True
    export_outline: bool = True
    use_aux_origin: bool = False  # KiCad drill/place file origin instead of absolute
    include_unsaved: bool = True  # export a copy of the open board, unsaved edits included
    outer_layers_only: bool = False  # mill F.Cu/B.Cu even if inner layers carry copper
    zero_start: bool = True  # lower-left corner of the board outline at X0/Y0
    # Double-sided boards: the board is turned over about its own centre line,
    # left/right (around the vertical axis) or top/bottom.
    flip_axis: str = "leftright"
    # Flip frame: a pocket of exactly the outline size is fixed on the machine
    # and the pre-cut blank is turned over inside it. The outline is not cut,
    # holes are drilled from the top before turning.
    frame_mode: bool = False
    zsafe: float = 5.0
    zchange: float = 10.0
    open_folder_after: bool = False


@dataclass
class MachineSettings:
    """G-code dialect switches. Defaults suit GRBL / grblHAL."""

    nog64: bool = True  # GRBL has no G64 path blending
    nog81: bool = True  # GRBL has no canned drilling cycles
    nog91_1: bool = False  # GRBL understands G91.1; some other controllers do not
    nom6: bool = True  # GRBL 1.1 rejects M6; grblHAL with a tool changer can use it
    tolerance: float = 0.01  # allowed deviation from the ideal path, mm (0 = pcb2gcode's default)
    extra_options: str = ""  # raw millproject lines, appended verbatim


@dataclass
class IsolationSettings:
    # Width the tool cuts at the milling depth, as pcb2gcode's mill-diameters:
    # one value, or several (comma separated) to clear wider areas with more tools.
    mill_diameters: str = "0.154"
    # Extra distance kept between tool path and copper, for a bit with a little slop
    # (pcb2gcode's "offset", "Toolpath offset" in pcb2gcodeGUI).
    offset: float = 0.1
    zwork: float = -0.25
    mill_feed: float = 1200.0
    mill_vertfeed: float = 600.0  # pcb2gcode's own default is half the feed rate
    mill_speed: float = 24000.0
    isolation_width: float = 2.0  # 0 = a single pass around each trace
    milling_overlap: str = "50%"  # percent of the tool width, or a length like "0.05mm"
    voronoi: bool = False
    preserve_thermal_reliefs: bool = True  # Voronoi mode only
    mill_feed_direction: str = "any"


@dataclass
class DrillSettings:
    zdrill: float = -2.5
    drill_feed: float = 300.0
    drill_speed: float = 24000.0
    drill_side: str = "auto"
    drills_available: str = ""  # e.g. "0.8, 1.0, 1.2"; empty = one tool per hole size
    onedrill: bool = True
    milldrill: bool = False  # mill large holes with a small end mill
    milldrill_diameter: float = 3.0
    min_milldrill_hole_diameter: float = 3.0
    zmilldrill: float = -2.5


@dataclass
class OutlineSettings:
    cutter_diameter: float = 1.5
    zcut: float = -2.5
    cut_infeed: float = 2.5
    cut_feed: float = 800.0
    cut_vertfeed: float = 60.0
    cut_speed: float = 24000.0
    cut_side: str = "auto"
    bridges: float = 0.5  # tab width in mm
    bridgesnum: int = 2  # 0 = no tabs
    zbridges: float = -0.6


@dataclass
class MaskSettings:
    """Milling the solder mask openings (F.Mask/B.Mask) free.

    pcb2gcode runs a second time with invert-gerbers, which mills inside the
    drawn shapes - for a mask layer those are exactly the openings over pads.
    """

    enabled: bool = True
    mill_diameters: str = "0.1"
    offset: float = 0.0
    zwork: float = -0.03  # just through the mask, not into the copper
    mill_feed: float = 1200.0
    mill_vertfeed: float = 600.0
    mill_speed: float = 24000.0
    isolation_width: float = 2.0  # cleared inward from the opening's edge
    milling_overlap: str = "50%"


SECTIONS = ("general", "machine", "isolation", "drill", "outline", "mask")


@dataclass
class Settings:
    version: int = SETTINGS_VERSION
    general: GeneralSettings = field(default_factory=GeneralSettings)
    machine: MachineSettings = field(default_factory=MachineSettings)
    isolation: IsolationSettings = field(default_factory=IsolationSettings)
    drill: DrillSettings = field(default_factory=DrillSettings)
    outline: OutlineSettings = field(default_factory=OutlineSettings)
    mask: MaskSettings = field(default_factory=MaskSettings)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def copy(self) -> "Settings":
        return copy.deepcopy(self)

    def update_from_dict(self, data: Any) -> None:
        """Merge values from ``data`` into self, ignoring unknown or invalid keys."""
        if not isinstance(data, dict):
            return
        for section_name in SECTIONS:
            section_data = data.get(section_name)
            if not isinstance(section_data, dict):
                continue
            section = getattr(self, section_name)
            for f in fields(section):
                if f.name not in section_data:
                    continue
                value = _coerce(section_data[f.name], getattr(section, f.name))
                if value is not None:
                    setattr(section, f.name, value)
        self.sanitize()

    @classmethod
    def from_dict(cls, data: Any) -> "Settings":
        s = cls()
        s.update_from_dict(data)
        return s

    def sanitize(self) -> None:
        g, i, d, o = self.general, self.isolation, self.drill, self.outline
        if g.flip_axis not in FLIP_AXES:
            g.flip_axis = "leftright"
        if g.sides not in SIDES:
            g.sides = "auto"
        if i.mill_feed_direction not in FEED_DIRECTIONS:
            i.mill_feed_direction = "any"
        if d.drill_side not in SIDE_CHOICES:
            d.drill_side = "auto"
        if o.cut_side not in SIDE_CHOICES:
            o.cut_side = "auto"
        g.output_subdir = g.output_subdir.strip() or "gcode"
        g.basename = g.basename.strip()
        i.mill_diameters = i.mill_diameters.strip()
        i.milling_overlap = i.milling_overlap.strip()
        self.mask.mill_diameters = self.mask.mill_diameters.strip()
        self.mask.milling_overlap = self.mask.milling_overlap.strip()


def _coerce(value: Any, current: Any) -> Any:
    """Convert ``value`` to the type of ``current``; return None if impossible."""
    try:
        if isinstance(current, bool):
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return None
        if isinstance(value, bool):
            return None  # never let true/false sneak into numbers
        if isinstance(current, int):
            return int(value)
        if isinstance(current, float):
            number = float(value)
            return number if number == number and abs(number) != float("inf") else None
        if isinstance(current, str):
            return value if isinstance(value, str) else None
    except (TypeError, ValueError):
        return None
    return None


# -- machine-local configuration --------------------------------------------


@dataclass
class AppConfig:
    pcb2gcode_path: str = ""
    defaults: Settings = field(default_factory=Settings)

    def to_dict(self) -> Dict[str, Any]:
        return {"pcb2gcode_path": self.pcb2gcode_path, "defaults": self.defaults.to_dict()}

    @classmethod
    def from_dict(cls, data: Any) -> "AppConfig":
        cfg = cls()
        if isinstance(data, dict):
            path = data.get("pcb2gcode_path")
            if isinstance(path, str):
                cfg.pcb2gcode_path = path
            cfg.defaults.update_from_dict(data.get("defaults"))
        return cfg


def config_dir() -> str:
    """Per-user configuration directory, created on demand by the writers."""
    override = os.environ.get("KICAD_PCB2GCODE_CONFIG_DIR")
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "kicad-pcb2gcode")


def config_path() -> str:
    return os.path.join(config_dir(), CONFIG_FILE_NAME)


def board_settings_path(board_path: str) -> str:
    base, _ = os.path.splitext(board_path)
    return base + BOARD_SETTINGS_SUFFIX


def read_json(path: Optional[str]) -> Any:
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_json(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def load_config(path: Optional[str] = None) -> AppConfig:
    return AppConfig.from_dict(read_json(path or config_path()))


def save_config(cfg: AppConfig, path: Optional[str] = None) -> None:
    write_json(path or config_path(), cfg.to_dict())


def load_board_settings(cfg: AppConfig, board_path: Optional[str]) -> Settings:
    """User defaults overlaid with the board's own settings file, if any."""
    settings = cfg.defaults.copy()
    if board_path:
        settings.update_from_dict(read_json(board_settings_path(board_path)))
    return settings


def save_board_settings(settings: Settings, board_path: str) -> str:
    path = board_settings_path(board_path)
    write_json(path, settings.to_dict())
    return path
