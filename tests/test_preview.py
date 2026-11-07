import os

from kicad_pcb2gcode.preview import clear, collect_run, list_previews


def touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()


def test_collect_and_list(tmp_path):
    out = str(tmp_path)
    for name in ("processed_back.svg", "traced_back.svg", "processed_outline.svg", "original_drill.svg",
                 "outp1_masked_back.svg"):
        touch(os.path.join(out, name))
    moved = collect_run(out, "main")
    assert len(moved) == 5 and not [f for f in os.listdir(out) if f.endswith(".svg")]
    touch(os.path.join(out, "processed_front.svg"))
    touch(os.path.join(out, "processed_back.svg"))
    collect_run(out, "mask")  # same names as the main run, kept apart
    labels = [label for label, _ in list_previews(out)]
    assert labels == ["Bottom side (B.Cu)", "Drill", "Outline", "Solder mask top", "Solder mask bottom"]


def test_final_image_of_several_tools_wins(tmp_path):
    out = str(tmp_path)
    for name in ("processed_front_0.svg", "processed_front_1.svg", "processed_front_final_0.svg",
                 "processed_front_final_1.svg"):
        touch(os.path.join(out, name))
    collect_run(out, "main")
    [(label, path)] = list_previews(out)
    assert os.path.basename(path) == "processed_front_final_1.svg"


def test_contentions_come_first(tmp_path):
    out = str(tmp_path)
    for name in ("processed_back.svg", "contentions_back.svg"):
        touch(os.path.join(out, name))
    collect_run(out, "main")
    labels = [label for label, _ in list_previews(out)]
    assert labels[0].startswith("⚠ Clearance not kept") and labels[1] == "Bottom side (B.Cu)"


def test_npth_label_and_clear(tmp_path):
    out = str(tmp_path)
    touch(os.path.join(out, "original_drill.svg"))
    collect_run(out, "npth")
    assert [label for label, _ in list_previews(out)] == ["NPTH: Drill"]
    touch(os.path.join(out, "stray.svg"))
    clear(out)
    assert list_previews(out) == [] and not os.path.exists(os.path.join(out, "stray.svg"))


def test_fit_view_centres_the_image():
    from kicad_pcb2gcode.preview import fit_view

    ox, oy, s = fit_view(200, 100, 416, 416)
    assert s == 2.0 and (ox, oy) == (8.0, 108.0)
    assert fit_view(0, 10, 100, 100) == (0.0, 0.0, 1.0)


def test_zoom_keeps_the_point_under_the_cursor():
    import pytest
    from kicad_pcb2gcode.preview import zoom_at

    ox, oy, s = 10.0, 20.0, 2.0
    px, py = 110.0, 70.0
    image_point = ((px - ox) / s, (py - oy) / s)
    nox, noy, ns = zoom_at(ox, oy, s, px, py, 1.25, fit_scale=2.0)
    assert ns == 2.5
    assert ((px - nox) / ns, (py - noy) / ns) == pytest.approx(image_point)


def test_zoom_limits():
    from kicad_pcb2gcode.preview import MAX_ZOOM, MIN_ZOOM, zoom_at

    assert zoom_at(0, 0, 1.0, 0, 0, 1000, fit_scale=1.0)[2] == MAX_ZOOM
    assert zoom_at(0, 0, 1.0, 0, 0, 0.001, fit_scale=1.0)[2] == MIN_ZOOM


def test_wheel_factor():
    from kicad_pcb2gcode.preview import wheel_factor

    assert wheel_factor(120, 120) == 1.25
    assert wheel_factor(-240, 120) == 1 / 1.25 ** 2
    assert 1 < wheel_factor(30, 120) < 1.25  # touchpad: part of a notch


def test_ease_scale_converges_both_ways():
    from kicad_pcb2gcode.preview import ease_scale

    for start, target in ((1.0, 8.0), (8.0, 1.0)):
        scale, done, steps = start, False, 0
        while not done:
            previous = scale
            scale, done = ease_scale(scale, target)
            assert min(start, target) <= scale <= max(start, target)
            assert abs(target - scale) <= abs(target - previous)
            steps += 1
        assert scale == target and 5 < steps < 30  # a short, visible glide


def test_ease_fraction_is_frame_rate_independent():
    from kicad_pcb2gcode.preview import ease_fraction, ease_scale

    assert ease_fraction(0) == 0.0
    assert 0 < ease_fraction(0.016) < ease_fraction(0.032) < 1
    # two short frames end where one long frame ends
    one = ease_scale(1.0, 8.0, ease_fraction(0.032))[0]
    two = ease_scale(ease_scale(1.0, 8.0, ease_fraction(0.016))[0], 8.0, ease_fraction(0.016))[0]
    assert abs(one - two) < 1e-9
