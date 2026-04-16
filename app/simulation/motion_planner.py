"""
이동 계획(Motion Planner) 모듈
공구경로의 각 이동 세그먼트에 대해 실제 기계 동작을 계획합니다.
가감속, 코너 처리 등을 고려한 현실적인 이동 시뮬레이션을 제공합니다.
"""
from __future__ import annotations
from typing import List, Tuple
import numpy as np

from app.models.toolpath import MotionSegment, MotionType
from app.models.machine import MachineDef
from app.utils.logger import get_logger
from app.utils.math_utils import distance_3d, normalize_vector

logger = get_logger("motion_planner")


class MotionPlanner:
    """
    이동 계획 클래스

    각 이동 세그먼트에 대해 실제 기계 동작을 분석합니다.
    현재는 단순 속도 계산을 수행하며, 향후 가감속 프로파일 추가 예정입니다.
    """

    def __init__(self, machine: MachineDef):
        """
        Args:
            machine: 머신 사양 정보
        """
        self.machine = machine

    def get_effective_feedrate(self, segment: MotionSegment) -> float:
        """
        세그먼트의 실효 이송 속도를 계산합니다.
        머신 최대 이송 속도를 초과하지 않도록 제한합니다.

        Args:
            segment: 이송 속도를 계산할 세그먼트

        Returns:
            실효 이송 속도 (mm/min)
        """
        if segment.motion_type == MotionType.RAPID:
            # 급속 이동: 머신 급속 속도 사용
            return self.machine.rapid_feedrate

        if segment.feedrate <= 0:
            # 이송 속도가 0인 경우 기본값 사용
            return min(1000.0, self.machine.max_feedrate)

        # 머신 최대 이송 속도로 제한
        return min(segment.feedrate, self.machine.max_feedrate)

    def interpolate_position(self, segment: MotionSegment, t: float) -> np.ndarray:
        """
        세그먼트 상의 특정 진행률에서의 위치를 계산합니다.

        Args:
            segment: 보간할 세그먼트
            t: 진행률 (0.0 ~ 1.0)

        Returns:
            보간된 위치 [X, Y, Z]
        """
        t = max(0.0, min(1.0, t))

        if segment.motion_type in (MotionType.ARC_CW, MotionType.ARC_CCW):
            return self._interpolate_arc(segment, t)
        else:
            # 직선 보간
            return segment.start_pos + t * (segment.end_pos - segment.start_pos)

    def _interpolate_arc(self, segment: MotionSegment, t: float) -> np.ndarray:
        """
        원호 세그먼트 상의 특정 진행률에서의 위치를 계산합니다.

        Args:
            segment: 원호 세그먼트
            t: 진행률 (0.0 ~ 1.0)

        Returns:
            보간된 위치 [X, Y, Z]
        """
        if segment.arc_center is None or segment.arc_radius is None:
            # 원호 정보 없으면 직선 보간
            return segment.start_pos + t * (segment.end_pos - segment.start_pos)

        center = segment.arc_center
        start = segment.start_pos

        # 시작점의 각도 계산
        dx = start[0] - center[0]
        dy = start[1] - center[1]
        start_angle = np.arctan2(dy, dx)

        # 끝점의 각도 계산
        ex = segment.end_pos[0] - center[0]
        ey = segment.end_pos[1] - center[1]
        end_angle = np.arctan2(ey, ex)

        # 이동 방향에 따른 각도 계산
        clockwise = (segment.motion_type == MotionType.ARC_CW)
        if clockwise:
            if end_angle > start_angle:
                end_angle -= 2 * np.pi
        else:
            if end_angle < start_angle:
                end_angle += 2 * np.pi

        # 현재 진행률에서의 각도
        current_angle = start_angle + t * (end_angle - start_angle)

        # Z 보간 (나선형 이동 지원)
        z = start[2] + t * (segment.end_pos[2] - start[2])

        return np.array([
            center[0] + segment.arc_radius * np.cos(current_angle),
            center[1] + segment.arc_radius * np.sin(current_angle),
            z
        ])

    def generate_preview_points(self, segment: MotionSegment,
                                num_points: int = 20) -> List[np.ndarray]:
        """
        시각화를 위한 세그먼트 미리보기 점 목록을 생성합니다.

        Args:
            segment: 미리보기할 세그먼트
            num_points: 생성할 점 수 (원호는 더 많이 필요)

        Returns:
            위치 점 목록
        """
        if segment.is_arc:
            # 원호는 더 많은 점으로 부드럽게 표현
            n = max(num_points, 32)
        else:
            n = 2  # 직선은 시작과 끝만으로 충분

        points = []
        for i in range(n + 1):
            t = i / n
            points.append(self.interpolate_position(segment, t))

        return points
