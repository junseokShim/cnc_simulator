"""
가공 해석 모델과 스톡 누적 표시 테스트
"""
import numpy as np

from app.geometry.stock_model import StockModel
from app.models.tool import Tool, ToolType
from app.parser.gcode_parser import GCodeParser
from app.simulation.machining_model import MachiningModel


def make_tool() -> Tool:
    return Tool(
        tool_number=1,
        name="테스트 엔드밀",
        tool_type=ToolType.END_MILL,
        diameter=10.0,
        length=75.0,
        flute_length=25.0,
        corner_radius=0.0,
        flute_count=4,
    )


def make_stock() -> StockModel:
    return StockModel(
        np.array([-30.0, -30.0, -20.0]),
        np.array([60.0, 30.0, 0.0]),
        resolution=1.0,
    )


def analyze_code(code: str):
    parser = GCodeParser()
    toolpath = parser.parse_string(code)
    model = MachiningModel()
    tool = make_tool()
    analysis = model.analyze_toolpath(toolpath, {1: tool}, make_stock())
    return toolpath, analysis


def cutting_results(analysis):
    return [result for result in analysis.results if result.is_cutting]


def last_cutting_result(analysis):
    return cutting_results(analysis)[-1]


def test_ae_affects_load_and_risk():
    """스테퍼가 커지면 AE, 부하, 채터 위험이 증가해야 한다."""

    narrow_code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-5.0 F200
G1 X40.0 F800
G0 Z5
G0 X0 Y2.0
G1 Z-5.0 F200
G1 X40.0 F800
"""

    wide_code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-5.0 F200
G1 X40.0 F800
G0 Z5
G0 X0 Y8.0
G1 Z-5.0 F200
G1 X40.0 F800
"""

    _, narrow_analysis = analyze_code(narrow_code)
    _, wide_analysis = analyze_code(wide_code)

    narrow = last_cutting_result(narrow_analysis)
    wide = last_cutting_result(wide_analysis)

    assert wide.radial_depth_ae > narrow.radial_depth_ae + 2.0
    assert wide.spindle_load_pct > narrow.spindle_load_pct
    assert wide.chatter_risk_score > narrow.chatter_risk_score
    assert wide.resultant_vibration_um > narrow.resultant_vibration_um


def test_ap_affects_load_and_risk():
    """절입 깊이가 깊어지면 AP, 부하, 채터 위험, Z축 진동이 증가해야 한다."""

    shallow_code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-2.0 F200
G1 X40.0 F800
"""

    deep_code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-8.0 F200
G1 X40.0 F800
"""

    _, shallow_analysis = analyze_code(shallow_code)
    _, deep_analysis = analyze_code(deep_code)

    shallow = last_cutting_result(shallow_analysis)
    deep = last_cutting_result(deep_analysis)

    assert deep.axial_depth_ap > shallow.axial_depth_ap + 3.0
    assert deep.spindle_load_pct > shallow.spindle_load_pct
    assert deep.chatter_risk_score > shallow.chatter_risk_score
    assert deep.vibration_z_um > shallow.vibration_z_um


def test_axis_vibration_reflects_cut_direction():
    """이송 방향에 따라 주로 흔들리는 축이 달라져야 한다."""

    x_move_code = """
G21 G90
T1 M6
S3500 M3
G0 X0 Y0 Z5
G1 Z-5.0 F250
G1 X40.0 F900
"""

    y_move_code = """
G21 G90
T1 M6
S3500 M3
G0 X0 Y0 Z5
G1 Z-5.0 F250
G1 Y40.0 F900
"""

    _, x_analysis = analyze_code(x_move_code)
    _, y_analysis = analyze_code(y_move_code)

    x_result = last_cutting_result(x_analysis)
    y_result = last_cutting_result(y_analysis)

    assert x_result.vibration_x_um > x_result.vibration_y_um
    assert y_result.vibration_y_um > y_result.vibration_x_um


def test_plunge_segment_has_high_z_vibration():
    """플런지 구간은 XY보다 Z축 진동이 더 크게 계산되어야 한다."""

    plunge_code = """
G21 G90
T1 M6
S2500 M3
G0 X0 Y0 Z5
G1 Z-6.0 F180
"""

    _, analysis = analyze_code(plunge_code)
    first_cut = cutting_results(analysis)[0]

    assert first_cut.is_plunge
    assert first_cut.vibration_z_um > first_cut.vibration_x_um
    assert first_cut.vibration_z_um > first_cut.vibration_y_um


def test_stock_trace_map_persists_and_resets():
    """가공 footprint가 누적되어 남아 있어야 하고 reset 시 초기화되어야 한다."""

    stock = make_stock()
    tool = make_tool()

    stock.remove_material(
        np.array([0.0, 0.0, -5.0]),
        np.array([20.0, 0.0, -5.0]),
        tool,
        {"spindle_load_pct": 55.0, "chatter_risk_score": 0.42},
    )

    mask = stock.get_machined_mask()
    trace = stock.get_trace_image_rgba()

    assert mask.any()
    assert stock.get_removed_depth_map().max() > 0.0
    assert trace[..., 3].max() > 70
    assert stock.load_map.max() >= 55.0
    assert stock.chatter_map.max() >= 42.0

    stock.reset()
    assert not stock.get_machined_mask().any()
    assert stock.get_removed_depth_map().max() == 0.0
