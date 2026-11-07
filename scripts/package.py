#!/usr/bin/env python3
"""Build dist/kicad-pcb2gcode-<version>.zip containing the plugin folder.

Unzip the archive into ``<KiCad documents folder>/<version>/plugins``.
"""

from __future__ import annotations

import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "plugin")
FOLDER_NAME = "kicad-pcb2gcode"


def version() -> str:
    with open(os.path.join(SOURCE, "kicad_pcb2gcode", "__init__.py"), encoding="utf-8") as fh:
        m = re.search(r'__version__ = "([^"]+)"', fh.read())
    if not m:
        sys.exit("version not found")
    return m.group(1)


def main() -> int:
    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    target = os.path.join(dist, "kicad-pcb2gcode-{}.zip".format(version()))
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for folder, dirs, files in os.walk(SOURCE):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for name in sorted(files):
                if name.endswith(".pyc"):
                    continue
                path = os.path.join(folder, name)
                arc = os.path.join(FOLDER_NAME, os.path.relpath(path, SOURCE))
                zf.write(path, arc)
        for extra in ("LICENSE", "README.md"):
            zf.write(os.path.join(ROOT, extra), os.path.join(FOLDER_NAME, extra))
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
