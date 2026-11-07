"""Entry point KiCad runs when the toolbar button is pressed.

KiCad starts this script in the plugin's own Python environment and passes
the API socket and token through KICAD_API_SOCKET / KICAD_API_TOKEN.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kicad_pcb2gcode.app import main_ipc  # noqa: E402

if __name__ == "__main__":
    sys.exit(main_ipc())
