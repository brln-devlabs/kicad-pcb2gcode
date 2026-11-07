"""Tiny two-language (English/German) translation helper.

Strings are written inline as ``tr("English", "Deutsch")``; the language is
picked once from the environment. Set ``KICAD_PCB2GCODE_LANG=en`` or ``de``
to override.
"""

from __future__ import annotations

import locale
import os
import sys
from typing import Optional

_LANG: Optional[str] = None


def _detect() -> str:
    forced = os.environ.get("KICAD_PCB2GCODE_LANG", "").strip().lower()
    if forced in ("en", "de"):
        return forced
    candidates = [os.environ.get(var, "") for var in ("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")]
    try:
        candidates.append(locale.getlocale()[0] or "")
    except (ValueError, TypeError):
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if lang_id & 0x3FF == 0x07:  # LANG_GERMAN
                return "de"
        except Exception:
            pass
    for value in candidates:
        value = value.strip().lower()
        if not value or value in ("c", "posix", "c.utf-8"):
            continue
        return "de" if value.startswith("de") or value.startswith("german") else "en"
    return "en"


def lang() -> str:
    global _LANG
    if _LANG is None:
        _LANG = _detect()
    return _LANG


def set_lang(value: str) -> None:
    global _LANG
    _LANG = value if value in ("en", "de") else "en"


def tr(en: str, de: str) -> str:
    return de if lang() == "de" else en


PROBLEMS = {
    "nothing_to_do": ("Nothing to do: no copper, drill or outline data selected or found.",
                      "Nichts zu tun: keine Kupfer-, Bohr- oder Konturdaten gewählt oder gefunden."),
    "zsafe_positive": ("Safe height must be above zero.", "Sicherheitshöhe muss über null liegen."),
    "zchange_positive": ("Tool change height must be above zero.", "Werkzeugwechselhöhe muss über null liegen."),
    "frame_needs_outline": ("The flip frame mode needs a board outline on Edge.Cuts.",
                            "Der Wenderahmen-Modus braucht eine Platinenkontur auf Edge.Cuts."),
    "zwork_negative": ("Milling depth must be below zero (e.g. -0.08).",
                       "Frästiefe muss unter null liegen (z. B. -0,08)."),
    "mill_diameters_invalid": ("Mill diameters: one or more positive numbers separated by commas, e.g. 0.15.",
                               "Fräserdurchmesser: eine oder mehrere positive Zahlen mit Komma getrennt, z. B. 0.15."),
    "overlap_invalid": ("Overlap: a percentage below 100 (e.g. 20%) or a length (e.g. 0.05mm).",
                        "Überlappung: Prozentwert unter 100 (z. B. 20%) oder eine Länge (z. B. 0.05mm)."),
    "offset_range": ("Toolpath offset must not be negative.", "Zusätzlicher Bahnabstand darf nicht negativ sein."),
    "tolerance_range": ("Path tolerance must not be negative.", "Bahntoleranz darf nicht negativ sein."),
    "feed_positive": ("Feed rates must be positive.", "Vorschübe müssen positiv sein."),
    "isolation_width_range": ("Isolation width must not be negative.", "Isolationsbreite darf nicht negativ sein."),
    "zdrill_negative": ("Drill depth must be below zero.", "Bohrtiefe muss unter null liegen."),
    "drills_available_invalid": ("Available drills: use positive numbers separated by commas, e.g. 0.8, 1.0.",
                                 "Verfügbare Bohrer: positive Zahlen mit Komma getrennt, z. B. 0.8, 1.0."),
    "milldrill_invalid": ("Mill-drilling needs a positive tool diameter and a depth below zero.",
                          "Bohrfräsen braucht einen positiven Werkzeugdurchmesser und eine Tiefe unter null."),
    "zcut_negative": ("Outline cut depth must be below zero.", "Konturtiefe muss unter null liegen."),
    "cutter_positive": ("Outline cutter diameter must be positive.", "Konturfräser-Durchmesser muss positiv sein."),
    "infeed_positive": ("Depth per pass must be positive.", "Zustellung pro Durchgang muss positiv sein."),
    "bridgesnum_range": ("Number of tabs must not be negative.", "Anzahl der Haltestege darf nicht negativ sein."),
    "bridges_invalid": ("Tabs need a positive width and a height between the cut depth and zero.",
                        "Haltestege brauchen eine positive Breite und eine Höhe zwischen Konturtiefe und null."),
}


def problem_text(key: str) -> str:
    en, de = PROBLEMS.get(key, (key, key))
    return tr(en, de)
