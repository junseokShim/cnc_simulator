"""
공구 정보 패널(Tool Info Panel) 모듈
현재 활성 공구와 가공 상태 정보를 표시하는 패널 위젯입니다.
"""
from __future__ import annotations
from typing import Optional
import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout,
    QGroupBox, QLabel
)
from PySide6.QtCore import Qt

from app.models.tool import Tool, ToolType
from app.models.toolpath import MotionType
from app.utils.logger import get_logger

logger = get_logger("tool_info_panel")


class ToolInfoPanel(QWidget):
    """
    공구 정보 및 가공 상태 표시 패널

    현재 공구 번호, 이름, 직경, 종류와 함께
    현재 이송 속도, 주축 회전수, 이동 유형, 경과 시간 등을 표시합니다.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """UI 레이아웃을 설정합니다."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(6)

        # --- 공구 정보 그룹 ---
        tool_group = QGroupBox("공구 정보")
        tool_layout = QFormLayout(tool_group)
        tool_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        tool_layout.setSpacing(4)

        self._tool_number_label = self._make_value_label("T0")
        self._tool_name_label = self._make_value_label("-")
        self._tool_diameter_label = self._make_value_label("-")
        self._tool_type_label = self._make_value_label("-")

        tool_layout.addRow("번호:", self._tool_number_label)
        tool_layout.addRow("이름:", self._tool_name_label)
        tool_layout.addRow("직경:", self._tool_diameter_label)
        tool_layout.addRow("종류:", self._tool_type_label)

        main_layout.addWidget(tool_group)

        # --- 가공 상태 그룹 ---
        machining_group = QGroupBox("가공 상태")
        machining_layout = QFormLayout(machining_group)
        machining_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        machining_layout.setSpacing(4)

        self._feedrate_label = self._make_value_label("0 mm/min")
        self._spindle_label = self._make_value_label("0 RPM")
        self._motion_type_label = self._make_value_label("-")
        self._spindle_on_label = self._make_value_label("정지")

        machining_layout.addRow("이송 속도:", self._feedrate_label)
        machining_layout.addRow("주축 회전수:", self._spindle_label)
        machining_layout.addRow("이동 유형:", self._motion_type_label)
        machining_layout.addRow("주축 상태:", self._spindle_on_label)

        main_layout.addWidget(machining_group)

        # --- 시간/거리 그룹 ---
        stats_group = QGroupBox("통계")
        stats_layout = QFormLayout(stats_group)
        stats_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        stats_layout.setSpacing(4)

        self._elapsed_time_label = self._make_value_label("00:00")
        self._distance_label = self._make_value_label("0.0 mm")
        self._cutting_dist_label = self._make_value_label("0.0 mm")

        stats_layout.addRow("경과 시간:", self._elapsed_time_label)
        stats_layout.addRow("총 이동 거리:", self._distance_label)
        stats_layout.addRow("절삭 거리:", self._cutting_dist_label)

        main_layout.addWidget(stats_group)

        main_layout.addStretch()

    def _make_value_label(self, text: str) -> QLabel:
        """값 표시용 레이블을 생성합니다."""
        label = QLabel(text)
        label.setStyleSheet(
            "QLabel { "
            "font-family: monospace; "
            "font-size: 12px; "
            "color: #00ddff; "
            "background: #1a1a1a; "
            "padding: 2px 6px; "
            "border-radius: 2px; "
            "}"
        )
        return label

    def update_tool(self, tool: Optional[Tool]):
        """
        공구 정보를 업데이트합니다.

        Args:
            tool: 표시할 Tool 인스턴스 (없으면 None)
        """
        if tool is None:
            self._tool_number_label.setText("T0")
            self._tool_name_label.setText("-")
            self._tool_diameter_label.setText("-")
            self._tool_type_label.setText("-")
            return

        type_names = {
            ToolType.END_MILL: "플랫 엔드밀",
            ToolType.BALL_END: "볼 엔드밀",
            ToolType.DRILL: "드릴",
            ToolType.FACE_MILL: "페이스밀",
            ToolType.TAP: "탭",
        }

        self._tool_number_label.setText(f"T{tool.tool_number}")
        self._tool_name_label.setText(tool.name[:25] if len(tool.name) > 25
                                      else tool.name)
        self._tool_diameter_label.setText(f"φ {tool.diameter:.1f} mm")
        self._tool_type_label.setText(type_names.get(tool.tool_type,
                                                       tool.tool_type.value))

    def update_machining_state(self, feedrate: float, spindle_speed: float,
                                motion_type: Optional[MotionType] = None,
                                spindle_on: bool = False):
        """
        가공 상태 정보를 업데이트합니다.

        Args:
            feedrate: 현재 이송 속도 (mm/min)
            spindle_speed: 현재 주축 회전수 (RPM)
            motion_type: 현재 이동 유형
            spindle_on: 주축 작동 여부
        """
        # 이송 속도 표시 (급속 이동은 특별 표시)
        if motion_type == MotionType.RAPID:
            self._feedrate_label.setText("급속 (RAPID)")
            self._feedrate_label.setStyleSheet(
                "QLabel { font-family: monospace; font-size: 12px; "
                "color: #5599ff; background: #1a1a1a; padding: 2px 6px; "
                "border-radius: 2px; }"
            )
        else:
            self._feedrate_label.setText(f"{feedrate:.0f} mm/min")
            self._feedrate_label.setStyleSheet(
                "QLabel { font-family: monospace; font-size: 12px; "
                "color: #00ddff; background: #1a1a1a; padding: 2px 6px; "
                "border-radius: 2px; }"
            )

        self._spindle_label.setText(f"{spindle_speed:.0f} RPM")

        # 이동 유형 표시
        if motion_type is not None:
            type_map = {
                MotionType.RAPID: "급속 (G0)",
                MotionType.LINEAR: "직선 (G1)",
                MotionType.ARC_CW: "원호 CW (G2)",
                MotionType.ARC_CCW: "원호 CCW (G3)",
                MotionType.DWELL: "드웰 (G4)",
            }
            self._motion_type_label.setText(type_map.get(motion_type, str(motion_type)))

        # 주축 상태 표시
        if spindle_on:
            self._spindle_on_label.setText("회전 중")
            self._spindle_on_label.setStyleSheet(
                "QLabel { font-family: monospace; font-size: 12px; "
                "color: #00ff88; background: #1a1a1a; padding: 2px 6px; "
                "border-radius: 2px; }"
            )
        else:
            self._spindle_on_label.setText("정지")
            self._spindle_on_label.setStyleSheet(
                "QLabel { font-family: monospace; font-size: 12px; "
                "color: #ff6666; background: #1a1a1a; padding: 2px 6px; "
                "border-radius: 2px; }"
            )

    def update_stats(self, elapsed_time: float, total_distance: float,
                     cutting_distance: float):
        """
        통계 정보를 업데이트합니다.

        Args:
            elapsed_time: 경과 시간 (초)
            total_distance: 총 이동 거리 (mm)
            cutting_distance: 절삭 거리 (mm)
        """
        # 시간 형식 변환
        mins = int(elapsed_time // 60)
        secs = int(elapsed_time % 60)
        self._elapsed_time_label.setText(f"{mins:02d}:{secs:02d}")

        self._distance_label.setText(f"{total_distance:.1f} mm")
        self._cutting_dist_label.setText(f"{cutting_distance:.1f} mm")
