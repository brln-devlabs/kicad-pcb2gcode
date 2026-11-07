"""The vector scene the preview draws every frame (no wx needed)."""

import time
from types import SimpleNamespace as NS

from kicad_pcb2gcode import vector


def line_points(*pts):
    """nanosvg's point list for a polyline: every line as a cubic curve."""
    out = [pts[0]]
    for (x0, y0), (x, y) in zip(pts, pts[1:]):
        dx, dy = (x - x0) / 3.0, (y - y0) / 3.0
        out += [(x0 + dx, y0 + dy), (x - dx, y - dy), (x, y)]
    return out


def paint(rgba=None):
    if rgba is None:
        return NS(type=vector.PAINT_NONE)
    return NS(type=vector.PAINT_COLOR, color_rgba=rgba)


def shape(paths, fill=None, stroke=None, width=1.0, opacity=1.0, flags=1, rule=0, bounds=None):
    xs = [p[0] for path in paths for p in path.points]
    ys = [p[1] for path in paths for p in path.points]
    return NS(paths=paths, fill=paint(fill), stroke=paint(stroke), strokeWidth=width,
              opacity=opacity, flags=flags, fillRule=rule, strokeLineJoin=1, strokeLineCap=1,
              bounds=bounds or [min(xs), min(ys), max(xs), max(ys)])


def path(points, closed=False):
    return NS(points=points, closed=closed)


def test_lines_become_lines_curves_stay_curves():
    pts = line_points((0, 0), (10, 0), (10, 10)) + [(12, 12), (14, 8), (20, 10)]
    closed, start, segs = vector.sub_path(pts, True, 1e-6)
    assert closed and start == (0.0, 0.0)
    assert segs[0] == (10.0, 0.0) and segs[1] == (10.0, 10.0)
    assert segs[2] == (12.0, 12.0, 14.0, 8.0, 20.0, 10.0)


def test_opacity_folds_into_colour_and_hidden_shapes_are_skipped():
    square = path(line_points((0, 0), (1, 0), (1, 1), (0, 0)), closed=True)
    items = vector.build_scene([
        shape([square], fill=(255, 0, 0, 200), opacity=0.5, width=0),
        shape([square], fill=(0, 255, 0, 255), flags=0),          # invisible
        shape([square], fill=(0, 0, 255, 255), opacity=0.0),      # fully transparent
        shape([square], stroke=(0, 0, 0, 255), width=0),          # zero-width outline
    ])
    assert len(items) == 1
    assert items[0].style.fill == (255, 0, 0, 100) and items[0].style.stroke is None


def test_same_outlines_merge_but_never_jump_over_a_fill():
    def tool_path(x):
        return path(line_points((x, 0), (x, 5)))

    black = (0, 0, 0, 255)
    shapes = [
        shape([tool_path(0)], stroke=(200, 10, 10, 128), width=3),
        shape([tool_path(0)], stroke=black),
        shape([tool_path(1)], stroke=(10, 200, 10, 128), width=3),
        shape([tool_path(1)], stroke=black),
        shape([path(line_points((0, 0), (2, 0), (2, 2), (0, 0)), True)], fill=(9, 9, 9, 255), stroke=black),
        shape([tool_path(2)], stroke=black),
    ]
    items = vector.build_scene(shapes)
    strokes = [(it.style.fill, it.style.stroke, len(it.paths)) for it in items]
    assert strokes == [
        (None, (200, 10, 10, 128), 1),
        (None, (10, 200, 10, 128), 1),
        (None, black, 2),              # both centre lines, drawn after the last one
        ((9, 9, 9, 255), black, 1),    # the copper on top, as in the file
        (None, black, 1),              # after a fill: a new group
    ]
    assert items[2].bounds == [-1.0, -1.0, 2.0, 6.0]  # union, plus the stroke width


def test_culling():
    item = vector.Item(vector.Style(None, (0, 0, 0, 255), 1, 0, 0, False), [10, 10, 20, 20], [])
    assert vector.visible(item, (0, 0, 15, 15))
    assert not vector.visible(item, (21, 0, 40, 40))
    # window 400x300 px, image origin at (-100, 50) px, 2 px per unit
    assert vector.view_rect((-100, 50), 2.0, 400, 300) == (50.0, -25.0, 250.0, 125.0)


def test_gradient_draws_in_its_first_colour():
    grad = NS(type=vector.PAINT_LINEAR, gradient=NS(stops=[NS(color_rgba=(1, 2, 3, 255)), NS(color_rgba=(9, 9, 9, 255))]))
    s = shape([path(line_points((0, 0), (1, 1)))], width=0)
    s.fill = grad
    assert vector.build_scene([s])[0].style.fill == (1, 2, 3, 255)


def test_large_image_prepares_quickly():
    # about the size of a dense pcb2gcode image: 4000 tool paths of 60 points;
    # outlines of the same colour end up in one path each
    shapes = []
    for i in range(2000):
        pts = line_points(*[(i + (k % 7) * 0.1, k * 0.2) for k in range(60)])
        shapes.append(shape([path(pts)], stroke=(i % 256, 0, 0, 128), width=3))
        shapes.append(shape([path(pts)], stroke=(0, 0, 0, 255)))
    start = time.perf_counter()
    items = vector.build_scene(shapes, (2000, 12))
    assert time.perf_counter() - start < 5
    assert len(items) == 256 + 1 and vector.segment_count(items) == 4000 * 60
