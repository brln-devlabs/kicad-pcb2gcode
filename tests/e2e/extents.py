"""Print the X/Y range of every G-code file in a folder (G0/G1/G2/G3 moves)."""
import glob
import os
import re
import sys

for path in sorted(glob.glob(os.path.join(sys.argv[1], "*.ngc"))):
    xs, ys, x, y = [], [], None, None
    for line in open(path):
        line = line.split(";")[0].split("(")[0]
        if not re.match(r"\s*G0?[0123]\b", line) and not re.match(r"\s*[XY]", line):
            continue
        mx, my = re.search(r"X(-?[\d.]+)", line), re.search(r"Y(-?[\d.]+)", line)
        x = float(mx.group(1)) if mx else x
        y = float(my.group(1)) if my else y
        if x is not None and y is not None and re.search(r"G0?[123]\b", line) or (mx or my) and re.match(r"\s*[XY]", line):
            if x is not None and y is not None:
                xs.append(x)
                ys.append(y)
    if xs:
        print("{:<28} X {:8.3f} .. {:8.3f}   Y {:8.3f} .. {:8.3f}".format(
            os.path.basename(path), min(xs), max(xs), min(ys), max(ys)))
