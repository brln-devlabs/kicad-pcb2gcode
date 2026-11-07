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
TOOL_TYPES = ("vbit", "endmill")
SIDE_CHOICES = ("auto", "front", "back")
FEED_DIRECTIONS = ("any", "climb", "conventional")


@dataclass
class GeneralSettings:
    output_subdir: str = "gcode"
    basename: str = ""  # empty: use the board file name
    sides: str = "auto"  # auto | front | back | both
    export_drill: bool = True
    export_outline: bool = True
    use_aux_origin: bool = False  # KiCad drill/place file origin instead of absolute
    include_unsaved: bool = True  # export a copy of the open board, unsaved edits included
    zero_start: bool = True
    zsafe: float = 2.0
    zchange: float = 20.0
    open_folder_after: bool = False


@dataclass
class MachineSettings:
    """G-code dialect switches. Defaults suit GRBL / grblHAL."""

    nog64: bool = True  # GRBL has no G64 path blending
    nog81: bool = True  # GRBL has no canned drilling cycles
    nog91_1: bool = True  # GRBL has no G91.1
    nom6: bool = True  # GRBL 1.1 rejects M6; grblHAL with a tool changer can use it
    extra_options: str = ""  # raw millproject lines, appended verbatim


@dataclass
class IsolationSettings:
    tool_type: str = "vbit"  # vbit | endmill
    vbit_angle: float = 30.0  # included angle in degrees
    vbit_tip: float = 0.1  # tip width in mm
    mill_diameter: float = 0.2  # used for end mills
    zwork: float = -0.08
    mill_feed: float = 200.0
    mill_vertfeed: float = 50.0
    mill_speed: float = 10000.0
    isolation_width: float = 0.3  # 0 = a single pass around each trace
    milling_overlap: float = 20.0  # percent
    voronoi: bool = False
    mill_feed_direction: str = "any"


@dataclass
class DrillSettings:
    zdrill: float = -1.8
    drill_feed: float = 60.0
    drill_speed: float = 10000.0
    drill_side: str = "auto"
    drills_available: str = ""  # e.g. "0.8, 1.0, 1.2"; empty = one tool per hole size
    onedrill: bool = False
    milldrill: bool = False  # mill large holes with a small end mill
    milldrill_diameter: float = 1.0
    min_milldrill_hole_diameter: float = 1.5
    zmilldrill: float = -1.8


@dataclass
class OutlineSettings:
    cutter_diameter: float = 1.0
    zcut: float = -1.8
    cut_infeed: float = 0.6
    cut_feed: float = 100.0
    cut_vertfeed: float = 40.0
    cut_speed: float = 10000.0
    cut_side: str = "auto"
    bridges: float = 2.0  # tab width in mm
    bridgesnum: int = 4  # 0 = no tabs
    zbridges: float = -1.0


SECTIONS = ("general", "machine", "isolation", "drill", "outline")


@dataclass
class Settings:
    version: int = SETTINGS_VERSION
    general: GeneralSettings = field(default_factory=GeneralSettings)
    machine: MachineSettings = field(default_factory=MachineSettings)
    isolation: IsolationSettings = field(default_factory=IsolationSettings)
    drill: DrillSettings = field(default_factory=DrillSettings)
    outline: OutlineSettings = field(default_factory=OutlineSettings)

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
        if g.sides not in SIDES:
            g.sides = "auto"
        if i.tool_type not in TOOL_TYPES:
            i.tool_type = "vbit"
        if i.mill_feed_direction not in FEED_DIRECTIONS:
            i.mill_feed_direction = "any"
        if d.drill_side not in SIDE_CHOICES:
            d.drill_side = "auto"
        if o.cut_side not in SIDE_CHOICES:
            o.cut_side = "auto"
        g.output_subdir = g.output_subdir.strip() or "gcode"
        g.basename = g.basename.strip()


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
