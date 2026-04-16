"""
G-코드 파서 모듈
NC 파일 또는 G-코드 문자열을 파싱하여 Toolpath 객체를 생성합니다.
모달 상태를 추적하며 각 이동 블록을 MotionSegment로 변환합니다.
"""
from __future__ import annotations
import os
from typing import List, Optional, Tuple
import numpy as np

from app.parser.nc_tokenizer import tokenize_block, get_line_number, NCToken
from app.parser.modal_state import ModalState
from app.models.toolpath import (
    Toolpath, MotionSegment, MotionType, ToolpathWarning
)
from app.utils.logger import get_logger
from app.utils.math_utils import calc_arc_angle, arc_length, distance_3d

logger = get_logger("gcode_parser")


class GCodeParser:
    """
    G-코드 파서 클래스

    NC 파일을 읽어 각 블록을 해석하고 이동 세그먼트로 변환합니다.
    모달 상태를 추적하여 생략된 좌표값을 올바르게 처리합니다.
    """

    def __init__(self):
        # 현재 파싱 중인 모달 상태
        self._state = ModalState()

        # 생성된 세그먼트 목록
        self._segments: List[MotionSegment] = []

        # 파싱 경고 목록
        self._warnings: List[ToolpathWarning] = []

        # 세그먼트 카운터
        self._seg_counter = 0

        # 사용된 공구 번호 집합
        self._used_tools = set()

    def parse_file(self, filepath: str) -> Toolpath:
        """
        NC 파일을 파싱하여 Toolpath를 반환합니다.

        Args:
            filepath: NC 파일 경로

        Returns:
            파싱된 Toolpath 객체

        Raises:
            FileNotFoundError: 파일이 없을 때
            ValueError: 파일 형식이 잘못되었을 때
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"NC 파일을 찾을 수 없습니다: {filepath}")

        logger.info(f"NC 파일 파싱 시작: {filepath}")

        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()

        lines = content.splitlines()
        toolpath = self._parse_lines(lines)
        toolpath.source_file = filepath

        logger.info(f"파싱 완료: {len(toolpath.segments)}개 세그먼트, "
                    f"{len(toolpath.warnings)}개 경고")
        return toolpath

    def parse_string(self, content: str) -> Toolpath:
        """
        G-코드 문자열을 파싱하여 Toolpath를 반환합니다.

        Args:
            content: G-코드 문자열

        Returns:
            파싱된 Toolpath 객체
        """
        lines = content.splitlines()
        return self._parse_lines(lines)

    def _parse_lines(self, lines: List[str]) -> Toolpath:
        """
        라인 목록을 파싱하여 Toolpath를 생성합니다.

        Args:
            lines: NC 코드 라인 목록

        Returns:
            완성된 Toolpath 객체
        """
        # 파서 상태 초기화
        self._state = ModalState()
        self._segments = []
        self._warnings = []
        self._seg_counter = 0
        self._used_tools = set()

        # 각 라인을 순서대로 처리
        actual_line_num = 0
        for raw_line in lines:
            actual_line_num += 1
            line = raw_line.strip()

            # 빈 줄 또는 프로그램 구분자 건너뜀
            if not line or line in ('%', '/'):
                continue

            # 프로그램 번호 건너뜀 (O0001 형식)
            if line.upper().startswith('O') and len(line) <= 6:
                try:
                    int(line[1:])
                    continue
                except ValueError:
                    pass

            # N 코드에서 블록 번호 추출 (실제 라인 번호 대신 사용)
            n_number = get_line_number(line)
            display_line_num = n_number if n_number is not None else actual_line_num

            # 블록 처리
            segment = self._process_block(line, display_line_num)
            if segment is not None:
                self._segments.append(segment)

            # 프로그램 종료 코드 처리
            if self._state.program_end:
                logger.debug(f"프로그램 종료 코드 감지 (라인 {display_line_num})")
                break

        # Toolpath 객체 생성 및 통계 계산
        toolpath = self._build_toolpath()
        return toolpath

    def _process_block(self, line: str, line_num: int) -> Optional[MotionSegment]:
        """
        단일 NC 블록을 처리하여 MotionSegment를 생성합니다.

        Args:
            line: NC 코드 블록 문자열
            line_num: 라인 번호

        Returns:
            생성된 MotionSegment 또는 None (이동이 없는 경우)
        """
        # 라인을 토큰으로 분해
        tokens = tokenize_block(line)
        if not tokens:
            return None

        # 이동 전 현재 위치 저장
        start_pos = self._state.position.copy()

        # 모달 상태 업데이트 (M 코드, G 코드, F, S, T 처리)
        changes = self._state.update(tokens)

        # 공구 교환 발생 시 사용된 공구 목록에 추가
        if 'tool_change' in changes:
            tool_num = changes['tool_change']['to']
            self._used_tools.add(tool_num)

        # 목표 위치 계산
        target_pos = self._state.resolve_position(tokens)

        # 위치 변화가 없는 경우 (설정 코드만 있는 경우)
        if target_pos is None:
            # 공구 교환만 있는 경우 세그먼트 생성
            if 'tool_change' in changes:
                # 공구 교환 세그먼트를 생성 (위치 이동 없음)
                seg = self._create_segment(
                    motion_type=MotionType.RAPID,
                    start_pos=start_pos,
                    end_pos=start_pos,
                    tokens=tokens,
                    line_num=line_num,
                    raw_block=line
                )
                return seg
            return None

        # 드웰(G4) 처리
        if 'dwell' in changes:
            dwell_time = 0.0
            for token in tokens:
                if token.letter == 'P':
                    dwell_time = token.value / 1000.0  # ms → s
                elif token.letter == 'X':
                    dwell_time = token.value  # 초 단위

            seg = MotionSegment(
                segment_id=self._seg_counter,
                motion_type=MotionType.DWELL,
                start_pos=start_pos.copy(),
                end_pos=start_pos.copy(),
                feedrate=self._state.feedrate,
                spindle_speed=self._state.spindle_speed,
                tool_number=self._state.current_tool,
                line_number=line_num,
                raw_block=line,
                spindle_on=self._state.spindle_on
            )
            self._seg_counter += 1
            self._state.apply_position_change(start_pos)
            return seg

        # 현재 이동 모드에 따른 세그먼트 생성
        motion_mode = self._state.motion_mode

        if motion_mode == 0:
            # G0: 급속 이동
            seg = self._create_segment(
                motion_type=MotionType.RAPID,
                start_pos=start_pos,
                end_pos=target_pos,
                tokens=tokens,
                line_num=line_num,
                raw_block=line
            )

        elif motion_mode == 1:
            # G1: 직선 이송
            if self._state.feedrate <= 0:
                self._add_warning(
                    severity="WARNING",
                    code="ZERO_FEEDRATE",
                    message=f"G1 이동에 이송 속도가 0입니다",
                    line_number=line_num,
                    segment_id=self._seg_counter
                )
            seg = self._create_segment(
                motion_type=MotionType.LINEAR,
                start_pos=start_pos,
                end_pos=target_pos,
                tokens=tokens,
                line_num=line_num,
                raw_block=line
            )

        elif motion_mode in (2, 3):
            # G2/G3: 원호 이동
            seg = self._create_arc_segment(
                clockwise=(motion_mode == 2),
                start_pos=start_pos,
                end_pos=target_pos,
                tokens=tokens,
                line_num=line_num,
                raw_block=line
            )

        else:
            # 알 수 없는 이동 모드
            logger.warning(f"알 수 없는 이동 모드: G{motion_mode} (라인 {line_num})")
            return None

        # 위치 업데이트
        self._state.apply_position_change(target_pos)

        return seg

    def _create_segment(self, motion_type: MotionType, start_pos: np.ndarray,
                        end_pos: np.ndarray, tokens: List[NCToken],
                        line_num: int, raw_block: str) -> MotionSegment:
        """
        직선 이동 세그먼트를 생성합니다.
        """
        seg = MotionSegment(
            segment_id=self._seg_counter,
            motion_type=motion_type,
            start_pos=start_pos.copy(),
            end_pos=end_pos.copy(),
            feedrate=self._state.feedrate,
            spindle_speed=self._state.spindle_speed,
            tool_number=self._state.current_tool,
            line_number=line_num,
            raw_block=raw_block,
            spindle_on=self._state.spindle_on
        )
        self._seg_counter += 1
        return seg

    def _create_arc_segment(self, clockwise: bool, start_pos: np.ndarray,
                             end_pos: np.ndarray, tokens: List[NCToken],
                             line_num: int, raw_block: str) -> MotionSegment:
        """
        원호 이동 세그먼트를 생성합니다.
        I, J, K 오프셋으로 원호 중심을 계산합니다.
        """
        motion_type = MotionType.ARC_CW if clockwise else MotionType.ARC_CCW

        # I, J, K 오프셋 추출 (항상 증분 좌표)
        offsets = self._state.get_arc_offsets(tokens)

        # 원호 중심 계산 (현재 위치 + 오프셋)
        arc_center = start_pos.copy()
        arc_center[0] += offsets[0]  # I (X 오프셋)
        arc_center[1] += offsets[1]  # J (Y 오프셋)
        arc_center[2] += offsets[2]  # K (Z 오프셋)

        # 반경 계산: 시작점에서 중심까지의 거리
        # XY 평면 기준 (G17)
        dx = start_pos[0] - arc_center[0]
        dy = start_pos[1] - arc_center[1]
        arc_radius = float(np.sqrt(dx**2 + dy**2))

        # 반경 검증: 시작점과 끝점의 중심까지 거리가 비슷해야 함
        dx_end = end_pos[0] - arc_center[0]
        dy_end = end_pos[1] - arc_center[1]
        radius_end = float(np.sqrt(dx_end**2 + dy_end**2))

        radius_diff = abs(arc_radius - radius_end)
        if arc_radius > 0.001 and radius_diff / arc_radius > 0.01:
            self._add_warning(
                severity="WARNING",
                code="ARC_RADIUS_MISMATCH",
                message=f"원호 반경 불일치: 시작={arc_radius:.3f}, 끝={radius_end:.3f}",
                line_number=line_num,
                segment_id=self._seg_counter
            )

        seg = MotionSegment(
            segment_id=self._seg_counter,
            motion_type=motion_type,
            start_pos=start_pos.copy(),
            end_pos=end_pos.copy(),
            feedrate=self._state.feedrate,
            spindle_speed=self._state.spindle_speed,
            tool_number=self._state.current_tool,
            line_number=line_num,
            raw_block=raw_block,
            arc_center=arc_center,
            arc_radius=arc_radius,
            spindle_on=self._state.spindle_on
        )
        self._seg_counter += 1
        return seg

    def _add_warning(self, severity: str, code: str, message: str,
                     line_number: int, segment_id: int = -1,
                     position: Optional[np.ndarray] = None):
        """파싱 경고를 추가합니다."""
        warning = ToolpathWarning(
            severity=severity,
            code=code,
            message=message,
            line_number=line_number,
            segment_id=segment_id,
            position=position
        )
        self._warnings.append(warning)
        log_fn = logger.error if severity == "ERROR" else logger.warning
        log_fn(f"[{severity}] 라인 {line_number}: {message}")

    def _build_toolpath(self) -> Toolpath:
        """
        파싱된 세그먼트와 통계로 Toolpath 객체를 생성합니다.
        """
        total_distance = 0.0
        rapid_distance = 0.0
        cutting_distance = 0.0

        for seg in self._segments:
            dist = seg.get_distance()
            total_distance += dist

            if seg.motion_type == MotionType.RAPID:
                rapid_distance += dist
            elif seg.is_cutting_move:
                cutting_distance += dist

        toolpath = Toolpath(
            segments=self._segments,
            total_distance=total_distance,
            rapid_distance=rapid_distance,
            cutting_distance=cutting_distance,
            warnings=self._warnings,
            used_tools=list(self._used_tools),
            total_lines=self._seg_counter
        )

        return toolpath
