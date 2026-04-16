"""
시뮬레이션 엔진 단위 테스트
머신 상태 관리와 시간 추정 기능을 검증합니다.
"""
import pytest
import numpy as np
from app.parser.gcode_parser import GCodeParser
from app.simulation.machine_state import MachineState
from app.simulation.time_estimator import TimeEstimator
from app.models.machine import MachineDef, MachineAxis


def make_test_machine():
    """테스트용 머신 설정을 생성합니다."""
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


def test_machine_state_step():
    """머신 상태 단계 이동 테스트"""
    code = "G0 X10.0 Y20.0\nG1 X50.0 F800\nG0 Z5.0"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    ms = MachineState()
    ms.load_toolpath(tp)

    # 초기 인덱스는 0이어야 함
    assert ms.current_segment_index == 0

    # 한 단계 앞으로
    result = ms.step_forward()
    assert result == True
    assert ms.current_segment_index == 1


def test_machine_state_step_backward():
    """머신 상태 역방향 이동 테스트"""
    code = "G0 X10.0\nG1 X20.0 F500\nG0 Z5.0"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    ms = MachineState()
    ms.load_toolpath(tp)

    ms.step_forward()
    ms.step_forward()
    assert ms.current_segment_index == 2

    ms.step_backward()
    assert ms.current_segment_index == 1


def test_machine_state_at_end():
    """마지막 세그먼트 도달 시 step_forward False 반환 테스트"""
    code = "G0 X10.0\nG0 X20.0"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    ms = MachineState()
    ms.load_toolpath(tp)

    # 처음 단계 이동은 성공
    assert ms.step_forward() == True
    # 마지막에서 이동 시도
    result = ms.step_forward()
    assert result == False


def test_machine_state_jump_to():
    """특정 인덱스로 점프 테스트"""
    code = "G0 X10.0\nG1 X20.0 F500\nG0 Z5.0\nG0 X0"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    ms = MachineState()
    ms.load_toolpath(tp)

    ms.jump_to(2)
    assert ms.current_segment_index == 2


def test_machine_state_reset():
    """리셋 후 처음으로 돌아가는지 테스트"""
    code = "G0 X10.0\nG1 X50.0 F800\nG0 Z5.0"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    ms = MachineState()
    ms.load_toolpath(tp)

    ms.step_forward()
    ms.step_forward()
    ms.reset()

    assert ms.current_segment_index == 0


def test_time_estimator_segment():
    """단일 세그먼트 시간 추정 테스트"""
    from app.models.toolpath import MotionSegment, MotionType

    estimator = TimeEstimator()

    # G1: 100mm 거리, 1000mm/min 이속
    seg = MotionSegment(
        segment_id=0,
        motion_type=MotionType.LINEAR,
        start_pos=np.array([0.0, 0.0, 0.0]),
        end_pos=np.array([100.0, 0.0, 0.0]),
        feedrate=1000.0,
        spindle_speed=3000.0,
        tool_number=1,
        line_number=1,
        raw_block="G1 X100 F1000"
    )

    # 100mm / 1000mm/min = 0.1분 = 6초
    time = estimator.estimate_segment_time(seg)
    assert time == pytest.approx(6.0, abs=0.01)


def test_time_estimator_rapid():
    """급속 이동 시간 추정 테스트 (머신 급속 속도 사용)"""
    from app.models.toolpath import MotionSegment, MotionType

    estimator = TimeEstimator()
    rapid_speed = 15000.0  # mm/min

    seg = MotionSegment(
        segment_id=0,
        motion_type=MotionType.RAPID,
        start_pos=np.array([0.0, 0.0, 0.0]),
        end_pos=np.array([150.0, 0.0, 0.0]),
        feedrate=0.0,  # 급속은 이송 속도 무시
        spindle_speed=0.0,
        tool_number=0,
        line_number=1,
        raw_block="G0 X150"
    )

    # 150mm / 15000mm/min = 0.01분 = 0.6초
    time = estimator.estimate_segment_time(seg, rapid_speed)
    assert time == pytest.approx(0.6, abs=0.01)


def test_time_estimator_total():
    """전체 공구경로 시간 추정 테스트"""
    machine = make_test_machine()
    code = "G0 X100.0\nG1 X0 F1000"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    estimator = TimeEstimator()
    total = estimator.estimate_total_time(tp, machine)
    # 최소한 0보다 커야 함
    assert total > 0


def test_progress():
    """진행률 계산 테스트"""
    code = "G0 X10.0\nG1 X20.0 F500\nG0 Z5.0"
    parser = GCodeParser()
    tp = parser.parse_string(code)
    ms = MachineState()
    ms.load_toolpath(tp)

    # 시작 시 진행률 0
    assert ms.get_progress() == pytest.approx(0.0, abs=0.01)

    ms.step_forward()
    ms.step_forward()

    # 2/3 지점 진행률
    assert ms.get_progress() > 0.5


def test_time_format():
    """시간 형식 변환 테스트"""
    estimator = TimeEstimator()
    assert "0초" in estimator.format_time(0)
    assert "30초" in estimator.format_time(30)
    assert "1분" in estimator.format_time(90)
    assert "1시간" in estimator.format_time(3600)
