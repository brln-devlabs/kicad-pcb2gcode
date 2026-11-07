"""Write dense.kicad_pcb: a 2-layer board with many pads and tracks, to see
how the plugin and its preview cope with a busy design."""

import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
head = open(os.path.join(here, "rect.kicad_pcb"), encoding="utf-8").read()
head = head[: head.index("  (footprint")]
head = head.replace("(aux_axis_origin 100 130)", "(aux_axis_origin 100 132)")
cols, rows, pitch = 14, 8, 2.54
x0, y0 = 105.0, 107.0
parts = [head]
nets = []
for r in range(rows):
    for c in range(cols):
        nets.append((r * cols + c) // 2 + 1)
for n in sorted(set(nets)):
    parts.append('  (net {} "N{}")\n'.format(n, n))
for r in range(rows):
    for c in range(cols):
        net = nets[r * cols + c]
        x, y = x0 + c * pitch, y0 + r * pitch
        shape = "rect" if c % 2 == 0 else "circle"
        parts.append('  (footprint "Demo:Pad" (layer "F.Cu") (at {:.3f} {:.3f})\n'
                     '    (pad "1" thru_hole {} (at 0 0) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask") (net {} "N{}"))\n'
                     '  )\n'.format(x, y, shape, net, net))
        if c % 2 == 0:
            layer = "B.Cu" if r % 2 == 0 else "F.Cu"
            parts.append('  (segment (start {:.3f} {:.3f}) (end {:.3f} {:.3f}) (width 0.4) (layer "{}") (net {}))\n'
                         .format(x, y, x + pitch, y, layer, net))
# some longer tracks between the rows
for r in range(rows - 1):
    y = y0 + r * pitch + pitch / 2
    parts.append('  (segment (start {:.3f} {:.3f}) (end {:.3f} {:.3f}) (width 0.25) (layer "{}") (net 0))\n'
                 .format(x0, y, x0 + (cols - 1) * pitch, y, "B.Cu" if r % 2 else "F.Cu"))
parts.append('  (gr_rect (start 100 100) (end 145 132) (layer "Edge.Cuts") (width 0.1) (fill none))\n)\n')
target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "dense.kicad_pcb")
open(target, "w", encoding="utf-8").write("".join(parts))
print("wrote", target)
