"""
머신 상태(Machine State) 모듈
시뮬레이션 재생 중 현재 머신의 상태를 추적합니다.
세그먼트 단위로 앞뒤 이동이 가능하며 재생 진행률을 제공합니다.
"""
from __future__ import annotations
from typing import Optional
import numpy as np

from app.models.toolpath import Toolpath, MotionSegment, MotionType
from app.utils.logger import get_logger

logger = get_logger("machine_state")


class MachineState:
    """
    시뮬레이션 재생을 위한 머신 상태 관리 클래스

    공구경로의 각 세그먼트를 순서대로 재생하며
    현재 위치, 공구, 이송 속도 등의 상태를 추적합니다.
    """

    def __init__(self):
        # 현재 재생 중인 세그먼트 인덱스
        self._current_index: int = 0

        # 로드된 공구경로 (None이면 로드 안됨)
        self._toolpath: Optional[Toolpath] = None

        # 현재 기계 위치 [X, Y, Z]
        self._current_position: np.ndarray = np.zeros(3, dtype=float)

        # 현재 활성 공구 번호
        self._current_tool: int = 0

        # 현재 이송 속도 (mm/min)
        self._feedrate: float = 0.0

        # 현재 주축 회전수 (RPM)
        self._spindle_speed: float = 0.0

        # 현재까지 경과 시간 (초)
        self._elapsed_time: float = 0.0

        # 각 세그먼트의 누적 시간 (빠른 점프를 위해 미리 계산)
        self._cumulative_times: list = []

    def load_toolpath(self, toolpath: Toolpath):
        """
        공구경로를 로드하고 상태를 초기화합니다.

        Args:
            toolpath: 재생할 Toolpath 객체
        """
        self._toolpath = toolpath
        self.reset()
        logger.info(f"공구경로 로드: {len(toolpath.segments)}개 세그먼트")

    def reset(self):
        """시뮬레이션 상태를 처음으로 되돌립니다."""
        self._current_index = 0
        self._elapsed_time = 0.0

        if self._toolpath and self._toolpath.segments:
            # 첫 번째 세그먼트의 시작 위치로 초기화
            first_seg = self._toolpath.segments[0]
            self._current_position = first_seg.start_pos.copy()
            self._current_tool = first_seg.tool_number
            self._feedrate = first_seg.feedrate
            self._spindle_speed = first_seg.spindle_speed
        else:
            self._current_position = np.zeros(3, dtype=float)
            self._current_tool = 0
            self._feedrate = 0.0
            self._spindle_speed = 0.0

    def step_forward(self) -> bool:
        """
        한 세그먼트 앞으로 이동합니다.

        Returns:
            이동 성공 여부 (마지막 세그먼트에서는 False)
        """
        if not self._toolpath or not self._toolpath.segments:
            return False

        total = len(self._toolpath.segments)
        if self._current_index >= total:
            # 이미 마지막 세그먼트까지 모두 적용된 상태
            return False

        # 현재 인덱스의 세그먼트를 적용하고 다음 인덱스로 진행
        current_seg = self._toolpath.segments[self._current_index]
        self._apply_segment(current_seg)
        self._current_index += 1
        return True

    def step_backward(self) -> bool:
        """
        한 세그먼트 뒤로 이동합니다.

        Returns:
            이동 성공 여부 (첫 번째 세그먼트에서는 False)
        """
        if not self._toolpath or self._current_index <= 0:
            return False

        self._current_index -= 1
        # 이전 세그먼트의 시작 위치로 복귀
        prev_seg = self._toolpath.segments[self._current_index]
        self._current_position = prev_seg.start_pos.copy()
        self._current_tool = prev_seg.tool_number
        self._feedrate = prev_seg.feedrate
        self._spindle_speed = prev_seg.spindle_speed

        # 경과 시간 재계산 (단순화: 세그먼트 수로 비례 계산)
        if self._toolpath.estimated_time > 0 and len(self._toolpath.segments) > 0:
            self._elapsed_time = (self._current_index / len(self._toolpath.segments)) * self._toolpath.estimated_time

        return True

    def jump_to(self, index: int):
        """
        특정 세그먼트 인덱스로 바로 이동합니다.

        Args:
            index: 이동할 세그먼트 인덱스 (0부터 시작)
        """
        if not self._toolpath:
            return

        total = len(self._toolpath.segments)
        # 범위 제한
        index = max(0, min(index, total - 1))

        self._current_index = index

        if total > 0:
            seg = self._toolpath.segments[index]
            self._current_position = seg.start_pos.copy()
            self._current_tool = seg.tool_number
            self._feedrate = seg.feedrate
            self._spindle_speed = seg.spindle_speed

            # 경과 시간 비례 계산
            if self._toolpath.estimated_time > 0:
                self._elapsed_time = (index / total) * self._toolpath.estimated_time

    def get_progress(self) -> float:
        """
        현재 재생 진행률을 반환합니다.

        Returns:
            0.0(처음) ~ 1.0(끝) 사이의 진행률
        """
        if not self._toolpath or len(self._toolpath.segments) == 0:
            return 0.0

        total = len(self._toolpath.segments)
        return min(1.0, self._current_index / total)

    def get_current_segment(self) -> Optional[MotionSegment]:
        """현재 세그먼트를 반환합니다."""
        if not self._toolpath or not self._toolpath.segments:
            return None
        if self._current_index >= len(self._toolpath.segments):
            return self._toolpath.segments[-1]
        return self._toolpath.segments[self._current_index]

    def is_at_end(self) -> bool:
        """재생이 끝까지 도달했는지 확인합니다."""
        if not self._toolpath:
            return True
        return self._current_index >= len(self._toolpath.segments)

    def _apply_segment(self, segment: MotionSegment):
        """
        세그먼트를 적용하여 상태를 업데이트합니다.

        Args:
            segment: 적용할 세그먼트
        """
        # 위치를 세그먼트 끝점으로 이동
        self._current_position = segment.end_pos.copy()
        self._current_tool = segment.tool_number
        self._feedrate = segment.feedrate
        self._spindle_speed = segment.spindle_speed

        # 이동 시간 계산 및 누적
        dist = segment.get_distance()
        if segment.motion_type == MotionType.RAPID:
            # 급속 이동: 고정 속도로 계산 (15000 mm/min)
            speed = 15000.0
        elif segment.feedrate > 0:
            speed = segment.feedrate
        else:
            speed = 1000.0  # 기본값

        if speed > 0 and dist > 0:
            time_min = dist / speed
            self._elapsed_time += time_min * 60.0  # 초로 변환

    # --- 읽기 전용 속성들 ---

    @property
    def current_segment_index(self) -> int:
        """현재 세그먼트 인덱스"""
        if self._toolpath and self._toolpath.segments:
            return min(self._current_index, len(self._toolpath.segments) - 1)
        return 0

    @property
    def completed_segments(self) -> int:
        """현재까지 적용이 완료된 세그먼트 수"""
        if self._toolpath:
            return min(self._current_index, len(self._toolpath.segments))
        return 0

    @property
    def current_position(self) -> np.ndarray:
        """현재 기계 위치 [X, Y, Z]"""
        return self._current_position.copy()

    @property
    def current_tool(self) -> int:
        """현재 공구 번호"""
        return self._current_tool

    @property
    def feedrate(self) -> float:
        """현재 이송 속도 (mm/min)"""
        return self._feedrate

    @property
    def spindle_speed(self) -> float:
        """현재 주축 회전수 (RPM)"""
        return self._spindle_speed

    @property
    def elapsed_time(self) -> float:
        """경과 시간 (초)"""
        return self._elapsed_time

    @property
    def total_segments(self) -> int:
        """전체 세그먼트 수"""
        if self._toolpath:
            return len(self._toolpath.segments)
        return 0
