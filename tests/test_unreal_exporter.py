import json

import pytest

from app.integrations.unreal_exporter import UnrealSceneExporter
from app.parser.gcode_parser import GCodeParser


def test_exports_scene_json(tmp_path):
    toolpath = GCodeParser().parse_string("G0 X0 Y0 Z5\nG1 X10 Y0 Z-1 F500")
    output = UnrealSceneExporter().export(toolpath, tmp_path / "scene.json")
    data = json.loads(output.read_text(encoding="utf-8"))

    assert data["schema"] == "vericut.unreal.scene"
    assert data["version"] == 1
    assert data["units"] == "mm"
    assert len(data["segments"]) == 2
    assert data["segments"][1]["cutting"] is True
    assert data["segments"][1]["points_mm"][-1] == [10.0, 0.0, -1.0]


def test_tessellates_arcs():
    toolpath = GCodeParser().parse_string("G17\nG2 X10 Y0 I5 J0 F300")
    scene = UnrealSceneExporter(arc_chord_mm=1.0).build_scene(toolpath)
    assert len(scene["segments"][0]["points_mm"]) > 2
    assert scene["segments"][0]["points_mm"][-1] == [10.0, 0.0, 0.0]


def test_rejects_invalid_stock_bounds():
    toolpath = GCodeParser().parse_string("G1 X1")
    with pytest.raises(ValueError):
        UnrealSceneExporter().build_scene(toolpath, (0, 0, 0), (0, 1, 1))
