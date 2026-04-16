"""
검증 규칙 단위 테스트
NC 코드 검증 규칙의 정확성을 검증합니다.
"""
import pytest
import numpy as np
from app.parser.gcode_parser import GCodeParser
from app.verification.checker import VerificationChecker
from app.verification.rules import (
    check_spindle_off_cutting,
    check_zero_feedrate,
    check_large_z_plunge,
    check_arc_radius,
    check_out_of_bounds,
    check_missing_tool,
)
from app.models.machine import MachineDef, MachineAxis
from app.geometry.stock_model import StockModel


def make_stock():
    """테스트용 소재 모델 생성"""
    return StockModel(
        np.array([-60.0, -60.0, -30.0]),
        np.array([60.0, 60.0, 0.0]),
        resolution=5.0
    )


def make_machine():
    """테스트용 머신 설정 생성"""
    return MachineDef(
        name="테스트 머신",
        axes={
            'X': MachineAxis('X', -500, 500),
            'Y': MachineAxis('Y', -400, 400),
            'Z': MachineAxis('Z', -300, 100)
        },
        max_spindle_rpm=12000,
        max_feedrate=10000,
        rapid_feedrate=15000
    )


def test_spindle_off_warning():
    """주축 정지 상태에서 절삭 이동 경고 테스트"""
    code = "G1 X10.0 Y20.0 F500"  # M3(주축 ON) 없음
    parser = GCodeParser()
    tp = parser.parse_string(code)
    warnings = check_spindle_off_cutting(tp.segments)
    # 주축이 꺼진 상태에서 G1 이동이므로 경고 발생해야 함
    assert len(warnings) > 0
    assert any(w.code == "SPINDLE_OFF_CUTTING" for w in warnings)


def test_spindle_on_no_warning():
    """주축 ON 상태에서는 경고 없음을 테스트"""
    code = "S3000 M3\nG1 X10.0 F500"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    warnings = check_spindle_off_cutting(tp.segments)
    assert len(warnings) == 0


def test_zero_feedrate_warning():
    """이송 속도 0인 절삭 이동 경고 테스트"""
    code = "G1 X10.0 F0"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    warnings = check_zero_feedrate(tp.segments)
    assert len(warnings) > 0
    assert any(w.code == "ZERO_FEEDRATE" for w in warnings)


def test_normal_feedrate_no_warning():
    """정상 이송 속도에서는 경고 없음을 테스트"""
    code = "S3000 M3\nG1 X10.0 F800"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    warnings = check_zero_feedrate(tp.segments)
    assert len(warnings) == 0


def test_large_z_plunge_warning():
    """대형 Z 플런지 경고 테스트 (임계값 10mm)"""
    code = "S3000 M3\nG1 X0 Y0 Z-15.0 F200"  # 15mm 플런지
    parser = GCodeParser()
    tp = parser.parse_string(code)
    warnings = check_large_z_plunge(tp.segments, threshold=10.0)
    assert len(warnings) > 0
    assert any(w.code == "LARGE_Z_PLUNGE" for w in warnings)


def test_small_z_plunge_no_warning():
    """임계값 이하의 Z 하강은 경고 없음을 테스트"""
    code = "S3000 M3\nG1 Z-5.0 F200"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    warnings = check_large_z_plunge(tp.segments, threshold=10.0)
    assert len(warnings) == 0


def test_out_of_bounds_warning():
    """머신 범위 초과 경고 테스트"""
    machine = make_machine()
    code = "G0 X600.0 Y0 Z0"  # X 범위 초과 (최대 500)
    parser = GCodeParser()
    tp = parser.parse_string(code)
    warnings = check_out_of_bounds(tp.segments, machine)
    assert len(warnings) > 0
    assert any(w.code == "OUT_OF_BOUNDS" for w in warnings)


def test_within_bounds_no_warning():
    """범위 내 이동은 경고 없음을 테스트"""
    machine = make_machine()
    code = "G0 X100.0 Y50.0 Z-10.0"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    warnings = check_out_of_bounds(tp.segments, machine)
    assert len(warnings) == 0


def test_missing_tool_warning():
    """미정의 공구 참조 경고 테스트"""
    code = "T99 M6\nG1 X10.0 F500"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    # 빈 공구 라이브러리 사용 (T99 미정의)
    warnings = check_missing_tool(tp.segments, tools={})
    assert len(warnings) > 0
    assert any(w.code == "MISSING_TOOL" for w in warnings)


def test_defined_tool_no_warning():
    """정의된 공구는 경고 없음을 테스트"""
    from app.models.tool import Tool, ToolType
    code = "T1 M6\nG1 X10.0 F500"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    tools = {
        1: Tool(tool_number=1, name="테스트",
                tool_type=ToolType.END_MILL, diameter=10.0,
                length=75.0, flute_length=25.0)
    }
    warnings = check_missing_tool(tp.segments, tools=tools)
    assert len(warnings) == 0


def test_arc_radius_too_small():
    """원호 반경이 너무 작은 경우 경고 테스트"""
    # 반경이 0에 가까운 원호 세그먼트 직접 생성
    from app.models.toolpath import MotionSegment, MotionType
    seg = MotionSegment(
        segment_id=0,
        motion_type=MotionType.ARC_CW,
        start_pos=np.array([0.0, 0.0, 0.0]),
        end_pos=np.array([0.0, 0.0, 0.0]),
        feedrate=500.0,
        spindle_speed=3000.0,
        tool_number=1,
        line_number=1,
        raw_block="G2 ...",
        arc_center=np.array([0.0, 0.001, 0.0]),
        arc_radius=0.001  # 매우 작은 반경
    )
    warnings = check_arc_radius([seg])
    assert len(warnings) > 0
    assert any(w.code == "ARC_RADIUS_TOO_SMALL" for w in warnings)


def test_checker_integration():
    """통합 검증 체커 테스트"""
    code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5.0
G1 Z-35.0 F200
G1 X50.0 F800
M5 M30
"""
    parser = GCodeParser()
    tp = parser.parse_string(code)
    stock = make_stock()
    machine = make_machine()
    checker = VerificationChecker()
    warnings = checker.run_all_checks(tp, stock, machine, {})

    # 경고 목록이 리스트여야 함
    assert isinstance(warnings, list)
    # T1 미정의 경고가 있어야 함
    assert any(w.code == "MISSING_TOOL" for w in warnings)


def test_checker_run_with_good_code():
    """잘 작성된 NC 코드의 검증 테스트 (오류 없어야 함)"""
    from app.models.tool import Tool, ToolType

    code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5.0
G1 Z-5.0 F200
G1 X50.0 F800
G0 Z50.0
M5
M30
"""
    tools = {
        1: Tool(tool_number=1, name="테스트 엔드밀",
                tool_type=ToolType.END_MILL,
                diameter=10.0, length=75.0, flute_length=25.0)
    }

    parser = GCodeParser()
    tp = parser.parse_string(code)
    stock = make_stock()
    machine = make_machine()
    checker = VerificationChecker()
    warnings = checker.run_all_checks(tp, stock, machine, tools)

    # 오류 수준 경고는 없어야 함
    errors = [w for w in warnings if w.severity == "ERROR"]
    assert len(errors) == 0
