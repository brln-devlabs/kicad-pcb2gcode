#!/usr/bin/env python3
"""Install the plugin into KiCad's plugin folder (KiCad 9 and newer).

    python scripts/install.py                 # copy into every KiCad >= 9 found
    python scripts/install.py --link          # symlink instead (for development)
    python scripts/install.py --kicad-version 10.0
    python scripts/install.py --plugins-dir /path/to/KiCad/10.0/plugins
    python scripts/install.py --uninstall

KiCad looks for IPC plugins in ``<KiCad documents folder>/<version>/plugins``.
Restart KiCad (or use Preferences > Plugins > Reload) afterwards.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "plugin")
FOLDER_NAME = "kicad-pcb2gcode"


def documents_homes() -> List[str]:
    """Candidate KiCad documents folders, existing ones only."""
    env = os.environ.get("KICAD_DOCUMENTS_HOME")
    homes = [env] if env else []
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        profile = os.environ.get("USERPROFILE", home)
        homes += [os.path.join(profile, "Documents", "KiCad"),
                  os.path.join(profile, "OneDrive", "Documents", "KiCad"),
                  os.path.join(profile, "OneDrive", "Dokumente", "KiCad")]
    elif sys.platform == "darwin":
        homes.append(os.path.join(home, "Documents", "KiCad"))
    else:
        data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
        homes += [os.path.join(data, "kicad"), os.path.join(data, "KiCad")]
    seen, result = set(), []
    for h in homes:
        real = os.path.realpath(h)
        if os.path.isdir(h) and real not in seen:
            seen.add(real)
            result.append(h)
    return result


def version_dirs(home: str) -> List[str]:
    found = []
    for name in os.listdir(home):
        m = re.fullmatch(r"(\d+)\.(\d+)", name)
        if m and int(m.group(1)) >= 9 and os.path.isdir(os.path.join(home, name)):
            found.append(os.path.join(home, name))
    return sorted(found)


def targets(args: argparse.Namespace) -> List[str]:
    if args.plugins_dir:
        return [args.plugins_dir]
    homes = documents_homes()
    if not homes:
        sys.exit("No KiCad documents folder found. Start KiCad once, or pass --plugins-dir.")
    if args.kicad_version:
        return [os.path.join(homes[0], args.kicad_version, "plugins")]
    dirs = [os.path.join(v, "plugins") for h in homes for v in version_dirs(h)]
    if not dirs:
        sys.exit("No KiCad 9 or newer found in {}. Pass --kicad-version or --plugins-dir.".format(", ".join(homes)))
    return dirs


def remove(path: str) -> None:
    if os.path.islink(path) or os.path.isfile(path):
        os.remove(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--link", action="store_true", help="symlink the plugin folder instead of copying it")
    p.add_argument("--kicad-version", help="e.g. 10.0")
    p.add_argument("--plugins-dir", help="explicit KiCad plugins folder")
    p.add_argument("--uninstall", action="store_true")
    args = p.parse_args()

    for plugins in targets(args):
        dest = os.path.join(plugins, FOLDER_NAME)
        remove(dest)
        if args.uninstall:
            print("removed   " + dest)
            continue
        os.makedirs(plugins, exist_ok=True)
        if args.link:
            os.symlink(SOURCE, dest, target_is_directory=True)
            print("linked    " + dest)
        else:
            shutil.copytree(SOURCE, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            print("installed " + dest)
    if not args.uninstall:
        print("\nRestart KiCad and make sure Preferences > Plugins > 'Enable KiCad API' is on.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
