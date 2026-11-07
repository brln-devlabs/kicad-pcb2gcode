#!/usr/bin/env python3
"""Render preview images of the settings window for the README.

The pictures are drawn from the dialog's own field definitions
(``kicad_pcb2gcode.form.PAGES``) and default settings, styled after the GTK
theme wxPython uses on Linux, and photographed with headless Chrome. They are
previews, not screenshots of a running KiCad: the real window follows the
operating system's look.

    python scripts/render_previews.py            # writes docs/images/*.png

Needs Google Chrome or Chromium and Pillow.
"""

from __future__ import annotations

import html
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "plugin"))

from kicad_pcb2gcode import __version__, i18n  # noqa: E402
from kicad_pcb2gcode.form import PAGES, Field, Heading, format_number, label_text  # noqa: E402
from kicad_pcb2gcode.gerber import Box  # noqa: E402
from kicad_pcb2gcode.job import frame_steps  # noqa: E402
from kicad_pcb2gcode.millproject import Inputs  # noqa: E402
from kicad_pcb2gcode.settings import Settings  # noqa: E402

OUT = os.path.join(ROOT, "docs", "images")
BOARD = "/home/user/projects/sensor-board/sensor-board.kicad_pcb"

CSS = """
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; background: #ffffff; font: 13px/1.35 "Cantarell", "Noto Sans", "DejaVu Sans", sans-serif; color: #2e3436; }
.win { width: 1200px; border: 1px solid #b6b6b3; border-radius: 8px 8px 4px 4px; background: #f6f5f4;
       box-shadow: 0 6px 22px rgba(0,0,0,.28); overflow: hidden; }
.title { height: 38px; background: #ebebeb; border-bottom: 1px solid #d5d0cc; display: flex; align-items: center;
         justify-content: center; font-weight: bold; position: relative; }
.title .close { position: absolute; right: 10px; top: 8px; width: 22px; height: 22px; border-radius: 50%;
                background: #dcdcdc; text-align: center; line-height: 22px; font-size: 12px; color: #444; }
.path { padding: 8px 10px 6px; color: #2e3436; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.body { display: flex; gap: 10px; margin: 0 8px; align-items: stretch; }
.nb { flex: 3; min-width: 0; border: 1px solid #cdc7c2; border-radius: 3px; background: #ffffff; }
.pv { flex: 2; display: flex; flex-direction: column; min-width: 0; }
.pv .t { font-weight: bold; margin-bottom: 6px; }
.pv .row { display: flex; gap: 6px; margin-bottom: 6px; }
.pv .row .combo { flex: 1; }
.pv .canvas { flex: 1; min-height: 240px; border: 1px solid #b8b3ae; background: #fff; display: flex;
              align-items: center; justify-content: center; color: #787878; text-align: center; padding: 12px; }
.tabs { display: flex; background: #f6f5f4; border-bottom: 1px solid #cdc7c2; }
.tab { padding: 7px 14px; color: #555753; border-bottom: 3px solid transparent; }
.tab.on { color: #2e3436; border-bottom-color: #3584e4; background: #ffffff; }
.page { padding: 12px 14px 14px; display: grid; grid-template-columns: max-content 1fr 64px; gap: 6px 10px; align-items: center; }
.h { font-weight: bold; padding-top: 8px; grid-column: 1 / span 3; }
.unit { color: #555753; }
.entry, .combo { height: 28px; border: 1px solid #cdc7c2; border-radius: 4px; background: #fff; padding: 4px 8px;
                 white-space: nowrap; overflow: hidden; }
.combo { background: linear-gradient(#fafafa, #f0f0ee); position: relative; padding-right: 26px; }
.combo:after { content: "\\25BE"; position: absolute; right: 9px; top: 4px; color: #555; }
.multi { height: 90px; }
.hint { color: #929595; }
.check { display: flex; align-items: center; gap: 7px; grid-column: 2 / span 2; }
.box { width: 16px; height: 16px; border: 1px solid #b8b3ae; border-radius: 3px; background: #fff; text-align: center;
       line-height: 15px; font-size: 12px; color: #fff; flex: none; }
.box.on { background: #3584e4; border-color: #1c71d8; }
.off { opacity: .45; }
.browse { width: 36px; height: 28px; border: 1px solid #cdc7c2; border-radius: 4px; background: #f6f5f4; text-align: center; }
.log { margin: 8px; border: 1px solid #cdc7c2; background: #fff; padding: 6px 8px; overflow: hidden;
       font: 12px/1.35 "DejaVu Sans Mono", monospace; white-space: pre; }
.buttons { display: flex; gap: 6px; padding: 0 8px 10px; }
.btn { white-space: nowrap; border: 1px solid #cdc7c2; border-radius: 5px; background: linear-gradient(#fafafa, #ececea); padding: 5px 12px; }
.btn.default { background: #3584e4; color: #fff; border-color: #1c71d8; }
.spacer { flex: 1; }
.origin { padding: 0 10px 6px; color: #b07800; font-size: 12px; }
.caption { margin-top: 10px; color: #77767b; font-size: 12px; }
"""


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def field_html(field: Field, settings: Settings, disabled: bool) -> str:
    value = getattr(getattr(settings, field.section), field.name)
    off = " off" if disabled else ""
    if field.kind == "bool":
        mark = "&#10003;" if value else ""
        return '<div></div><div class="check{}"><span class="box{}">{}</span>{}</div>'.format(
            off, " on" if value else "", mark, esc(label_text(field.label)))
    label = '<div class="{}">{}</div>'.format(off.strip(), esc(label_text(field.label)))
    if field.kind == "choice":
        text = next((label_text(lbl) for v, lbl in field.choices if v == value), "")
        ctrl = '<div class="combo{}">{}</div>'.format(off, esc(text))
    elif field.kind == "multiline":
        ctrl = '<div class="entry multi{}">{}</div>'.format(off, esc(str(value)))
    elif field.kind == "float":
        ctrl = '<div class="entry{}">{}</div>'.format(off, esc(format_number(value)))
    else:
        ctrl = '<div class="entry{}">{}</div>'.format(off, esc(str(value)))
    return label + ctrl + '<div class="unit{}">{}</div>'.format(off, esc(field.unit))


def disabled_keys(settings: Settings) -> set:
    keys = set()
    if not settings.isolation.voronoi:
        keys.add(("isolation", "preserve_thermal_reliefs"))
    if settings.general.frame_mode:
        keys |= {("general", "zero_start"), ("general", "export_outline"), ("drill", "drill_side")}
    if not settings.mask.enabled:
        keys |= {("mask", f.name) for _, rows in PAGES for f in rows
                 if isinstance(f, Field) and f.section == "mask" and f.name != "enabled"}
    return keys


def page_html(index: int, settings: Settings) -> str:
    title, rows = PAGES[index]
    parts = []
    if title[0] == "General":
        parts.append('<div class="h" style="padding-top:0">pcb2gcode</div>')
        parts.append('<div>{}</div><div class="entry"><span class="hint">{}</span></div><div class="browse">…</div>'.format(
            esc(i18n.tr("Program", "Programm")), esc(i18n.tr("Empty: search PATH", "Leer: im PATH suchen"))))
    off = disabled_keys(settings)
    for row in rows:
        if isinstance(row, Heading):
            parts.append('<div class="h">{}</div>'.format(esc(label_text(row.label))))
        else:
            parts.append(field_html(row, settings, (row.section, row.name) in off))
    return '<div class="page">{}</div>'.format("".join(parts))


def window_html(index: int, settings: Settings, log_lines, origin_hint: bool = False) -> str:
    tabs = "".join('<div class="tab{}">{}</div>'.format(" on" if i == index else "", esc(label_text(t)))
                   for i, (t, _) in enumerate(PAGES))
    tr = i18n.tr
    buttons = (
        '<div class="btn default">{}</div><div class="btn">{}</div><div class="spacer"></div>'
        '<div class="btn">{}</div><div class="btn">{}</div><div class="btn">{}</div>'
    ).format(*(esc(x) for x in (tr("Generate G-code", "G-Code erzeugen"), tr("Open output folder", "Ausgabeordner öffnen"),
                                tr("Save as default", "Als Standard speichern"), tr("Reset", "Zurücksetzen"),
                                tr("Close", "Schließen"))))
    return (
        '<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body>'
        '<div class="win" id="win"><div class="title">pcb2gcode – sensor-board<span class="close">✕</span></div>'
        '<div class="path">{path}</div>{hint}<div class="body"><div class="nb"><div class="tabs">{tabs}</div>{page}</div>'
        '<div class="pv"><div class="t">{pv_title}</div><div class="row"><div class="combo off"></div>'
        '<div class="browse off">\u2197</div></div><div class="canvas">{pv_msg}</div></div></div>'
        '<div class="log" style="height:{log_h}px">{log}</div><div class="buttons">{buttons}</div></div></body></html>'
    ).format(css=CSS, path=esc(BOARD), tabs=tabs,
             pv_title=esc(tr("Preview", "Vorschau")),
             pv_msg=esc(tr("No preview yet - it appears after generating.",
                           "Noch keine Vorschau - sie erscheint nach dem Erzeugen.")),
             hint='<div class="origin">\u26a0 {}</div>'.format(esc(tr(
                 "Drill/place file origin is not set", "Bohr-/Platzierungsursprung ist nicht gesetzt")))
             if origin_hint else "", page=page_html(index, settings),
             log=esc("\n".join(log_lines)), log_h=max(150, 17 * len(log_lines) + 14), buttons=buttons)


def chrome() -> str:
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome"):
        path = shutil.which(name)
        if path:
            return path
    sys.exit("Google Chrome or Chromium is needed to render the previews.")


def shoot(html_text: str, target: str) -> None:
    from PIL import Image, ImageChops

    with tempfile.TemporaryDirectory() as tmp:
        page = os.path.join(tmp, "page.html")
        raw = os.path.join(tmp, "raw.png")
        with open(page, "w", encoding="utf-8") as fh:
            fh.write(html_text)
        subprocess.run(
            [chrome(), "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=2", "--window-size=1300,1400", "--screenshot=" + raw, "file://" + page],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        img = Image.open(raw).convert("RGB")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bbox = ImageChops.difference(img, bg).getbbox()
        if bbox:
            pad = 24
            img = img.crop((max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
                            min(bbox[2] + pad, img.width), min(bbox[3] + pad, img.height)))
        img.save(target, optimize=True)


def render(lang: str) -> None:
    i18n.set_lang(lang)
    tr = i18n.tr
    ready = [tr("Ready. kicad-pcb2gcode {}", "Bereit. kicad-pcb2gcode {}").format(__version__)]
    titles = [t[0] for t, _ in PAGES]

    defaults = Settings()
    shots = [("general", titles.index("General"), defaults, ready)]

    iso = Settings()
    shots.append(("isolation", titles.index("Isolation"), iso, ready))

    shots.append(("solder-mask", titles.index("Solder mask"), Settings(), ready))

    frame = Settings()
    frame.general.frame_mode = True
    frame.general.sides = "both"
    box = Box(100.0, -80.0, 140.0, -50.0)
    files = ["sensor-board_front.ngc", "sensor-board_drill.ngc", "sensor-board_back.ngc",
             "sensor-board_mask_back.ngc", "sensor-board_mask_front.ngc"]
    log = [tr("Board outline: {:.3f} x {:.3f} mm", "Platinenkontur: {:.3f} x {:.3f} mm").format(box.width, box.height),
           tr("Flip frame: the outline is not cut.", "Wenderahmen: Die Kontur wird nicht gefräst."), ""]
    log += frame_steps(files, Inputs(board_box=box), "leftright")
    shots.append(("double-sided", titles.index("Double-sided"), frame, log))

    os.makedirs(OUT, exist_ok=True)
    for name, index, settings, log_lines in shots:
        target = os.path.join(OUT, "dialog-{}-{}.png".format(name, lang))
        shoot(window_html(index, settings, log_lines, origin_hint=(name == "general")), target)
        print(os.path.relpath(target, ROOT))


def main() -> int:
    for lang in ("en", "de"):
        render(lang)
    return 0


if __name__ == "__main__":
    sys.exit(main())
