"""
공구 정보 패널

현재 선택된 공구와 가공 상태, 블록별 해석 결과를 표시합니다.
직경 입력값과 내부 반경 계산값을 함께 보여 주어
직경/반경 해석 혼동을 줄이는 것이 목적입니다.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from app.models.machining_result import SegmentMachiningResult
from app.models.tool import Tool
from app.models.toolpath import MotionType


_TYPE_NAMES = {
    "EM": "엔드밀",
    "REM": "러핑 엔드밀",
    "BALL": "볼 엔드밀",
    "DR": "드릴",
    "FACE": "페이스밀",
    "TAP": "탭",
    "CUSTOM": "사용자 정의",
}


class ToolInfoPanel(QWidget):
    """현재 공구와 블록 해석 결과를 요약해 보여주는 패널"""

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
        self._tool_radius_label = self._make_value_label("-")
        self._tool_type_label = self._make_value_label("-")
        self._mapping_label = QLabel("매핑 정보 없음")
        self._mapping_label.setWordWrap(True)
        self._mapping_label.setStyleSheet(
            "QLabel { font-size: 11px; color: #d6d6d6; background: #1a1a1a; "
            "padding: 4px 6px; border-radius: 2px; }"
        )

        tool_layout.addRow("번호:", self._tool_number_label)
        tool_layout.addRow("이름:", self._tool_name_label)
        tool_layout.addRow("직경:", self._tool_diameter_label)
        tool_layout.addRow("반경:", self._tool_radius_label)
        tool_layout.addRow("타입:", self._tool_type_label)
        tool_layout.addRow("매핑:", self._mapping_label)
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
        machining_layout.addRow("NC 이동:", self._motion_type_label)
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

        analysis_group = QGroupBox("블록 해석")
        analysis_layout = QFormLayout(analysis_group)
        analysis_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        analysis_layout.setSpacing(4)

        self._machining_state_label = self._make_value_label("-")
        self._ae_label = self._make_value_label("0.0 mm")
        self._ap_label = self._make_value_label("0.0 mm")
        self._load_label = self._make_value_label("0.0 %")
        self._chatter_label = self._make_value_label("0.0 %")
        self._force_label = self._make_value_label("0 N")
        self._force_xyz_label = self._make_value_label("0 / 0 / 0 N")
        self._motion_vibration_label = self._make_value_label("0.00 um")
        self._cutting_vibration_label = self._make_value_label("0.00 um")
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

        analysis_layout.addRow("가공 상태:", self._machining_state_label)
        analysis_layout.addRow("AE:", self._ae_label)
        analysis_layout.addRow("AP:", self._ap_label)
        analysis_layout.addRow("스핀들 부하:", self._load_label)
        analysis_layout.addRow("채터 위험:", self._chatter_label)
        analysis_layout.addRow("절삭력:", self._force_label)
        analysis_layout.addRow("축력 X/Y/Z:", self._force_xyz_label)
        analysis_layout.addRow("이송 진동:", self._motion_vibration_label)
        analysis_layout.addRow("절삭 진동:", self._cutting_vibration_label)
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

    def update_tool(self, tool: Optional[Tool], requested_tool_number: int = 0):
        """현재 공구와 T코드 매핑 상태를 표시합니다."""

        if tool is None:
            display_number = requested_tool_number if requested_tool_number > 0 else 0
            self._tool_number_label.setText(f"T{display_number}")
            self._tool_name_label.setText("미정의 공구")
            self._tool_diameter_label.setText("-")
            self._tool_radius_label.setText("-")
            self._tool_type_label.setText("-")
            if requested_tool_number > 0:
                self._mapping_label.setText(
                    f"T{requested_tool_number} 공구 정의가 없습니다. "
                    "시뮬레이션은 경고와 함께 fallback 공구 모델을 사용할 수 있습니다."
                )
                self._mapping_label.setStyleSheet(
                    "QLabel { font-size: 11px; color: #ffb08a; background: #2a1b14; "
                    "padding: 4px 6px; border-radius: 2px; }"
                )
            else:
                self._mapping_label.setText("매핑 정보 없음")
                self._mapping_label.setStyleSheet(
                    "QLabel { font-size: 11px; color: #d6d6d6; background: #1a1a1a; "
                    "padding: 4px 6px; border-radius: 2px; }"
                )
            return

        category = str(tool.tool_category or tool.tool_type.value).upper()
        type_name = _TYPE_NAMES.get(category, category)
        self._tool_number_label.setText(f"T{tool.tool_number}")
        self._tool_name_label.setText(tool.name[:25] if len(tool.name) > 25 else tool.name)
        self._tool_diameter_label.setText(f"{tool.diameter_mm:.3f} mm")
        self._tool_radius_label.setText(f"{tool.radius_mm:.3f} mm")
        self._tool_type_label.setText(type_name)
        self._mapping_label.setText(
            f"T{tool.tool_number} -> {category} | 입력 직경 {tool.diameter_mm:.3f} mm | "
            f"내부 반경 {tool.radius_mm:.3f} mm"
        )
        self._mapping_label.setStyleSheet(
            "QLabel { font-size: 11px; color: #88ffbb; background: #122218; "
            "padding: 4px 6px; border-radius: 2px; }"
        )

    def update_machining_state(
        self,
        feedrate: float,
        spindle_speed: float,
        motion_type: Optional[MotionType] = None,
        spindle_on: bool = False,
    ):
        """현재 이송/주축/NC 이동 상태를 표시합니다."""

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
        """현재 블록의 해석 결과를 표시합니다."""

        if result is None:
            self._machining_state_label.setText("-")
            self._ae_label.setText("0.0 mm")
            self._ap_label.setText("0.0 mm")
            self._load_label.setText("0.0 %")
            self._chatter_label.setText("0.0 %")
            self._force_label.setText("0 N")
            self._force_xyz_label.setText("0 / 0 / 0 N")
            self._motion_vibration_label.setText("0.00 um")
            self._cutting_vibration_label.setText("0.00 um")
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

        self._machining_state_label.setText(result.machining_state or "-")
        self._ae_label.setText(f"{result.radial_depth_ae:.2f} mm")
        self._ap_label.setText(f"{result.axial_depth_ap:.2f} mm")
        self._load_label.setText(f"{result.spindle_load_pct:.1f} %")
        self._chatter_label.setText(f"{result.chatter_risk_pct:.1f} %")
        self._force_label.setText(f"{result.estimated_cutting_force:.0f} N")
        self._force_xyz_label.setText(
            f"{result.estimated_force_x:.0f} / {result.estimated_force_y:.0f} / {result.estimated_force_z:.0f} N"
        )
        self._motion_vibration_label.setText(f"{result.motion_vibration_um:.2f} um")
        self._cutting_vibration_label.setText(f"{result.cutting_vibration_um:.2f} um")
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
            self._warning_label.setText("절삭 상태 정상")
            self._warning_label.setStyleSheet(
                "QLabel { font-size: 11px; color: #88ffbb; background: #122218; "
                "padding: 4px 6px; border-radius: 2px; }"
            )
        else:
            self._warning_label.setText("비절삭 이동")
            self._warning_label.setStyleSheet(
                "QLabel { font-size: 11px; color: #bbbbbb; background: #1a1a1a; "
                "padding: 4px 6px; border-radius: 2px; }"
            )
