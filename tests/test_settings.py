import json

from kicad_pcb2gcode.settings import (
    AppConfig,
    Settings,
    board_settings_path,
    config_path,
    load_board_settings,
    load_config,
    save_board_settings,
    save_config,
)


def test_roundtrip():
    s = Settings()
    s.general.sides = "back"
    s.isolation.zwork = -0.1
    s.outline.bridgesnum = 2
    assert Settings.from_dict(json.loads(json.dumps(s.to_dict()))) == s


def test_invalid_and_unknown_values_fall_back():
    s = Settings.from_dict(
        {
            "general": {"sides": "sideways", "zsafe": "high", "export_drill": "no", "bogus": 1},
            "isolation": {"zwork": "-0.05", "milling_overlap": 30, "mill_speed": True, "vbit_angle": 30},
            "outline": {"bridgesnum": "3"},
            "drill": "not a dict",
            "unknown_section": {},
        }
    )
    d = Settings()
    assert s.general.sides == "auto"
    assert s.general.zsafe == d.general.zsafe
    assert s.general.export_drill is False
    assert s.isolation.zwork == -0.05
    assert s.isolation.milling_overlap == d.isolation.milling_overlap  # must be text
    assert s.isolation.mill_speed == d.isolation.mill_speed  # a bool is not a number
    assert s.outline.bridgesnum == 3
    assert s.drill == d.drill


def test_garbage_input_gives_defaults():
    for data in (None, [], "x", 3):
        assert Settings.from_dict(data) == Settings()


def test_nan_is_rejected():
    s = Settings.from_dict({"general": {"zsafe": "nan"}})
    assert s.general.zsafe == Settings().general.zsafe


def test_board_settings_path():
    assert board_settings_path("/p/board.kicad_pcb") == "/p/board.pcb2gcode.json"


def test_board_settings_override_user_defaults(tmp_path):
    board = tmp_path / "b.kicad_pcb"
    board.write_text("(kicad_pcb)")
    cfg = AppConfig()
    cfg.defaults.isolation.zwork = -0.06
    cfg.defaults.general.zsafe = 3
    assert load_board_settings(cfg, str(board)).isolation.zwork == -0.06

    s = Settings()
    s.isolation.zwork = -0.12
    save_board_settings(s, str(board))
    loaded = load_board_settings(cfg, str(board))
    assert loaded.isolation.zwork == -0.12
    assert loaded.general.zsafe == Settings().general.zsafe  # board file is complete


def test_config_roundtrip():
    cfg = AppConfig(pcb2gcode_path="/opt/pcb2gcode")
    cfg.defaults.drill.zdrill = -2.0
    save_config(cfg)
    assert config_path().endswith("config.json")
    loaded = load_config()
    assert loaded.pcb2gcode_path == "/opt/pcb2gcode"
    assert loaded.defaults.drill.zdrill == -2.0


def test_corrupt_config_is_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ not json")
    assert load_config(str(path)) == AppConfig()
