#!/usr/bin/env python3
"""Draw docs/images/flip-frame-{en,de}.svg, the flip-frame sketch in the README."""

from __future__ import annotations

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "images")

TEXT = {
    "en": {
        "step1": "1  Top side + drilling",
        "step2": "2  Turn over left/right",
        "step3": "3  Bottom side",
        "frame": "frame = board size",
        "origin": "X0/Y0",
        "axis": "centre line",
        "files1": "board_front.ngc, board_drill.ngc",
        "files2": "origin stays",
        "files3": "board_back.ngc",
        "top": "top (F.Cu)",
        "bottom": "bottom (B.Cu)",
    },
    "de": {
        "step1": "1  Oberseite + Bohren",
        "step2": "2  Links/rechts wenden",
        "step3": "3  Unterseite",
        "frame": "Rahmen = Platinengröße",
        "origin": "X0/Y0",
        "axis": "Mittelachse",
        "files1": "board_front.ngc, board_drill.ngc",
        "files2": "Nullpunkt bleibt",
        "files3": "board_back.ngc",
        "top": "Oberseite (F.Cu)",
        "bottom": "Unterseite (B.Cu)",
    },
}

FRAME_W, FRAME_H = 200, 150


def panel(x: float, y: float, flipped: bool, t: dict, label: str) -> str:
    """Machine bed with frame, board, traces, holes and an orientation mark."""
    bx, by = x + 20, y + 20
    copper = "#c87533" if not flipped else "#b06a2c"
    board = "#2f6b3a" if not flipped else "#24552d"
    parts = [
        # frame
        '<rect x="{}" y="{}" width="{}" height="{}" rx="4" fill="#d9d4cc" stroke="#8a8378" stroke-width="2"/>'.format(
            x, y, FRAME_W + 40, FRAME_H + 40),
        '<rect x="{}" y="{}" width="{}" height="{}" fill="{}" stroke="#1d3d22" stroke-width="1.5"/>'.format(
            bx, by, FRAME_W, FRAME_H, board),
    ]
    # traces and pads, mirrored left/right on the bottom side
    def fx(px: float) -> float:
        return bx + (FRAME_W - px if flipped else px)

    # top: own traces; bottom: other traces between the same (through) holes
    traces = [((30, 40), (110, 40)), ((110, 40), (150, 80)), ((40, 110), (160, 110))]
    if flipped:
        traces = [((30, 40), (40, 110)), ((120, 70), (150, 80))]
    for (x1, y1), (x2, y2) in traces:
        parts.append('<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="{}" stroke-width="7" stroke-linecap="round"/>'.format(
            fx(x1), by + y1, fx(x2), by + y2, copper))
    holes = [(30, 40), (150, 80), (40, 110), (160, 110), (120, 70)]  # drilled through: mirrored below
    for hx, hy in holes:
        parts.append('<circle cx="{}" cy="{}" r="7" fill="{}"/><circle cx="{}" cy="{}" r="2.6" fill="#f4f1ea"/>'.format(
            fx(hx), by + hy, copper, fx(hx), by + hy))
    # orientation mark: a notch in one corner of the board
    mx = fx(12)
    parts.append('<circle cx="{}" cy="{}" r="5" fill="#f4f1ea" stroke="#1d3d22"/>'.format(mx, by + 12))
    # side label inside the board
    parts.append('<text x="{}" y="{}" text-anchor="middle" font-size="12" fill="#e8f3e6">{}</text>'.format(
        bx + FRAME_W * 0.72, by + FRAME_H - 10, t["bottom"] if flipped else t["top"]))
    # origin at the lower-left corner of the frame pocket
    ox, oy = bx, by + FRAME_H
    parts += [
        '<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#d1242f" stroke-width="2"/>'.format(ox, oy, ox + 28, oy),
        '<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="#d1242f" stroke-width="2"/>'.format(ox, oy, ox, oy - 28),
        '<circle cx="{}" cy="{}" r="4" fill="#d1242f"/>'.format(ox, oy),
        '<text x="{}" y="{}" font-size="12" fill="#d1242f" font-weight="bold">{}</text>'.format(ox - 2, oy + 34, t["origin"]),
        '<text x="{}" y="{}" text-anchor="middle" font-size="15" font-weight="bold" fill="#24292f">{}</text>'.format(
            x + (FRAME_W + 40) / 2, y - 14, label),
    ]
    return "\n".join(parts)


def svg(lang: str) -> str:
    t = TEXT[lang]
    width, height = 820, 350
    left_x, right_x, top_y = 20, 560, 50
    mid = (left_x + FRAME_W + 40 + right_x) / 2
    body = [
        '<rect width="{}" height="{}" fill="#ffffff"/>'.format(width, height),
        panel(left_x, top_y, False, t, t["step1"]),
        panel(right_x, top_y, True, t, t["step3"]),
        # centre line of the left board
        '<line x1="{0}" y1="{1}" x2="{0}" y2="{2}" stroke="#0969da" stroke-width="1.5" stroke-dasharray="6 4"/>'.format(
            left_x + 20 + FRAME_W / 2, top_y + 2, top_y + FRAME_H + 38),
        '<text x="{}" y="{}" font-size="11" fill="#0969da">{}</text>'.format(
            left_x + 20 + FRAME_W / 2 + 5, top_y + 14, t["axis"]),
        # turn-over arrow
        '<path d="M {} {} C {} {}, {} {}, {} {}" fill="none" stroke="#0969da" stroke-width="3" marker-end="url(#arrow)"/>'.format(
            mid - 70, top_y + 105, mid - 30, top_y + 40, mid + 30, top_y + 40, mid + 70, top_y + 105),
        '<text x="{}" y="{}" text-anchor="middle" font-size="15" font-weight="bold" fill="#24292f">{}</text>'.format(
            mid, top_y + 20, t["step2"]),
        '<text x="{}" y="{}" text-anchor="middle" font-size="12" fill="#57606a">{}</text>'.format(
            mid, top_y + 140, t["files2"]),
        # file names under the panels
        '<text x="{}" y="{}" text-anchor="middle" font-size="12" fill="#57606a" font-family="DejaVu Sans Mono, monospace">{}</text>'.format(
            left_x + (FRAME_W + 40) / 2, top_y + FRAME_H + 82, t["files1"]),
        '<text x="{}" y="{}" text-anchor="middle" font-size="12" fill="#57606a" font-family="DejaVu Sans Mono, monospace">{}</text>'.format(
            right_x + (FRAME_W + 40) / 2, top_y + FRAME_H + 82, t["files3"]),
        '<text x="{}" y="{}" text-anchor="middle" font-size="11" fill="#57606a">{}</text>'.format(
            right_x + (FRAME_W + 40) / 2, top_y + FRAME_H + 102, t["frame"]),
    ]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        'font-family="Noto Sans, DejaVu Sans, Helvetica, Arial, sans-serif">\n'
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#0969da"/></marker></defs>\n{body}\n</svg>\n'
    ).format(w=width, h=height, body="\n".join(body))


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    for lang in TEXT:
        path = os.path.join(OUT, "flip-frame-{}.svg".format(lang))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(svg(lang))
        print(os.path.relpath(path, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
