"""Description of the settings form: tabs, fields, labels (English, German).

Kept free of wxPython so that the documentation previews (scripts/render_previews.py)
can be generated from the very same definitions the dialog uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple, Union

from .i18n import tr


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
        Field("general", "file_extension", ("File extension", "Dateiendung"), "choice", choices=(
            ("ngc", (".ngc (pcb2gcode, LinuxCNC)", ".ngc (pcb2gcode, LinuxCNC)")),
            ("nc", (".nc", ".nc")),
            ("gcode", (".gcode", ".gcode")),
            ("tap", (".tap", ".tap")),
            ("cnc", (".cnc", ".cnc")),
            ("txt", (".txt", ".txt")),
        ), tip=("pcb2gcode writes .ngc; other extensions are applied afterwards. Pick what your G-code "
                "sender opens without asking (Candle, UGS, bCNC ...).",
                "pcb2gcode schreibt .ngc; andere Endungen werden danach vergeben. Wähle, was dein "
                "G-Code-Sender direkt öffnet (Candle, UGS, bCNC …).")),
        Field("general", "open_folder_after", ("Open folder when done", "Ordner danach öffnen"), "bool"),
        Heading(("Coordinates and heights", "Koordinaten und Höhen")),
        Field("general", "zero_start", ("Board corner at X0/Y0", "Platinenecke auf X0/Y0"), "bool",
              tip=("Puts the lower-left corner of the board outline exactly on the origin. "
                   "The bottom side is mirrored about the board's centre line, so it uses the same area.",
                   "Legt die linke untere Ecke der Platinenkontur genau auf den Nullpunkt. Die Unterseite "
                   "wird um die Platinenmitte gespiegelt und liegt im selben Bereich.")),
        Field("general", "use_aux_origin", ("Use drill/place file origin", "Bohr-/Platzierungsursprung verwenden"), "bool",
              tip=("Gerber and drill files are exported relative to KiCad's drill/place file origin, "
                   "like 'Use drill/place file origin' in KiCad's plot dialog.",
                   "Gerber- und Bohrdateien werden relativ zu KiCads Bohr-/Platzierungsursprung exportiert, "
                   "wie mit 'Bohr-/Platzierungsursprung verwenden' im Plotten-Dialog von KiCad.")),
        Field("general", "zsafe", ("Safe height", "Sicherheitshöhe"), "float", "mm"),
        Field("general", "zchange", ("Tool change height", "Werkzeugwechselhöhe"), "float", "mm"),
    ]),
    (("Double-sided", "Doppelseitig"), [
        Heading(("Turning the board over", "Platine wenden")),
        Field("general", "flip_axis", ("Direction", "Richtung"), "choice", choices=(
            ("leftright", ("Left/right (about the vertical centre line)", "Links/rechts (um die senkrechte Mittelachse)")),
            ("topbottom", ("Top/bottom (about the horizontal centre line)", "Oben/unten (um die waagerechte Mittelachse)")),
        )),
        Heading(("Flip frame", "Wenderahmen")),
        Field("general", "frame_mode", ("Mill in a flip frame", "Im Wenderahmen fräsen"), "bool",
              tip=("A frame with exactly the size of the board outline is fixed on the machine, its lower-left "
                   "corner is X0/Y0. The pre-cut blank is milled on top, drilled, turned over inside the frame "
                   "and milled on the bottom. The outline is cut last, from the side facing up by then.",
                   "Ein Rahmen genau in der Größe der Platinenkontur ist auf der Maschine befestigt, seine linke "
                   "untere Ecke ist X0/Y0. Der zugeschnittene Rohling wird oben gefräst, gebohrt, im Rahmen "
                   "gewendet und unten gefräst. Die Kontur wird zum Schluss gefräst, von der Seite, die dann oben liegt.")),
    ]),
    (("Isolation", "Isolation"), [
        Heading(("Tool", "Werkzeug")),
        Field("isolation", "mill_diameters", ("Available mill diameters", "Verfügbare Fräserdurchmesser"), "text", "mm",
              tip=("Width the tool cuts at the milling depth. Several, comma separated (e.g. 0.15, 0.4), "
                   "clear wider areas with additional tools.",
                   "Breite, die das Werkzeug in der Frästiefe schneidet. Mehrere mit Komma getrennt "
                   "(z. B. 0.15, 0.4) räumen breitere Bereiche mit weiteren Werkzeugen.")),
        Field("isolation", "offset", ("Toolpath offset", "Zusätzlicher Bahnabstand"), "float", "mm",
              tip=("Extra distance between tool path and copper, for a bit with a little slop.",
                   "Zusätzlicher Abstand zwischen Fräsbahn und Kupfer, falls der Fräser etwas Schlag hat.")),
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
        Field("drill", "holes", ("Holes", "Bohrungen"), "choice", choices=(
            ("merged", ("PTH and NPTH together (one file)", "PTH und NPTH zusammen (eine Datei)")),
            ("separate", ("PTH and NPTH separately (two files)", "PTH und NPTH getrennt (zwei Dateien)")),
            ("pth", ("Plated holes only (PTH)", "Nur durchkontaktierte Löcher (PTH)")),
            ("npth", ("Non-plated holes only (NPTH)", "Nur nicht durchkontaktierte Löcher (NPTH)")),
        ), tip=("Separately: <board>_drill.ngc for PTH and <board>_npth_drill.ngc for NPTH, "
                "e.g. for different drills or to mill mounting holes later.",
                "Getrennt: <board>_drill.ngc für PTH und <board>_npth_drill.ngc für NPTH, "
                "z. B. für unterschiedliche Bohrer oder um Befestigungslöcher später zu bohren.")),
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
    (("Solder mask", "Lötstopp"), [
        Field("mask", "enabled", ("Mill solder mask openings (F.Mask/B.Mask)", "Lötstopp-Öffnungen fräsen (F.Mask/B.Mask)"), "bool",
              tip=("Second pcb2gcode run with inverted Gerbers: mills inside the mask openings, i.e. frees the "
                   "pads after the solder mask has been applied.",
                   "Zweiter pcb2gcode-Lauf mit invertierten Gerbers: fräst innerhalb der Lötstopp-Öffnungen, legt "
                   "also die Pads nach dem Auftragen des Lötstopplacks frei.")),
        Heading(("Tool", "Werkzeug")),
        Field("mask", "mill_diameters", ("Available mill diameters", "Verfügbare Fräserdurchmesser"), "text", "mm",
              tip=("Width the tool cuts at the mask depth.", "Breite, die das Werkzeug in der Lötstopp-Tiefe schneidet.")),
        Field("mask", "offset", ("Toolpath offset", "Zusätzlicher Bahnabstand"), "float", "mm"),
        Field("mask", "zwork", ("Milling depth", "Frästiefe"), "float", "mm",
              tip=("Just through the mask, not into the copper (mask about 0.02-0.03 mm).",
                   "Nur durch den Lack, nicht ins Kupfer (Lack etwa 0,02-0,03 mm).")),
        Heading(("Feeds and speeds", "Vorschub und Drehzahl")),
        Field("mask", "mill_feed", ("Feed rate", "Vorschub"), "float", "mm/min"),
        Field("mask", "mill_vertfeed", ("Plunge rate", "Eintauchvorschub"), "float", "mm/min"),
        Field("mask", "mill_speed", ("Spindle speed", "Spindeldrehzahl"), "float", "1/min"),
        Heading(("Clearing", "Ausräumen")),
        Field("mask", "isolation_width", ("Clearing width", "Ausräumbreite"), "float", "mm",
              tip=("How far inward from the edge of an opening is milled. 2 mm clears pads up to 4 mm.",
                   "Wie weit vom Rand einer Öffnung nach innen gefräst wird. 2 mm räumt Pads bis 4 mm frei.")),
        Field("mask", "milling_overlap", ("Milling overlap", "Überlappung"), "text", "",
              tip=("Percent of the tool width (50%) or a length (0.05mm).",
                   "Prozent der Werkzeugbreite (50%) oder eine Länge (0.05mm).")),
    ]),
    (("Machine", "Maschine"), [
        Heading(("G-code dialect (defaults suit GRBL)", "G-Code-Dialekt (Voreinstellung passt für GRBL)")),
        Field("machine", "nog64", ("No G64 (path blending)", "Kein G64 (Bahnüberschleifen)"), "bool"),
        Field("machine", "nog81", ("No G81 (drilling cycle)", "Kein G81 (Bohrzyklus)"), "bool"),
        Field("machine", "nog91_1", ("No G91.1", "Kein G91.1"), "bool",
              tip=("GRBL understands G91.1. Tick only for controllers that do not.",
                   "GRBL versteht G91.1. Nur für Steuerungen ankreuzen, die es nicht kennen.")),
        Field("machine", "nom6", ("No M6 (tool change)", "Kein M6 (Werkzeugwechsel)"), "bool",
              tip=("GRBL 1.1 rejects M6. Turn off for grblHAL with a tool changer.",
                   "GRBL 1.1 lehnt M6 ab. Für grblHAL mit Werkzeugwechsler ausschalten.")),
        Field("machine", "skip_first_pause", ("Skip the pause at the start of each file",
                                               "Pause am Anfang jeder Datei weglassen"), "bool",
              tip=("pcb2gcode stops (M0) before every tool, including the first one. With this option the "
                   "first stop of each file is removed; stops for tool changes inside a file stay.",
                   "pcb2gcode hält (M0) vor jedem Werkzeug an, auch vor dem ersten. Mit dieser Option wird "
                   "die erste Pause jeder Datei entfernt; Pausen für Werkzeugwechsel innerhalb einer Datei "
                   "bleiben.")),
        Field("machine", "tolerance", ("Path tolerance", "Bahntoleranz"), "float", "mm",
              tip=("Allowed deviation from the ideal path. 0 = pcb2gcode's default.",
                   "Erlaubte Abweichung von der idealen Bahn. 0 = Voreinstellung von pcb2gcode.")),
        Heading(("Extra pcb2gcode options", "Zusätzliche pcb2gcode-Optionen")),
        Field("machine", "extra_options", ("One option per line", "Eine Option pro Zeile"), "multiline",
              tip=("e.g. spinup-time=3 - overrides generated options of the same name.",
                   "z. B. spinup-time=3 - überschreibt gleichnamige erzeugte Optionen.")),
    ]),
]


def label_text(pair: Tuple[str, str]) -> str:
    return tr(pair[0], pair[1])


def parse_number(text: str) -> float:
    return float(text.strip().replace(",", "."))


def format_number(value: float) -> str:
    text = "{:.4f}".format(value).rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text
