"""
모달 상태(Modal State) 관리 모듈
NC 코드 파싱 중 지속되는 상태값들을 추적합니다.
G-코드는 모달 명령어로, 한번 설정하면 다음 명령이 올 때까지 유지됩니다.
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional
import numpy as np

from app.parser.nc_tokenizer import NCToken
from app.utils.logger import get_logger

logger = get_logger("modal_state")


class ModalState:
    """
    NC 코드 파싱 중 모달(지속) 상태를 관리하는 클래스

    모달 그룹:
    - 이동 모드: G0(급속), G1(직선), G2(원호CW), G3(원호CCW)
    - 평면 선택: G17(XY), G18(XZ), G19(YZ)
    - 단위: G20(인치), G21(mm)
    - 좌표계: G90(절대), G91(증분)
    """

    def __init__(self):
        # 이동 모드: 0=G0(급속), 1=G1(직선), 2=G2(원호CW), 3=G3(원호CCW)
        self.motion_mode: int = 0

        # 가공 평면: 17=G17(XY평면), 18=G18(XZ평면), 19=G19(YZ평면)
        self.plane: int = 17

        # 단위계: "mm"(G21) 또는 "inch"(G20)
        self.units: str = "mm"

        # 좌표 모드: True=절대(G90), False=증분(G91)
        self.absolute: bool = True

        # 현재 이송 속도 (mm/min 또는 inch/min)
        self.feedrate: float = 0.0

        # 주축 회전수 (RPM)
        self.spindle_speed: float = 0.0

        # 주축 작동 여부
        self.spindle_on: bool = False

        # 주축 회전 방향: True=정회전(M3), False=역회전(M4)
        self.spindle_clockwise: bool = True

        # 현재 활성 공구 번호
        self.current_tool: int = 0

        # 현재 기계 위치 [X, Y, Z] (mm)
        self.position: np.ndarray = np.zeros(3, dtype=float)

        # 냉각수 작동 여부 (M8=ON, M9=OFF)
        self.coolant: bool = False

        # 프로그램 종료 여부 (M30, M2)
        self.program_end: bool = False

        # 다음 이동에 사용할 공구 번호 (T코드 후 M6 전까지 대기)
        self._pending_tool: Optional[int] = None

    def update(self, tokens: List[NCToken]) -> Dict[str, Any]:
        """
        토큰 목록으로 모달 상태를 업데이트하고 변경된 항목을 반환합니다.

        Args:
            tokens: 파싱된 NC 토큰 목록

        Returns:
            변경된 상태 항목 딕셔너리 {상태명: 새로운값}
        """
        changes: Dict[str, Any] = {}

        # 토큰을 순서대로 처리
        for token in tokens:
            letter = token.letter
            value = token.value

            if letter == 'G':
                # G 코드 처리 - 정수로 반올림하여 처리
                g_code = int(round(value))
                self._process_g_code(g_code, changes)

            elif letter == 'M':
                # M 코드 처리 (보조 기능)
                m_code = int(round(value))
                self._process_m_code(m_code, changes)

            elif letter == 'F':
                # 이송 속도 설정
                if value != self.feedrate:
                    changes['feedrate'] = value
                    self.feedrate = value

            elif letter == 'S':
                # 주축 회전수 설정
                if value != self.spindle_speed:
                    changes['spindle_speed'] = value
                    self.spindle_speed = value

            elif letter == 'T':
                # 공구 선택 (M6 전까지 대기)
                tool_num = int(round(value))
                if tool_num != self._pending_tool:
                    self._pending_tool = tool_num
                    changes['pending_tool'] = tool_num

        return changes

    def _process_g_code(self, g_code: int, changes: Dict[str, Any]):
        """G 코드에 따라 모달 상태를 업데이트합니다."""

        # 이동 모드 그룹 (모달 그룹 1)
        if g_code in (0, 1, 2, 3):
            if self.motion_mode != g_code:
                changes['motion_mode'] = g_code
                self.motion_mode = g_code

        # 평면 선택 그룹 (모달 그룹 2)
        elif g_code in (17, 18, 19):
            if self.plane != g_code:
                changes['plane'] = g_code
                self.plane = g_code

        # 단위 그룹 (모달 그룹 6)
        elif g_code == 20:
            if self.units != "inch":
                changes['units'] = "inch"
                self.units = "inch"
                logger.info("단위 변경: 인치(G20)")

        elif g_code == 21:
            if self.units != "mm":
                changes['units'] = "mm"
                self.units = "mm"
                logger.info("단위 변경: mm(G21)")

        # 좌표계 그룹 (모달 그룹 3)
        elif g_code == 90:
            if not self.absolute:
                changes['absolute'] = True
                self.absolute = True

        elif g_code == 91:
            if self.absolute:
                changes['absolute'] = False
                self.absolute = False

        # 원점 복귀 (단순 처리: 위치를 0으로 설정)
        elif g_code == 28:
            # G28은 실제 머신 원점으로 복귀하는 명령이지만,
            # 시뮬레이션에서는 Z축만 0으로 처리 (일반적으로 G28 Z0 형태)
            changes['home'] = True

        # 드웰 (G4): 별도 처리 필요
        elif g_code == 4:
            changes['dwell'] = True

    def _process_m_code(self, m_code: int, changes: Dict[str, Any]):
        """M 코드에 따라 보조 기능 상태를 업데이트합니다."""

        if m_code == 3:
            # M3: 주축 정회전
            if not self.spindle_on or not self.spindle_clockwise:
                changes['spindle_on'] = True
                changes['spindle_clockwise'] = True
                self.spindle_on = True
                self.spindle_clockwise = True

        elif m_code == 4:
            # M4: 주축 역회전
            if not self.spindle_on or self.spindle_clockwise:
                changes['spindle_on'] = True
                changes['spindle_clockwise'] = False
                self.spindle_on = True
                self.spindle_clockwise = False

        elif m_code == 5:
            # M5: 주축 정지
            if self.spindle_on:
                changes['spindle_on'] = False
                self.spindle_on = False

        elif m_code == 6:
            # M6: 공구 교환 실행 (대기 중인 공구로 변경)
            if self._pending_tool is not None:
                old_tool = self.current_tool
                self.current_tool = self._pending_tool
                changes['tool_change'] = {
                    'from': old_tool,
                    'to': self.current_tool
                }
                self._pending_tool = None
                logger.debug(f"공구 교환: T{old_tool} → T{self.current_tool}")

        elif m_code == 8:
            # M8: 냉각수 ON
            if not self.coolant:
                changes['coolant'] = True
                self.coolant = True

        elif m_code == 9:
            # M9: 냉각수 OFF
            if self.coolant:
                changes['coolant'] = False
                self.coolant = False

        elif m_code in (30, 2):
            # M30/M2: 프로그램 종료
            changes['program_end'] = True
            self.program_end = True

    def apply_position_change(self, new_pos: np.ndarray):
        """
        기계 위치를 업데이트합니다.

        Args:
            new_pos: 새 위치 [X, Y, Z]
        """
        self.position = new_pos.copy()

    def resolve_position(self, tokens: List[NCToken]) -> Optional[np.ndarray]:
        """
        토큰에서 목표 위치를 계산합니다.
        절대 모드와 증분 모드를 모두 처리합니다.

        Args:
            tokens: 위치 관련 토큰 목록 (X, Y, Z 포함 가능)

        Returns:
            목표 위치 [X, Y, Z] 또는 None (위치 정보 없는 경우)
        """
        # 현재 위치에서 시작
        target = self.position.copy()
        has_position = False

        # 축 인덱스 매핑
        axis_map = {'X': 0, 'Y': 1, 'Z': 2}

        for token in tokens:
            if token.letter in axis_map:
                idx = axis_map[token.letter]
                if self.absolute:
                    # 절대 좌표: 직접 설정
                    target[idx] = token.value
                else:
                    # 증분 좌표: 현재 위치에 더함
                    target[idx] = self.position[idx] + token.value
                has_position = True

        return target if has_position else None

    def get_arc_offsets(self, tokens: List[NCToken]) -> np.ndarray:
        """
        원호 이동의 중심 오프셋(I, J, K)을 토큰에서 추출합니다.

        Args:
            tokens: I, J, K 값을 포함하는 토큰 목록

        Returns:
            중심 오프셋 [I, J, K] (없으면 0)
        """
        offsets = np.zeros(3, dtype=float)
        ijk_map = {'I': 0, 'J': 1, 'K': 2}

        for token in tokens:
            if token.letter in ijk_map:
                offsets[ijk_map[token.letter]] = token.value

        return offsets

    def clone(self) -> 'ModalState':
        """현재 상태의 깊은 복사본을 반환합니다."""
        new_state = ModalState()
        new_state.motion_mode = self.motion_mode
        new_state.plane = self.plane
        new_state.units = self.units
        new_state.absolute = self.absolute
        new_state.feedrate = self.feedrate
        new_state.spindle_speed = self.spindle_speed
        new_state.spindle_on = self.spindle_on
        new_state.spindle_clockwise = self.spindle_clockwise
        new_state.current_tool = self.current_tool
        new_state.position = self.position.copy()
        new_state.coolant = self.coolant
        new_state.program_end = self.program_end
        new_state._pending_tool = self._pending_tool
        return new_state
