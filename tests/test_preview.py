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
