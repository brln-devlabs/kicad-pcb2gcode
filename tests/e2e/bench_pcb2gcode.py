"""Time pcb2gcode on an exported job with changed settings.

    python3 bench_pcb2gcode.py GCODE_DIR

GCODE_DIR is the plugin's output folder (millproject, millproject_mask, cam/).
"""

import os
import subprocess
import sys
import time

out = os.path.abspath(sys.argv[1])
limit = float(sys.argv[2]) if len(sys.argv) > 2 else 900


def options(name):
    opts = []
    for line in open(os.path.join(out, name), encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            opts.append(line.split("=", 1))
    return opts


def run(base, label, change, drop=()):
    opts = [(k, v) for k, v in options(base) if k not in change and k not in drop]
    opts += [(k, v) for k, v in change.items() if v is not None]
    cfg = os.path.join(out, "bench.cfg")
    with open(cfg, "w") as fh:
        fh.write("".join("{}={}\n".format(k, v) for k, v in opts))
    start = time.time()
    try:
        proc = subprocess.run(["pcb2gcode", "--config", cfg], cwd=out, capture_output=True, text=True, timeout=limit)
        took = time.time() - start
        status = "ok" if proc.returncode == 0 else "exit {}".format(proc.returncode)
    except subprocess.TimeoutExpired:
        took, status = time.time() - start, "TIMEOUT"
    lines = 0
    for f in os.listdir(out):
        if f.startswith("bench_") and f.endswith(".ngc"):
            lines += sum(1 for _ in open(os.path.join(out, f)))
            os.remove(os.path.join(out, f))
    print("{:<52} {:7.1f} s  {:>8} G-code lines  {}".format(label, took, lines, status), flush=True)


print("main run settings:", dict(options("millproject")))
copper_only = {"basename": "bench", "drill": None, "outline": None}
run("millproject", "copper, as configured (isolation width 2 mm)", dict(copper_only))
run("millproject", "copper, isolation width 1 mm", dict(copper_only, **{"isolation-width": "1"}))
run("millproject", "copper, isolation width 0.5 mm", dict(copper_only, **{"isolation-width": "0.5"}))
run("millproject", "copper, 2 mm, eulerian-paths off", dict(copper_only, **{"eulerian-paths": "false"}))
if os.path.exists(os.path.join(out, "millproject_mask")):
    print("mask run settings:", dict(options("millproject_mask")))
    run("millproject_mask", "solder mask, as configured", {"basename": "bench"})
    run("millproject_mask", "solder mask, eulerian-paths on", {"basename": "bench", "eulerian-paths": None})
