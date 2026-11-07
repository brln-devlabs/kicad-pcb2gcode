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
from typing import List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "plugin")
FOLDER_NAME = "kicad-pcb2gcode"


def _windows_documents() -> str:
    """The real "Documents" folder, also when it is moved or redirected to OneDrive."""
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:  # CSIDL_PERSONAL
            return buf.value
    except Exception:
        pass
    return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Documents")


def locations() -> List[Tuple[str, str]]:
    """(documents home, config dir) pairs where a KiCad installation keeps its
    plugins and its settings - normal install and Flatpak on Linux."""
    home = os.path.expanduser("~")
    env = os.environ.get("KICAD_DOCUMENTS_HOME")
    pairs: List[Tuple[str, str]] = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        docs = _windows_documents()
        pairs.append((os.path.join(docs, "KiCad"), os.path.join(appdata, "kicad")))
        for alt in (os.path.join(home, "Documents"), os.path.join(home, "OneDrive", "Documents"),
                    os.path.join(home, "OneDrive", "Dokumente")):
            pairs.append((os.path.join(alt, "KiCad"), os.path.join(appdata, "kicad")))
    elif sys.platform == "darwin":
        pairs.append((os.path.join(home, "Documents", "KiCad"),
                      os.path.join(home, "Library", "Preferences", "kicad")))
    else:
        data = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
        config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        pairs.append((os.path.join(data, "kicad"), os.path.join(config, "kicad")))
        pairs.append((os.path.join(data, "KiCad"), os.path.join(config, "kicad")))
        flatpak = os.path.join(home, ".var", "app", "org.kicad.KiCad")
        pairs.append((os.path.join(flatpak, "data", "kicad"), os.path.join(flatpak, "config", "kicad")))
    if env:
        pairs.insert(0, (env, pairs[0][1]))
    return pairs


def version_dirs(folder: str) -> List[str]:
    """Version names >= 9 ("9.0", "10.0") that exist below ``folder``."""
    if not os.path.isdir(folder):
        return []
    found = []
    for name in os.listdir(folder):
        m = re.fullmatch(r"(\d+)\.(\d+)", name)
        if m and int(m.group(1)) >= 9 and os.path.isdir(os.path.join(folder, name)):
            found.append(name)
    return sorted(found, key=lambda v: tuple(int(x) for x in v.split(".")))


def targets(args: argparse.Namespace) -> List[str]:
    """Plugin folders to install into.

    A KiCad version counts as installed when its documents folder or its
    settings folder exists (KiCad creates the settings on first start, the
    documents folder only when something is saved there). Missing folders
    are created.
    """
    if args.plugins_dir:
        return [args.plugins_dir]
    pairs = locations()
    if args.kicad_version:
        for docs, config in pairs:
            if os.path.isdir(docs) or os.path.isdir(config):
                return [os.path.join(docs, args.kicad_version, "plugins")]
        return [os.path.join(pairs[0][0], args.kicad_version, "plugins")]
    result: List[str] = []
    seen = set()

    def add(docs: str, version: str) -> None:
        target = os.path.join(docs, version, "plugins")
        key = os.path.normcase(os.path.realpath(target))
        if key not in seen:
            seen.add(key)
            result.append(target)

    # versions that already have a documents folder
    for docs, _ in pairs:
        for version in version_dirs(docs):
            add(docs, version)
    # versions known only from their settings: use the first documents folder
    # of that installation that exists, else its default one
    for config in dict.fromkeys(c for _, c in pairs):
        candidates = [d for d, c in pairs if c == config]
        docs = next((d for d in candidates if os.path.isdir(d)), candidates[0])
        for version in version_dirs(config):
            if not any(os.path.isdir(os.path.join(d, version)) for d in candidates):
                add(docs, version)
    if not result:
        searched = "\n  ".join(sorted({p for pair in pairs for p in pair}))
        sys.exit(
            "No KiCad 9 or newer found. Searched:\n  {}\n\n"
            "Start KiCad once, or install explicitly:\n"
            "  python scripts/install.py --kicad-version 9.0\n"
            "  python scripts/install.py --plugins-dir <KiCad documents folder>/<version>/plugins".format(searched)
        )
    return result


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
