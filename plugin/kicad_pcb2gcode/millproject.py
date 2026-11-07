"""Build the ``millproject`` configuration file that pcb2gcode reads.

pcb2gcode picks up a file named ``millproject`` from its working directory, so
the plugin writes one into the output folder and runs pcb2gcode there. The file
stays next to the G-code: you can inspect it and re-run ``pcb2gcode`` by hand
from that folder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import __version__
from .settings import Settings
from .tools import fmt, parse_diameter_list, vbit_width


@dataclass
class Inputs:
    """File names (relative to the output folder) handed to pcb2gcode."""

    front: Optional[str] = None
    back: Optional[str] = None
    drill: Optional[str] = None
    outline: Optional[str] = None

    @property
    def mills(self) -> bool:
        return bool(self.front or self.back)

    @property
    def empty(self) -> bool:
        return not (self.front or self.back or self.drill or self.outline)


def mill_diameter(settings: Settings) -> float:
    iso = settings.isolation
    if iso.tool_type == "vbit":
        return vbit_width(iso.vbit_tip, iso.vbit_angle, iso.zwork)
    return iso.mill_diameter


def validate(settings: Settings, inputs: Inputs) -> List[str]:
    """Return problem keys (translated for display by :mod:`i18n`)."""
    problems: List[str] = []
    g, iso, d, o = settings.general, settings.isolation, settings.drill, settings.outline
    if inputs.empty:
        problems.append("nothing_to_do")
    if g.zsafe <= 0:
        problems.append("zsafe_positive")
    if g.zchange <= 0:
        problems.append("zchange_positive")
    if inputs.mills:
        if iso.zwork >= 0:
            problems.append("zwork_negative")
        try:
            if mill_diameter(settings) <= 0:
                problems.append("mill_diameter_positive")
        except ValueError:
            problems.append("vbit_invalid")
        if iso.mill_feed <= 0 or iso.mill_vertfeed <= 0:
            problems.append("feed_positive")
        if not 0 <= iso.milling_overlap < 100:
            problems.append("overlap_range")
        if iso.isolation_width < 0:
            problems.append("isolation_width_range")
    if inputs.drill:
        if d.zdrill >= 0:
            problems.append("zdrill_negative")
        if d.drill_feed <= 0:
            problems.append("feed_positive")
        try:
            parse_diameter_list(d.drills_available)
        except ValueError:
            problems.append("drills_available_invalid")
        if d.milldrill and (d.milldrill_diameter <= 0 or d.zmilldrill >= 0):
            problems.append("milldrill_invalid")
    if inputs.outline:
        if o.zcut >= 0:
            problems.append("zcut_negative")
        if o.cutter_diameter <= 0:
            problems.append("cutter_positive")
        if o.cut_infeed <= 0:
            problems.append("infeed_positive")
        if o.cut_feed <= 0 or o.cut_vertfeed <= 0:
            problems.append("feed_positive")
        if o.bridgesnum < 0:
            problems.append("bridgesnum_range")
        if o.bridgesnum > 0 and not (o.zcut < o.zbridges < 0 and o.bridges > 0):
            problems.append("bridges_invalid")
    seen = set()
    unique = []
    for p in problems:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def build_options(settings: Settings, inputs: Inputs, basename: str) -> List[Tuple[str, str]]:
    """Ordered (option, value) pairs for pcb2gcode."""
    g, m, iso, d, o = (
        settings.general,
        settings.machine,
        settings.isolation,
        settings.drill,
        settings.outline,
    )
    opts: List[Tuple[str, str]] = []

    def add(key: str, value) -> None:
        opts.append((key, value if isinstance(value, str) else fmt(value)))

    # -- common ------------------------------------------------------------
    add("metric", True)
    add("metricoutput", True)
    add("output-dir", ".")
    add("basename", basename)
    add("zsafe", g.zsafe)
    add("zchange", g.zchange)
    # Switches pcb2gcode defaults to false are only written when set, so a
    # switched-off option never trips an older pcb2gcode that lacks it.
    if g.zero_start:
        add("zero-start", True)
    for key, enabled in (("nog64", m.nog64), ("nog81", m.nog81), ("nog91-1", m.nog91_1), ("nom6", m.nom6)):
        if enabled:
            add(key, True)

    # -- isolation milling -------------------------------------------------
    if inputs.front:
        add("front", inputs.front)
    if inputs.back:
        add("back", inputs.back)
    if inputs.mills:
        add("zwork", iso.zwork)
        add("mill-diameters", mill_diameter(settings))
        add("mill-feed", iso.mill_feed)
        add("mill-vertfeed", iso.mill_vertfeed)
        add("mill-speed", iso.mill_speed)
        if iso.isolation_width > 0:
            add("isolation-width", iso.isolation_width)
            add("milling-overlap", fmt(iso.milling_overlap) + "%")
        if iso.voronoi:
            add("voronoi", True)
        if iso.mill_feed_direction != "any":
            add("mill-feed-direction", iso.mill_feed_direction)

    # -- drilling ----------------------------------------------------------
    if inputs.drill:
        add("drill", inputs.drill)
        add("zdrill", d.zdrill)
        add("drill-feed", d.drill_feed)
        add("drill-speed", d.drill_speed)
        if d.drill_side != "auto":
            add("drill-side", d.drill_side)
        sizes = parse_diameter_list(d.drills_available)
        if sizes:
            add("drills-available", ",".join(fmt(s) for s in sizes))
        if d.onedrill:
            add("onedrill", True)
        if d.milldrill:
            add("milldrill-diameter", d.milldrill_diameter)
            add("min-milldrill-hole-diameter", d.min_milldrill_hole_diameter)
            add("zmilldrill", d.zmilldrill)

    # -- board outline -----------------------------------------------------
    if inputs.outline:
        add("outline", inputs.outline)
        add("fill-outline", True)
        add("cutter-diameter", o.cutter_diameter)
        add("zcut", o.zcut)
        add("cut-infeed", o.cut_infeed)
        add("cut-feed", o.cut_feed)
        add("cut-vertfeed", o.cut_vertfeed)
        add("cut-speed", o.cut_speed)
        if o.cut_side != "auto":
            add("cut-side", o.cut_side)
        add("bridgesnum", o.bridgesnum)
        if o.bridgesnum > 0:
            add("bridges", o.bridges)
            add("zbridges", o.zbridges)

    return opts


def extra_lines(settings: Settings) -> List[str]:
    """User-supplied raw option lines; comments and blanks dropped, a leading
    "--" accepted so options can be pasted from a command line."""
    lines = []
    for raw in settings.machine.extra_options.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--"):
            line = line[2:]
        lines.append(line)
    return lines


def _split_option(line: str) -> Tuple[str, str]:
    if "=" in line:
        key, value = line.split("=", 1)
        return key.strip(), value.strip()
    # a bare flag such as "voronoi" means "voronoi=true" in a config file
    return line.strip(), "true"


def render(settings: Settings, inputs: Inputs, basename: str) -> str:
    """Text of the millproject file.

    Extra options override generated ones with the same name (pcb2gcode
    rejects an option given twice) and are appended otherwise.
    """
    options = build_options(settings, inputs, basename)
    index = {key: i for i, (key, _) in enumerate(options)}
    appended: List[Tuple[str, str]] = []
    appended_index = {}
    for line in extra_lines(settings):
        key, value = _split_option(line)
        if not key:
            continue
        if key in index:
            options[index[key]] = (key, value)
        elif key in appended_index:
            appended[appended_index[key]] = (key, value)
        else:
            appended_index[key] = len(appended)
            appended.append((key, value))

    out = [
        "# Generated by kicad-pcb2gcode {} - overwritten on every run.".format(__version__),
        "# Put permanent additions into the plugin's 'Extra options' field.",
        "",
    ]
    out.extend("{}={}".format(k, v) for k, v in options)
    if appended:
        out.append("")
        out.append("# Extra options")
        out.extend("{}={}".format(k, v) for k, v in appended)
    out.append("")
    return "\n".join(out)
