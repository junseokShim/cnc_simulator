"""
공구 정보 패널 모듈

현재 공구 상태와 세그먼트별 가공 해석 결과를 함께 보여줍니다.
AE/AP, 스핀들 부하, 채터 위험도뿐 아니라 X/Y/Z 축 예상 진동도 표시합니다.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.models.machining_result import SegmentMachiningResult
from app.models.tool import Tool, ToolType
from app.models.toolpath import MotionType


class ToolInfoPanel(QWidget):
    """공구 정보와 현재 세그먼트 해석값을 보여주는 패널"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(6)

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

        machining_group = QGroupBox("가공 상태")
        machining_layout = QFormLayout(machining_group)
        machining_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        machining_layout.setSpacing(4)

        self._feedrate_label = self._make_value_label("0 mm/min")
        self._spindle_label = self._make_value_label("0 RPM")
        self._motion_type_label = self._make_value_label("-")
        self._spindle_on_label = self._make_value_label("정지")

        machining_layout.addRow("이송 속도:", self._feedrate_label)
        machining_layout.addRow("주축 회전:", self._spindle_label)
        machining_layout.addRow("이동 유형:", self._motion_type_label)
        machining_layout.addRow("주축 상태:", self._spindle_on_label)
        main_layout.addWidget(machining_group)

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

        analysis_group = QGroupBox("세그먼트 해석")
        analysis_layout = QFormLayout(analysis_group)
        analysis_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        analysis_layout.setSpacing(4)

        self._ae_label = self._make_value_label("0.0 mm")
        self._ap_label = self._make_value_label("0.0 mm")
        self._load_label = self._make_value_label("0.0 %")
        self._chatter_label = self._make_value_label("0.0 %")
        self._force_label = self._make_value_label("0 N")
        self._force_xyz_label = self._make_value_label("0 / 0 / 0 N")
        self._vibration_x_label = self._make_value_label("0.00 um")
        self._vibration_y_label = self._make_value_label("0.00 um")
        self._vibration_z_label = self._make_value_label("0.00 um")
        self._vibration_total_label = self._make_value_label("0.00 um")

        self._warning_label = QLabel("정상")
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet(
            "QLabel { font-size: 11px; color: #dddddd; background: #1a1a1a; "
            "padding: 4px 6px; border-radius: 2px; }"
        )

        analysis_layout.addRow("AE:", self._ae_label)
        analysis_layout.addRow("AP:", self._ap_label)
        analysis_layout.addRow("스핀들 부하:", self._load_label)
        analysis_layout.addRow("채터 위험:", self._chatter_label)
        analysis_layout.addRow("절삭력:", self._force_label)
        analysis_layout.addRow("축력 X/Y/Z:", self._force_xyz_label)
        analysis_layout.addRow("진동 X:", self._vibration_x_label)
        analysis_layout.addRow("진동 Y:", self._vibration_y_label)
        analysis_layout.addRow("진동 Z:", self._vibration_z_label)
        analysis_layout.addRow("합성 진동:", self._vibration_total_label)
        analysis_layout.addRow("주의:", self._warning_label)
        main_layout.addWidget(analysis_group)

        main_layout.addStretch()

    def _make_value_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            "QLabel { font-family: monospace; font-size: 12px; color: #00ddff; "
            "background: #1a1a1a; padding: 2px 6px; border-radius: 2px; }"
        )
        return label

    def update_tool(self, tool: Optional[Tool]):
        """현재 공구 정보를 표시합니다."""

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
        self._tool_name_label.setText(tool.name[:25] if len(tool.name) > 25 else tool.name)
        self._tool_diameter_label.setText(f"Ø {tool.diameter:.1f} mm")
        self._tool_type_label.setText(type_names.get(tool.tool_type, tool.tool_type.value))

    def update_machining_state(
        self,
        feedrate: float,
        spindle_speed: float,
        motion_type: Optional[MotionType] = None,
        spindle_on: bool = False,
    ):
        """현재 이송/주축/이동 타입 정보를 표시합니다."""

        if motion_type == MotionType.RAPID:
            self._feedrate_label.setText("급속 (RAPID)")
            self._feedrate_label.setStyleSheet(
                "QLabel { font-family: monospace; font-size: 12px; color: #5599ff; "
                "background: #1a1a1a; padding: 2px 6px; border-radius: 2px; }"
            )
        else:
            self._feedrate_label.setText(f"{feedrate:.0f} mm/min")
            self._feedrate_label.setStyleSheet(
                "QLabel { font-family: monospace; font-size: 12px; color: #00ddff; "
                "background: #1a1a1a; padding: 2px 6px; border-radius: 2px; }"
            )

        self._spindle_label.setText(f"{spindle_speed:.0f} RPM")

        if motion_type is not None:
            type_map = {
                MotionType.RAPID: "급속 (G0)",
                MotionType.LINEAR: "직선 (G1)",
                MotionType.ARC_CW: "원호 CW (G2)",
                MotionType.ARC_CCW: "원호 CCW (G3)",
                MotionType.DWELL: "정지 (G4)",
            }
            self._motion_type_label.setText(type_map.get(motion_type, str(motion_type)))

        if spindle_on:
            self._spindle_on_label.setText("회전 중")
            self._spindle_on_label.setStyleSheet(
                "QLabel { font-family: monospace; font-size: 12px; color: #00ff88; "
                "background: #1a1a1a; padding: 2px 6px; border-radius: 2px; }"
            )
        else:
            self._spindle_on_label.setText("정지")
            self._spindle_on_label.setStyleSheet(
                "QLabel { font-family: monospace; font-size: 12px; color: #ff6666; "
                "background: #1a1a1a; padding: 2px 6px; border-radius: 2px; }"
            )

    def update_stats(self, elapsed_time: float, total_distance: float, cutting_distance: float):
        """가공 진행 통계를 표시합니다."""

        mins = int(elapsed_time // 60)
        secs = int(elapsed_time % 60)
        self._elapsed_time_label.setText(f"{mins:02d}:{secs:02d}")
        self._distance_label.setText(f"{total_distance:.1f} mm")
        self._cutting_dist_label.setText(f"{cutting_distance:.1f} mm")

    def update_analysis(self, result: Optional[SegmentMachiningResult]):
        """현재 세그먼트 해석 결과를 표시합니다."""

        if result is None:
            self._ae_label.setText("0.0 mm")
            self._ap_label.setText("0.0 mm")
            self._load_label.setText("0.0 %")
            self._chatter_label.setText("0.0 %")
            self._force_label.setText("0 N")
            self._force_xyz_label.setText("0 / 0 / 0 N")
            self._vibration_x_label.setText("0.00 um")
            self._vibration_y_label.setText("0.00 um")
            self._vibration_z_label.setText("0.00 um")
            self._vibration_total_label.setText("0.00 um")
            self._warning_label.setText("해석 정보 없음")
            self._warning_label.setStyleSheet(
                "QLabel { font-size: 11px; color: #bbbbbb; background: #1a1a1a; "
                "padding: 4px 6px; border-radius: 2px; }"
            )
            return

        self._ae_label.setText(f"{result.radial_depth_ae:.2f} mm")
        self._ap_label.setText(f"{result.axial_depth_ap:.2f} mm")
        self._load_label.setText(f"{result.spindle_load_pct:.1f} %")
        self._chatter_label.setText(f"{result.chatter_risk_pct:.1f} %")
        self._force_label.setText(f"{result.estimated_cutting_force:.0f} N")
        self._force_xyz_label.setText(
            f"{result.estimated_force_x:.0f} / {result.estimated_force_y:.0f} / {result.estimated_force_z:.0f} N"
        )
        self._vibration_x_label.setText(f"{result.vibration_x_um:.2f} um")
        self._vibration_y_label.setText(f"{result.vibration_y_um:.2f} um")
        self._vibration_z_label.setText(f"{result.vibration_z_um:.2f} um")
        self._vibration_total_label.setText(f"{result.resultant_vibration_um:.2f} um")

        if result.warning_messages:
            self._warning_label.setText("\n".join(result.warning_messages[:4]))
            self._warning_label.setStyleSheet(
                "QLabel { font-size: 11px; color: #ffcc88; background: #2a1e12; "
                "padding: 4px 6px; border-radius: 2px; }"
            )
        elif result.is_cutting:
            self._warning_label.setText("안정 범위 내 절삭")
            self._warning_label.setStyleSheet(
                "QLabel { font-size: 11px; color: #88ffbb; background: #122218; "
                "padding: 4px 6px; border-radius: 2px; }"
            )
        else:
            self._warning_label.setText("비절삭 또는 에어컷")
            self._warning_label.setStyleSheet(
                "QLabel { font-size: 11px; color: #bbbbbb; background: #1a1a1a; "
                "padding: 4px 6px; border-radius: 2px; }"
            )
