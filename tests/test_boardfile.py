from kicad_pcb2gcode.boardfile import inner_copper_layers, special_via_kinds
from kicad_pcb2gcode.export import split_drill_files

# KiCad 9/10 numbering: F.Cu=0, B.Cu=2, inner layers 4, 6, …
KICAD9_4LAYER = """(kicad_pcb
\t(version 20241229)
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(4 "In1.Cu" signal)
\t\t(6 "In2.Cu" power "GND")
\t\t(2 "B.Cu" signal)
\t\t(9 "F.Adhes" user "F.Adhesive")
\t\t(25 "Edge.Cuts" user)
\t)
\t(setup (pad_to_mask_clearance 0))
\t(footprint "R" (layers "In1.Cu"))
)
"""

# KiCad 6-8 numbering and unquoted names
KICAD6_6LAYER = """(kicad_pcb (version 20211014)
  (layers
    (0 F.Cu signal)
    (1 In1.Cu signal)
    (2 In2.Cu signal)
    (10 In10.Cu signal)
    (31 B.Cu signal)
    (44 Edge.Cuts user)
  )
  (setup)
)
"""

TWO_LAYER = """(kicad_pcb (version 20241229)
  (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))
  (setup)
  (via (at 1 2) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu"))
)
"""


def test_inner_layers_kicad9():
    assert inner_copper_layers(KICAD9_4LAYER) == ["In1.Cu", "In2.Cu"]


def test_inner_layers_old_format_sorted_numerically():
    assert inner_copper_layers(KICAD6_6LAYER) == ["In1.Cu", "In2.Cu", "In10.Cu"]


def test_two_layer_board():
    assert inner_copper_layers(TWO_LAYER) == []
    assert special_via_kinds(TWO_LAYER) == []
    assert inner_copper_layers("") == []


def test_special_vias():
    text = TWO_LAYER + '(via blind (at 1 2) (layers "F.Cu" "In1.Cu"))\n(via micro (at 3 4))\n'
    assert special_via_kinds(text) == ["blind", "micro"]


def test_split_drill_files(tmp_path):
    assert split_drill_files(str(tmp_path)) == (None, [])
    for name in ("b.drl", "b-F_Cu-In1_Cu.drl"):
        (tmp_path / name).write_text("")
    merged, others = split_drill_files(str(tmp_path), "/x/b.kicad_pcb")
    assert merged.endswith("b.drl")
    assert [o.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for o in others] == ["b-F_Cu-In1_Cu.drl"]
    # without knowing the board name the shortest name is the through-hole file
    merged, _ = split_drill_files(str(tmp_path))
    assert merged.endswith("b.drl")


def test_drill_origin():
    from kicad_pcb2gcode.boardfile import drill_origin

    assert drill_origin(TWO_LAYER) is None  # KiCad leaves the entry out at 0/0
    assert drill_origin("(setup (aux_axis_origin 0 0))") is None
    assert drill_origin("(setup\n\t\t(aux_axis_origin 100.5 -80.25)\n\t)") == (100.5, -80.25)
