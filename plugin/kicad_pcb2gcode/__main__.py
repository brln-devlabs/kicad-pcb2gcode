"""Command line: ``python -m kicad_pcb2gcode BOARD.kicad_pcb [options]``.

Runs the same pipeline as the KiCad plugin on a saved board, without a running
KiCad. Settings come from the board's ``.pcb2gcode.json`` (written by the
plugin) and the user defaults; the options below override them for this run.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .i18n import set_lang
from .settings import SIDES


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="python -m kicad_pcb2gcode",
        description="Generate CNC milling G-code from a KiCad board with pcb2gcode.",
    )
    p.add_argument("board", help="path to the .kicad_pcb file")
    p.add_argument("--gui", action="store_true", help="open the settings window instead of running directly")
    p.add_argument("--sides", choices=SIDES, help="copper sides to mill (default: from settings, usually auto)")
    p.add_argument("--no-drill", action="store_true", help="skip drilling")
    p.add_argument("--no-outline", action="store_true", help="skip the board outline")
    p.add_argument("--frame", action="store_true",
                   help="flip frame: no outline cut, drill from the top, corner at X0/Y0")
    p.add_argument("--flip", choices=("leftright", "topbottom"), help="axis the board is turned over about")
    p.add_argument("--outer-layers-only", action="store_true",
                   help="mill F.Cu/B.Cu even if inner copper layers carry copper")
    p.add_argument("--output", metavar="DIR", help="output folder (absolute, or relative to the board)")
    p.add_argument("--kicad-cli", metavar="PATH", help="kicad-cli executable")
    p.add_argument("--pcb2gcode", metavar="PATH", help="pcb2gcode executable")
    p.add_argument("--lang", choices=("en", "de"), help="message language")
    p.add_argument("--version", action="version", version="kicad-pcb2gcode " + __version__)
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.lang:
        set_lang(args.lang)
    general = {}
    if args.sides:
        general["sides"] = args.sides
    if args.no_drill:
        general["export_drill"] = False
    if args.no_outline:
        general["export_outline"] = False
    if args.frame:
        general["frame_mode"] = True
    if args.flip:
        general["flip_axis"] = args.flip
    if args.outer_layers_only:
        general["outer_layers_only"] = True
    if args.output:
        general["output_subdir"] = args.output

    from .app import main_standalone

    return main_standalone(
        args.board,
        use_gui=args.gui,
        overrides={"general": general} if general else None,
        kicad_cli=args.kicad_cli,
        pcb2gcode=args.pcb2gcode,
    )


if __name__ == "__main__":
    sys.exit(main())
