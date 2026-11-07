"""Write pour.kicad_pcb: a made-up two-layer board similar in size and
structure to a typical hobby design - 123 x 54 mm, about 80 through-hole
pads, ~160 track segments mostly on the bottom, and a GND pour with 1 mm
clearance on both sides (zones unfilled; fill them with pcbnew)."""

import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
head = open(os.path.join(here, "rect.kicad_pcb"), encoding="utf-8").read()
head = head[: head.index("  (net 0")]
head = head.replace("(aux_axis_origin 100 130)", "(aux_axis_origin 100 154)")

parts = [head, '  (net 0 "")\n  (net 1 "GND")\n']
net = 1
pads = []  # (x, y, size_x, size_y, shape, drill, net)
segments = []


def new_net():
    global net
    net += 1
    parts.append('  (net {} "N{}")\n'.format(net, net))
    return net


# rows of components: (y, x start, count, pitch, size, shape, drill)
rows = [
    (106, 106, 8, 5.08, (2.8, 2.8), "circle", 1.3),     # screw terminals
    (114, 108, 16, 2.54, (1.6, 1.6), "circle", 0.8),    # pin header
    (124, 110, 10, 2.54, (2.4, 1.6), "oval", 0.8),      # DIP row 1
    (131.62, 110, 10, 2.54, (2.4, 1.6), "oval", 0.8),   # DIP row 2
    (124, 150, 9, 2.54, (1.905, 2.0), "roundrect", 1.0),
    (140, 106, 9, 3.5, (1.508, 1.508), "circle", 0.8),
    (148, 150, 12, 3.0, (1.07, 2.9), "oval", 0.7),
    (106, 160, 9, 5.08, (2.8, 2.8), "circle", 1.3),
]
for i, (y, x0, count, pitch, size, shape, drill) in enumerate(rows):
    for k in range(count):
        is_gnd = (k + i) % 4 == 0
        pads.append((x0 + k * pitch, y, size, shape, drill, 1 if is_gnd else None))
# nets: neighbouring non-GND pads in a row share a net and get a track
for i, (x, y, size, shape, drill, n) in enumerate(pads):
    if n is None:
        prev = pads[i - 1] if i else None
        if prev and prev[1] == y and prev[5] not in (None, 1) and i % 2:
            pads[i] = (x, y, size, shape, drill, prev[5])
            # three segments with a small jog below the row
            px = prev[0]
            jy = y + 1.6
            segments.append((px, y, px + 0.8, jy, 1.0, n or prev[5]))
            segments.append((px + 0.8, jy, x - 0.8, jy, 1.0, prev[5]))
            segments.append((x - 0.8, jy, x, y, 1.0, prev[5]))
        else:
            pads[i] = (x, y, size, shape, drill, new_net())
# long bottom-side tracks between the rows, in the channels
channel_ys = [110.5, 119.5, 136, 144]
for j, cy in enumerate(channel_ys):
    for k in range(4):
        n = new_net()
        x0 = 104 + k * 29
        segments.append((x0, cy, x0 + 12, cy, 1.0 if k % 2 else 1.8, n))
        segments.append((x0 + 12, cy, x0 + 14, cy + 1.2, 0.8, n))
        segments.append((x0 + 14, cy + 1.2, x0 + 26, cy + 1.2, 0.8, n))

for x, y, (sx, sy), shape, drill, n in pads:
    extra = " (roundrect_rratio 0.25)" if shape == "roundrect" else ""
    parts.append('  (footprint "Demo:Pad" (layer "F.Cu") (at {:.3f} {:.3f})\n'
                 '    (pad "1" thru_hole {} (at 0 0) (size {} {}) (drill {}) (layers "*.Cu" "*.Mask"){} (net {} "{}"))\n'
                 '  )\n'.format(x, y, shape, sx, sy, drill, extra, n, "GND" if n == 1 else "N{}".format(n)))
for x0, y0, x1, y1, w, n in segments:
    parts.append('  (segment (start {:.3f} {:.3f}) (end {:.3f} {:.3f}) (width {}) (layer "B.Cu") (net {}))\n'
                 .format(x0, y0, x1, y1, w, n))
for x in (103, 220):
    parts.append('  (footprint "Demo:Hole" (layer "F.Cu") (at {} 151)\n'
                 '    (pad "" np_thru_hole circle (at 0 0) (size 3.2 3.2) (drill 3.2) (layers "*.Cu" "*.Mask"))\n'
                 '  )\n'.format(x))
for layer in ("F.Cu", "B.Cu"):
    parts.append('  (zone (net 1) (net_name "GND") (layer "{}") (hatch edge 0.5)\n'
                 '    (connect_pads (clearance 1))\n'
                 '    (min_thickness 0.25)\n'
                 '    (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))\n'
                 '    (polygon (pts (xy 99 99) (xy 224 99) (xy 224 155) (xy 99 155)))\n'
                 '  )\n'.format(layer))
parts.append('  (gr_rect (start 100 100) (end 223 154) (layer "Edge.Cuts") (width 0.05) (fill none))\n)\n')
target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "pour.kicad_pcb")
open(target, "w", encoding="utf-8").write("".join(parts))
print("wrote", target, len(pads), "pads", len(segments), "segments")
