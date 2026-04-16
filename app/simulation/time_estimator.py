"""
가공 시간 추정(Time Estimator) 모듈
공구경로의 각 세그먼트에 대한 가공 시간을 추정합니다.
이송 속도와 거리를 기반으로 계산하며 공구 교환 시간도 포함합니다.
"""
from __future__ import annotations
from typing import Optional

from app.models.toolpath import Toolpath, MotionSegment, MotionType
from app.models.machine import MachineDef
from app.utils.logger import get_logger

logger = get_logger("time_estimator")

# 공구 교환 예상 시간 (초)
TOOL_CHANGE_TIME_SEC = 5.0

# 주축 가속/감속 예상 시간 (초)
SPINDLE_RAMP_TIME_SEC = 2.0


class TimeEstimator:
    """
    가공 시간 추정 클래스

    거리와 이송 속도를 기반으로 각 세그먼트의 가공 시간을 계산합니다.
    급속 이동과 절삭 이동을 구분하여 처리합니다.
    """

    def estimate_segment_time(self, segment: MotionSegment,
                              rapid_feedrate: float = 15000.0) -> float:
        """
        단일 세그먼트의 가공 시간을 추정합니다.

        계산 방식:
        - 급속 이동(G0): 머신 급속 이송 속도 사용
        - 직선/원호 이동: 프로그래밍된 이송 속도 사용
        - 드웰: P/X 값으로 지정된 시간

        Args:
            segment: 시간을 추정할 세그먼트
            rapid_feedrate: 급속 이동 속도 (mm/min)

        Returns:
            추정 가공 시간 (초)
        """
        if segment.motion_type == MotionType.DWELL:
            # 드웰은 이동 거리가 없으므로 별도 처리
            # 실제 드웰 시간은 세그먼트에서 가져와야 하지만 여기선 0으로 처리
            return 0.0

        # 이동 거리 계산
        distance = segment.get_distance()

        if distance < 1e-6:
            # 이동 거리가 거의 없는 경우
            return 0.0

        if segment.motion_type == MotionType.RAPID:
            # 급속 이동: 머신 최대 급속 속도 사용
            speed_mm_min = rapid_feedrate if rapid_feedrate > 0 else 15000.0
        else:
            # 절삭 이동: 프로그래밍된 이송 속도 사용
            if segment.feedrate > 0:
                speed_mm_min = segment.feedrate
            else:
                # 이송 속도가 0인 경우 기본값 사용 (경고 상황)
                speed_mm_min = 1000.0

        # 시간 계산 (mm/min → 초 변환)
        time_minutes = distance / speed_mm_min
        time_seconds = time_minutes * 60.0

        return time_seconds

    def estimate_total_time(self, toolpath: Toolpath, machine: MachineDef) -> float:
        """
        전체 공구경로의 예상 가공 시간을 계산합니다.

        계산 항목:
        1. 각 이동 세그먼트의 이동 시간
        2. 공구 교환 시간
        3. 주축 가속/감속 시간 (근사값)

        Args:
            toolpath: 시간을 추정할 공구경로
            machine: 머신 사양 (급속 이송 속도 등)

        Returns:
            총 예상 가공 시간 (초)
        """
        if not toolpath.segments:
            return 0.0

        total_time = 0.0
        tool_change_count = 0
        prev_tool = -1

        for segment in toolpath.segments:
            # 세그먼트 이동 시간
            seg_time = self.estimate_segment_time(segment, machine.rapid_feedrate)
            total_time += seg_time

            # 공구 교환 감지
            if segment.tool_number != prev_tool and prev_tool != -1:
                total_time += TOOL_CHANGE_TIME_SEC
                tool_change_count += 1

            prev_tool = segment.tool_number

        logger.debug(f"총 가공 시간 추정: {total_time:.1f}초 "
                     f"(공구 교환 {tool_change_count}회 포함)")

        return total_time

    def format_time(self, seconds: float) -> str:
        """
        초를 시:분:초 형식의 문자열로 변환합니다.

        Args:
            seconds: 변환할 시간 (초)

        Returns:
            형식화된 시간 문자열 (예: "1시간 23분 45초")
        """
        if seconds < 0:
            return "0초"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        parts = []
        if hours > 0:
            parts.append(f"{hours}시간")
        if minutes > 0:
            parts.append(f"{minutes}분")
        if secs > 0 or not parts:
            parts.append(f"{secs}초")

        return " ".join(parts)

    def get_segment_cumulative_times(self, toolpath: Toolpath,
                                     rapid_feedrate: float = 15000.0) -> list:
        """
        각 세그먼트까지의 누적 시간 목록을 반환합니다.
        재생 중 특정 시간으로 점프할 때 사용됩니다.

        Args:
            toolpath: 대상 공구경로
            rapid_feedrate: 급속 이동 속도 (mm/min)

        Returns:
            누적 시간 목록 (초 단위, 세그먼트 수+1 개)
        """
        cumulative = [0.0]
        running_time = 0.0

        for segment in toolpath.segments:
            seg_time = self.estimate_segment_time(segment, rapid_feedrate)
            running_time += seg_time
            cumulative.append(running_time)

        return cumulative
