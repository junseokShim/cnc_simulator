"""
공구경로(Toolpath) 데이터 모델 모듈
NC 코드 파싱 결과를 저장하는 데이터 구조를 정의합니다.
각 이동 세그먼트와 전체 공구경로 정보를 포함합니다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import numpy as np


class MotionType(Enum):
    """
    공구 이동 유형 열거형
    G-코드의 이동 명령에 대응하는 이동 종류를 정의합니다.
    """
    RAPID = "RAPID"          # G0: 급속 이동 (절삭 없음)
    LINEAR = "LINEAR"        # G1: 직선 절삭 이동
    ARC_CW = "ARC_CW"       # G2: 시계방향 원호 이동
    ARC_CCW = "ARC_CCW"     # G3: 반시계방향 원호 이동
    DWELL = "DWELL"          # G4: 일시 정지


@dataclass
class MotionSegment:
    """
    단일 이동 세그먼트 데이터 클래스
    NC 코드의 한 블록(G0/G1/G2/G3)에 해당하는 이동 정보를 저장합니다.
    """
    # 세그먼트 고유 식별자
    segment_id: int

    # 이동 유형 (RAPID, LINEAR, ARC_CW, ARC_CCW, DWELL)
    motion_type: MotionType

    # 이동 시작 위치 [X, Y, Z] (mm 단위)
    start_pos: np.ndarray

    # 이동 끝 위치 [X, Y, Z] (mm 단위)
    end_pos: np.ndarray

    # 이송 속도 (mm/min), 급속 이동 시 0
    feedrate: float

    # 주축 회전수 (RPM)
    spindle_speed: float

    # 현재 활성 공구 번호
    tool_number: int

    # NC 코드에서의 원본 라인 번호
    line_number: int

    # 원본 NC 코드 블록 문자열
    raw_block: str

    # 원호 이동 시 중심점 [X, Y, Z] (G2/G3에서 I,J,K로 지정)
    arc_center: Optional[np.ndarray] = None

    # 원호 반지름 (mm), 원호 이동 시만 유효
    arc_radius: Optional[float] = None

    # 주축 회전 여부
    spindle_on: bool = False

    def __post_init__(self):
        """numpy 배열 타입 보장"""
        if not isinstance(self.start_pos, np.ndarray):
            self.start_pos = np.array(self.start_pos, dtype=float)
        if not isinstance(self.end_pos, np.ndarray):
            self.end_pos = np.array(self.end_pos, dtype=float)
        if self.arc_center is not None and not isinstance(self.arc_center, np.ndarray):
            self.arc_center = np.array(self.arc_center, dtype=float)

    @property
    def is_cutting_move(self) -> bool:
        """절삭 이동 여부 (급속 이동이 아닌 경우)"""
        return self.motion_type in (MotionType.LINEAR, MotionType.ARC_CW, MotionType.ARC_CCW)

    @property
    def is_arc(self) -> bool:
        """원호 이동 여부"""
        return self.motion_type in (MotionType.ARC_CW, MotionType.ARC_CCW)

    def get_distance(self) -> float:
        """이동 거리를 반환합니다. 원호의 경우 호의 길이를 계산합니다."""
        if self.is_arc and self.arc_center is not None and self.arc_radius is not None:
            from app.utils.math_utils import calc_arc_angle, arc_length
            clockwise = (self.motion_type == MotionType.ARC_CW)
            angle = calc_arc_angle(self.start_pos, self.end_pos, self.arc_center, clockwise)
            return arc_length(self.arc_radius, angle)
        else:
            return float(np.linalg.norm(self.end_pos - self.start_pos))


@dataclass
class ToolpathWarning:
    """
    공구경로 검증 경고 데이터 클래스
    파싱 또는 시뮬레이션 중 발견된 문제를 저장합니다.
    """
    # 경고 심각도: "ERROR", "WARNING", "INFO"
    severity: str

    # 경고 코드 (규칙 식별자)
    code: str

    # 경고 메시지 (사용자에게 표시될 내용)
    message: str

    # NC 코드 라인 번호
    line_number: int

    # 관련 세그먼트 ID (-1이면 특정 세그먼트와 무관)
    segment_id: int = -1

    # 문제 발생 위치 (없을 수 있음)
    position: Optional[np.ndarray] = None


@dataclass
class Toolpath:
    """
    전체 공구경로 데이터 클래스
    NC 파일 파싱 결과 전체를 저장하는 최상위 컨테이너입니다.
    """
    # 이동 세그먼트 목록 (순서대로 저장)
    segments: List[MotionSegment] = field(default_factory=list)

    # 전체 이동 거리 (급속 + 절삭 포함, mm)
    total_distance: float = 0.0

    # 급속 이동 거리 (mm)
    rapid_distance: float = 0.0

    # 절삭 이동 거리 (mm)
    cutting_distance: float = 0.0

    # 예상 가공 시간 (초)
    estimated_time: float = 0.0

    # 파싱 또는 검증 중 발견된 경고 목록
    warnings: List[ToolpathWarning] = field(default_factory=list)

    # 사용된 공구 번호 집합
    used_tools: List[int] = field(default_factory=list)

    # 원본 파일 경로 (파일에서 로드한 경우)
    source_file: str = ""

    # 총 라인 수
    total_lines: int = 0

    def get_segment_count(self) -> int:
        """전체 세그먼트 수를 반환합니다."""
        return len(self.segments)

    def get_cutting_segments(self) -> List[MotionSegment]:
        """절삭 이동 세그먼트만 반환합니다."""
        return [s for s in self.segments if s.is_cutting_move]

    def get_rapid_segments(self) -> List[MotionSegment]:
        """급속 이동 세그먼트만 반환합니다."""
        return [s for s in self.segments if s.motion_type == MotionType.RAPID]

    def get_bounds(self):
        """공구경로의 전체 경계 박스를 반환합니다."""
        if not self.segments:
            return np.zeros(3), np.zeros(3)

        all_points = []
        for seg in self.segments:
            all_points.append(seg.start_pos)
            all_points.append(seg.end_pos)

        points = np.array(all_points)
        return points.min(axis=0), points.max(axis=0)
