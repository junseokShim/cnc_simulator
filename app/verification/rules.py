"""
검증 규칙(Verification Rules) 모듈
NC 코드와 공구경로의 잠재적 문제를 감지하는 규칙 함수들을 제공합니다.
각 규칙은 독립적으로 실행되어 VerificationWarning 목록을 반환합니다.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Dict
import numpy as np

from app.models.toolpath import MotionSegment, MotionType
from app.models.machine import MachineDef
from app.models.tool import Tool
from app.geometry.stock_model import StockModel
from app.utils.logger import get_logger

logger = get_logger("verification_rules")


@dataclass
class VerificationWarning:
    """
    검증 경고 데이터 클래스
    NC 코드 검증 중 발견된 문제를 저장합니다.
    """
    # 경고 심각도: "ERROR"(오류), "WARNING"(경고), "INFO"(정보)
    severity: str

    # 경고 코드 (규칙 식별자, 예: "SPINDLE_OFF_CUTTING")
    code: str

    # 사용자에게 표시할 경고 메시지
    message: str

    # 문제가 발생한 NC 코드 라인 번호
    line_number: int

    # 관련 세그먼트 ID (-1이면 특정 세그먼트와 무관)
    segment_id: int = -1

    # 문제 발생 위치 [X, Y, Z] (없을 수 있음)
    position: Optional[np.ndarray] = None


def check_rapid_into_stock(segments: List[MotionSegment],
                            stock: StockModel) -> List[VerificationWarning]:
    """
    규칙 1: 급속 이동이 소재 내부로 진입하는지 검사합니다.
    G0(급속) 이동으로 소재 위 또는 내부로 이동하면 공구 충돌 위험이 있습니다.

    Args:
        segments: 검사할 세그먼트 목록
        stock: 소재 모델

    Returns:
        발견된 경고 목록
    """
    warnings = []

    for seg in segments:
        if seg.motion_type != MotionType.RAPID:
            continue

        # 소재 경계 박스 내에 있는지 확인
        min_corner, max_corner = stock.get_stock_bounds()
        end = seg.end_pos

        # XY 범위 내에 있는지 확인
        in_xy = (min_corner[0] <= end[0] <= max_corner[0] and
                 min_corner[1] <= end[1] <= max_corner[1])

        if not in_xy:
            continue

        # 소재 높이 조회
        stock_height = stock.get_height_at(end[0], end[1])

        # 공구 끝이 소재 높이 아래에 있는 경우 (소재 내부 진입)
        if end[2] < stock_height - 0.1:
            warnings.append(VerificationWarning(
                severity="ERROR",
                code="RAPID_INTO_STOCK",
                message=(f"급속 이동(G0)이 소재 내부로 진입합니다. "
                         f"위치: X{end[0]:.2f} Y{end[1]:.2f} Z{end[2]:.2f}, "
                         f"소재 높이: {stock_height:.2f}"),
                line_number=seg.line_number,
                segment_id=seg.segment_id,
                position=end.copy()
            ))
        elif abs(end[2] - stock_height) < 1.0:
            # 소재 표면에 매우 가까운 경우 (안전 여유 부족)
            warnings.append(VerificationWarning(
                severity="WARNING",
                code="RAPID_NEAR_STOCK",
                message=(f"급속 이동(G0)이 소재 표면에 너무 가깝습니다. "
                         f"위치: X{end[0]:.2f} Y{end[1]:.2f} Z{end[2]:.2f}, "
                         f"소재 높이: {stock_height:.2f} (여유: {end[2]-stock_height:.2f}mm)"),
                line_number=seg.line_number,
                segment_id=seg.segment_id,
                position=end.copy()
            ))

    return warnings


def check_out_of_bounds(segments: List[MotionSegment],
                         machine: MachineDef) -> List[VerificationWarning]:
    """
    규칙 2: 공구 이동이 머신 이동 범위를 벗어나는지 검사합니다.

    Args:
        segments: 검사할 세그먼트 목록
        machine: 머신 사양 (축 이동 범위 포함)

    Returns:
        발견된 경고 목록
    """
    warnings = []

    for seg in segments:
        # 시작점과 끝점 모두 확인
        for pos, pos_label in [(seg.start_pos, "시작"), (seg.end_pos, "끝")]:
            out_axes = machine.check_position(pos[0], pos[1], pos[2])

            if out_axes:
                axes_str = ", ".join(out_axes)
                warnings.append(VerificationWarning(
                    severity="ERROR",
                    code="OUT_OF_BOUNDS",
                    message=(f"세그먼트 {seg.segment_id} {pos_label}점이 "
                             f"머신 이동 범위를 벗어났습니다. "
                             f"벗어난 축: {axes_str}, "
                             f"위치: X{pos[0]:.2f} Y{pos[1]:.2f} Z{pos[2]:.2f}"),
                    line_number=seg.line_number,
                    segment_id=seg.segment_id,
                    position=pos.copy()
                ))

    return warnings


def check_missing_tool(segments: List[MotionSegment],
                        tools: Dict[int, Tool]) -> List[VerificationWarning]:
    """
    규칙 3: 참조된 공구 번호가 공구 라이브러리에 정의되어 있는지 확인합니다.

    Args:
        segments: 검사할 세그먼트 목록
        tools: 정의된 공구 딕셔너리 (번호 → Tool)

    Returns:
        발견된 경고 목록
    """
    warnings = []
    reported_tools = set()  # 중복 경고 방지

    for seg in segments:
        tool_num = seg.tool_number
        if tool_num == 0:
            continue  # 공구 미선택 상태는 건너뜀

        if tool_num not in tools and tool_num not in reported_tools:
            reported_tools.add(tool_num)
            warnings.append(VerificationWarning(
                severity="WARNING",
                code="MISSING_TOOL",
                message=(f"공구 T{tool_num}이 공구 라이브러리에 정의되지 않았습니다. "
                         f"공구 직경과 형상을 알 수 없어 검증이 제한됩니다."),
                line_number=seg.line_number,
                segment_id=seg.segment_id
            ))

    return warnings


def check_spindle_off_cutting(segments: List[MotionSegment]) -> List[VerificationWarning]:
    """
    규칙 4: 주축이 정지된 상태에서 절삭 이동이 발생하는지 검사합니다.
    주축이 꺼진 상태에서 G1/G2/G3 이동은 공구 파손 위험이 있습니다.

    Args:
        segments: 검사할 세그먼트 목록

    Returns:
        발견된 경고 목록
    """
    warnings = []

    for seg in segments:
        # 절삭 이동(G1, G2, G3)이면서 주축이 꺼진 경우
        if seg.is_cutting_move and not seg.spindle_on:
            # 매우 짧은 이동은 무시 (0.1mm 미만)
            if seg.get_distance() < 0.1:
                continue

            warnings.append(VerificationWarning(
                severity="WARNING",
                code="SPINDLE_OFF_CUTTING",
                message=(f"주축이 정지된 상태에서 절삭 이동({seg.motion_type.value})이 "
                         f"발생합니다. 공구 파손 위험이 있습니다."),
                line_number=seg.line_number,
                segment_id=seg.segment_id,
                position=seg.start_pos.copy()
            ))

    return warnings


def check_large_z_plunge(segments: List[MotionSegment],
                          threshold: float = 10.0) -> List[VerificationWarning]:
    """
    규칙 5: 단일 이동에서 Z축이 급격히 하강하는지 검사합니다.
    너무 큰 Z 플런지는 공구 파손 원인이 될 수 있습니다.

    Args:
        segments: 검사할 세그먼트 목록
        threshold: Z 하강 한계값 (mm, 기본값: 10.0)

    Returns:
        발견된 경고 목록
    """
    warnings = []

    for seg in segments:
        if seg.motion_type == MotionType.RAPID:
            continue  # 급속 이동은 Z 플런지 검사 제외

        # Z 방향 이동량 계산 (음수면 하강)
        dz = seg.end_pos[2] - seg.start_pos[2]

        if dz < -threshold:
            warnings.append(VerificationWarning(
                severity="WARNING",
                code="LARGE_Z_PLUNGE",
                message=(f"단일 이동에서 Z축이 {abs(dz):.1f}mm 하강합니다. "
                         f"한계값({threshold:.1f}mm)을 초과했습니다. "
                         f"이송 속도를 줄이거나 여러 단계로 분할하세요."),
                line_number=seg.line_number,
                segment_id=seg.segment_id,
                position=seg.start_pos.copy()
            ))

    return warnings


def check_zero_feedrate(segments: List[MotionSegment]) -> List[VerificationWarning]:
    """
    규칙 6: 절삭 이동에서 이송 속도가 0인지 검사합니다.
    이송 속도 0으로 절삭하면 머신이 멈추거나 오동작할 수 있습니다.

    Args:
        segments: 검사할 세그먼트 목록

    Returns:
        발견된 경고 목록
    """
    warnings = []

    for seg in segments:
        if not seg.is_cutting_move:
            continue

        if seg.feedrate <= 0:
            warnings.append(VerificationWarning(
                severity="ERROR",
                code="ZERO_FEEDRATE",
                message=(f"절삭 이동({seg.motion_type.value})에서 이송 속도가 "
                         f"{seg.feedrate:.1f} mm/min입니다. "
                         f"이송 속도를 반드시 지정해야 합니다."),
                line_number=seg.line_number,
                segment_id=seg.segment_id,
                position=seg.start_pos.copy()
            ))

    return warnings


def check_arc_radius(segments: List[MotionSegment]) -> List[VerificationWarning]:
    """
    규칙 7: 원호 이동의 반경이 의심스러운지 검사합니다.
    너무 작거나 너무 큰 반경은 프로그래밍 오류일 수 있습니다.

    Args:
        segments: 검사할 세그먼트 목록

    Returns:
        발견된 경고 목록
    """
    warnings = []

    for seg in segments:
        if not seg.is_arc:
            continue

        if seg.arc_radius is None:
            warnings.append(VerificationWarning(
                severity="WARNING",
                code="ARC_NO_RADIUS",
                message=f"원호 이동에 반경 정보가 없습니다.",
                line_number=seg.line_number,
                segment_id=seg.segment_id
            ))
            continue

        # 너무 작은 반경 (0.1mm 미만)
        if seg.arc_radius < 0.1:
            warnings.append(VerificationWarning(
                severity="WARNING",
                code="ARC_RADIUS_TOO_SMALL",
                message=(f"원호 반경이 너무 작습니다: {seg.arc_radius:.3f}mm. "
                         f"공구 경로 오류 가능성이 있습니다."),
                line_number=seg.line_number,
                segment_id=seg.segment_id,
                position=seg.start_pos.copy()
            ))

        # 너무 큰 반경 (10000mm 초과)
        elif seg.arc_radius > 10000.0:
            warnings.append(VerificationWarning(
                severity="INFO",
                code="ARC_RADIUS_VERY_LARGE",
                message=(f"원호 반경이 매우 큽니다: {seg.arc_radius:.1f}mm. "
                         f"직선 이동으로 대체를 검토하세요."),
                line_number=seg.line_number,
                segment_id=seg.segment_id
            ))

    return warnings


def check_excessive_feedrate(segments: List[MotionSegment],
                              machine: MachineDef) -> List[VerificationWarning]:
    """
    규칙 8: 이송 속도가 머신 최대값을 초과하는지 검사합니다.

    Args:
        segments: 검사할 세그먼트 목록
        machine: 머신 사양

    Returns:
        발견된 경고 목록
    """
    warnings = []

    for seg in segments:
        if seg.motion_type == MotionType.RAPID:
            continue

        if seg.feedrate > machine.max_feedrate:
            warnings.append(VerificationWarning(
                severity="WARNING",
                code="EXCESSIVE_FEEDRATE",
                message=(f"이송 속도 {seg.feedrate:.0f} mm/min이 "
                         f"머신 최대 이송 속도 {machine.max_feedrate:.0f} mm/min을 "
                         f"초과합니다."),
                line_number=seg.line_number,
                segment_id=seg.segment_id
            ))

    return warnings


def check_excessive_spindle_speed(segments: List[MotionSegment],
                                   machine: MachineDef) -> List[VerificationWarning]:
    """
    규칙 9: 주축 회전수가 머신 최대값을 초과하는지 검사합니다.

    Args:
        segments: 검사할 세그먼트 목록
        machine: 머신 사양

    Returns:
        발견된 경고 목록
    """
    warnings = []
    reported_speeds = set()

    for seg in segments:
        rpm = seg.spindle_speed
        if rpm > machine.max_spindle_rpm and rpm not in reported_speeds:
            reported_speeds.add(rpm)
            warnings.append(VerificationWarning(
                severity="WARNING",
                code="EXCESSIVE_SPINDLE_SPEED",
                message=(f"주축 회전수 {rpm:.0f} RPM이 "
                         f"머신 최대 회전수 {machine.max_spindle_rpm:.0f} RPM을 "
                         f"초과합니다."),
                line_number=seg.line_number,
                segment_id=seg.segment_id
            ))

    return warnings
