"""
재료 제거 시뮬레이션(Material Removal) 모듈
공구경로에 따라 소재에서 재료를 제거하는 시뮬레이션을 수행합니다.
Z-맵 기반으로 절삭 이동마다 소재를 업데이트합니다.
"""
from __future__ import annotations
from typing import Dict
import numpy as np

from app.models.toolpath import Toolpath, MotionType
from app.models.tool import Tool
from app.geometry.stock_model import StockModel
from app.utils.logger import get_logger

logger = get_logger("material_removal")


class MaterialRemovalSimulator:
    """
    재료 제거 시뮬레이션 클래스

    공구경로의 각 절삭 이동에 대해 소재에서 재료를 제거합니다.
    급속 이동(G0)은 재료 제거 없이 충돌 검사만 수행합니다.
    """

    def __init__(self):
        # 처리된 세그먼트 수
        self._processed_segments = 0

        # 재료 제거된 셀 수
        self._removed_cells = 0

    def simulate(self, toolpath: Toolpath, stock: StockModel,
                 tools: Dict[int, Tool],
                 analysis_results: Dict[int, dict] | None = None) -> StockModel:
        """
        전체 공구경로에 대해 재료 제거를 시뮬레이션합니다.

        처리 방식:
        1. 절삭 이동(G1, G2, G3)에 대해서만 재료 제거
        2. 급속 이동(G0)은 재료 제거하지 않음 (충돌 가능성 있음)
        3. 공구가 정의되지 않은 경우 건너뜀

        Args:
            toolpath: 재생할 공구경로
            stock: 재료 제거를 적용할 소재 모델 (원본 수정됨)
            tools: 공구 번호 → Tool 매핑 딕셔너리

        Returns:
            재료가 제거된 소재 모델 (입력과 동일 객체)
        """
        self._processed_segments = 0
        self._removed_cells = 0

        if not toolpath.segments:
            logger.warning("공구경로 세그먼트가 없습니다")
            return stock

        total_segments = len(toolpath.segments)
        cutting_count = 0

        for i, segment in enumerate(toolpath.segments):
            # 급속 이동과 드웰은 재료 제거 건너뜀
            if segment.motion_type == MotionType.RAPID:
                # 급속 이동 중 소재 내부 진입 여부 로깅 (충돌 가능성)
                stock_height = stock.get_height_at(
                    segment.end_pos[0], segment.end_pos[1]
                )
                if segment.end_pos[2] < stock_height:
                    logger.debug(
                        f"급속 이동이 소재 내부로 진입할 수 있음: "
                        f"세그먼트 {segment.segment_id}, "
                        f"위치 ({segment.end_pos[0]:.1f}, {segment.end_pos[1]:.1f}, "
                        f"{segment.end_pos[2]:.1f}), "
                        f"소재 높이: {stock_height:.1f}"
                    )
                self._processed_segments += 1
                continue

            if segment.motion_type == MotionType.DWELL:
                # 드웰은 위치 변화 없음
                self._processed_segments += 1
                continue

            if not segment.spindle_on:
                # 주축 정지 상태의 이동은 가공 흔적으로 반영하지 않습니다.
                self._processed_segments += 1
                continue

            # 현재 세그먼트에 사용되는 공구 조회
            current_tool = tools.get(segment.tool_number)
            if current_tool is None:
                logger.warning(
                    f"공구 T{segment.tool_number}가 정의되지 않았습니다. "
                    f"세그먼트 {segment.segment_id} 건너뜀"
                )
                self._processed_segments += 1
                continue

            # 원호 이동은 여러 직선 구간으로 분할하여 처리
            seg_metrics = analysis_results.get(segment.segment_id) if analysis_results else None

            if segment.is_arc:
                self._remove_arc_material(segment, stock, current_tool, seg_metrics)
            else:
                # 직선 이동: 직접 재료 제거
                stock.remove_material(
                    segment.start_pos, segment.end_pos, current_tool, seg_metrics
                )

            cutting_count += 1
            self._processed_segments += 1

            # 진행 상황 로그 (100 세그먼트마다)
            if (i + 1) % 100 == 0:
                progress = (i + 1) / total_segments * 100
                logger.debug(f"재료 제거 진행: {progress:.0f}% ({i+1}/{total_segments})")

        logger.info(
            f"재료 제거 시뮬레이션 완료: "
            f"총 {total_segments}개 세그먼트, "
            f"절삭 {cutting_count}개 처리"
        )

        return stock

    def _remove_arc_material(self, segment, stock: StockModel, tool: Tool,
                             segment_metrics: dict | None = None):
        """
        원호 이동에 대한 재료 제거를 수행합니다.
        원호를 여러 직선 구간으로 분할하여 처리합니다.

        Args:
            segment: 원호 이동 세그먼트
            stock: 소재 모델
            tool: 공구 정보
        """
        if segment.arc_center is None or segment.arc_radius is None:
            # 원호 정보가 없으면 직선으로 처리
            stock.remove_material(segment.start_pos, segment.end_pos, tool, segment_metrics)
            return

        from app.utils.math_utils import calc_arc_angle

        # 원호 분할 수 계산 (반경에 비례하여 충분히 분할)
        clockwise = (segment.motion_type == MotionType.ARC_CW)
        angle = calc_arc_angle(segment.start_pos, segment.end_pos,
                               segment.arc_center, clockwise)

        # 적절한 분할 수 계산 (최소 4개, 최대 64개)
        arc_length = segment.arc_radius * angle
        num_steps = max(4, min(64, int(arc_length / (tool.radius * 0.5))))

        from app.simulation.motion_planner import MotionPlanner
        from app.models.machine import create_default_machine

        # 임시 MotionPlanner로 보간점 생성
        planner = MotionPlanner(create_default_machine())
        points = planner.generate_preview_points(segment, num_steps)

        # 각 구간에 대해 재료 제거
        for i in range(len(points) - 1):
            stock.remove_material(points[i], points[i + 1], tool, segment_metrics)

    def simulate_step(self, segment_index: int, toolpath: Toolpath,
                      stock: StockModel, tools: Dict[int, Tool],
                      segment_metrics: dict | None = None):
        """
        단일 세그먼트의 재료 제거를 수행합니다.
        실시간 시뮬레이션 재생 시 사용됩니다.

        Args:
            segment_index: 처리할 세그먼트 인덱스
            toolpath: 공구경로
            stock: 소재 모델
            tools: 공구 딕셔너리
        """
        if segment_index >= len(toolpath.segments):
            return

        segment = toolpath.segments[segment_index]

        if segment.motion_type == MotionType.RAPID or segment.motion_type == MotionType.DWELL:
            return

        if not segment.spindle_on:
            return

        current_tool = tools.get(segment.tool_number)
        if current_tool is None:
            return

        if segment.is_arc:
            self._remove_arc_material(segment, stock, current_tool, segment_metrics)
        else:
            stock.remove_material(segment.start_pos, segment.end_pos, current_tool, segment_metrics)
