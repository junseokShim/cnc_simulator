"""
공구 라이브러리와 급속/공구 카테고리 모델 통합 테스트
"""
import shutil
from pathlib import Path
from uuid import uuid4

import numpy as np

from app.geometry.stock_model import StockModel
from app.parser.gcode_parser import GCodeParser
from app.services.project_service import ProjectService
from app.services.tool_library_service import ToolLibraryService
from app.simulation.machining_model import MachiningModel


def make_stock() -> StockModel:
    return StockModel(
        np.array([-30.0, -30.0, -20.0]),
        np.array([100.0, 100.0, 0.0]),
        resolution=1.0,
    )


def analyze_code(code: str, tools):
    parser = GCodeParser()
    toolpath = parser.parse_string(code)
    return MachiningModel().analyze_toolpath(toolpath, tools, make_stock())


def test_tool_library_parses_shorthand_definition():
    """현장식 shorthand 정의가 공구 메타데이터로 변환되어야 한다."""

    service = ToolLibraryService()
    tools = service.load_entries([
        "T5 = 16mm REM 4F OH55 L90 RIGID=1.05 KC=0.95",
        "T6 = 12mm EM 4F OH48",
        "T7 = 7.5mm DR 2F OH70 KTC=950",
    ])

    rougher = tools[5]
    end_mill = tools[6]
    drill = tools[7]

    assert rougher.tool_category == "REM"
    assert rougher.flute_count == 4
    assert rougher.effective_overhang_mm == 55.0
    assert round(rougher.rigidity_factor, 2) == 1.05
    assert round(rougher.cutting_coefficient_factor, 2) == 0.95

    assert end_mill.tool_category == "EM"
    assert end_mill.flute_count == 4

    assert drill.tool_category == "DR"
    assert drill.is_drill
    assert drill.flute_count == 2
    assert drill.material_coefficient_overrides["Ktc"] == 950.0


def test_tool_diameter_input_is_converted_to_half_radius():
    """직경 입력값은 유지되고 내부 반경은 직경의 절반으로 계산되어야 한다."""

    tool = ToolLibraryService().parse_entry("T5 = 12mm EM 4F OH55")

    assert tool.diameter_mm == 12.0
    assert tool.radius_mm == 6.0


def test_tool_library_save_roundtrip_preserves_diameter_based_definition():
    """저장 후 다시 읽어도 직경 기반 공구 정의가 유지되어야 한다."""

    temp_root = Path("tests") / f"_tmp_tool_library_roundtrip_{uuid4().hex}"
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        library_file = temp_root / "tools.yaml"
        service = ToolLibraryService()
        tools = service.load_entries([
            "T5 = 12mm EM 4F OH55 L90 RIGID=1.05 KC=0.95",
            "T6 = 10mm EM 4F OH48 L85 RIGID=1.00 KC=1.00",
            "T7 = 7.5mm DR 2F OH70 L95 RIGID=0.92 KC=1.03",
        ])

        service.save_file(str(library_file), tools)
        reloaded = service.load_file(str(library_file))

        assert reloaded[5].diameter_mm == 12.0
        assert reloaded[5].radius_mm == 6.0
        assert reloaded[6].diameter_mm == 10.0
        assert reloaded[6].radius_mm == 5.0
        assert reloaded[7].diameter_mm == 7.5
        assert reloaded[7].radius_mm == 3.75
        assert reloaded[7].tool_category == "DR"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_project_service_loads_inline_tool_library():
    """프로젝트 YAML 안의 inline 공구 라이브러리가 로드되어야 한다."""

    temp_root = Path("tests") / f"_tmp_tool_library_{uuid4().hex}"
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        project_file = temp_root / "project.yaml"
        project_file.write_text(
            """
project_name: "tool library test"
nc_file: "dummy.nc"
stock:
  origin_mode: top_center
  origin: [0.0, 0.0, 0.0]
  size: [80.0, 80.0, 20.0]
tool_library:
  definitions:
    - "T5 = 16mm REM 4F OH55"
    - "T6 = 12mm EM 4F OH48"
    - "T7 = 7.5mm DR 2F OH70"
""".strip(),
            encoding="utf-8",
        )

        config = ProjectService().load_project(str(project_file))
        tools = config.get_tools_dict()

        assert set(tools) == {5, 6, 7}
        assert tools[5].tool_category == "REM"
        assert tools[6].tool_category == "EM"
        assert tools[7].tool_category == "DR"
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def test_rapid_segments_have_motion_vibration_without_cutting_chatter():
    """급속 이송은 절삭 채터와 분리된 모션 진동으로 계산되어야 한다."""

    tools = ToolLibraryService().load_entries([
        "T5 = 16mm REM 4F OH60",
    ])
    code = """
G21 G90
T5 M6
S3000 M3
G0 X0 Y0 Z20
G0 X80 Y0 Z20
G0 X80 Y80 Z20
G0 X0 Y80 Z20
"""

    analysis = analyze_code(code, tools)
    rapid_results = [result for result in analysis.results if result.machining_state == "RAPID"]

    assert rapid_results
    assert max(result.motion_vibration_um for result in rapid_results) > 0.0
    assert max(result.motion_risk_score for result in rapid_results) > 0.0
    assert max(result.cutting_vibration_um for result in rapid_results) == 0.0
    assert max(result.chatter_risk_score for result in rapid_results) == 0.0


def test_tool_category_changes_axial_force_and_chatter_behavior():
    """드릴과 엔드밀은 같은 직경이어도 서로 다른 축력/채터 거동을 보여야 한다."""

    tools = ToolLibraryService().load_entries([
        "T6 = 10mm EM 4F OH45",
        "T7 = 10mm DR 2F OH70",
    ])

    em_analysis = analyze_code(
        """
G21 G90
T6 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-6.0 F180
""",
        tools,
    )
    dr_analysis = analyze_code(
        """
G21 G90
T7 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-6.0 F180
""",
        tools,
    )

    em_result = next(result for result in em_analysis.results if result.is_cutting)
    dr_result = next(result for result in dr_analysis.results if result.is_cutting)

    assert em_result.tool_category == "EM"
    assert dr_result.tool_category == "DR"
    assert dr_result.estimated_force_z > em_result.estimated_force_z
    assert dr_result.chatter_risk_score < em_result.chatter_risk_score
