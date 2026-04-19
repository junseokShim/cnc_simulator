"""
가공 해석 차트 패널 모듈

세그먼트별 스핀들 부하, 채터 위험도, X/Y/Z 축 예상 진동을 차트로 표시합니다.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.models.machining_result import MachiningAnalysis
from app.utils.logger import get_logger

logger = get_logger("analysis_panel")

_PG_AVAILABLE = False
try:
    import pyqtgraph as pg

    pg.setConfigOptions(antialias=True)
    _PG_AVAILABLE = True
except ImportError:
    logger.warning("pyqtgraph 미설치 - 차트 표시 불가")


class MachiningAnalysisPanel(QWidget):
    """가공 해석 결과를 차트로 보여주는 패널"""

    segment_hover = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._analysis: Optional[MachiningAnalysis] = None
        self._current_index: int = 0

        self._load_curve = None
        self._load_fill = None
        self._load_vline = None
        self._load_current_marker = None

        self._chatter_curve = None
        self._chatter_fill = None
        self._chatter_vline = None
        self._chatter_current_marker = None

        self._vibration_curve_x = None
        self._vibration_curve_y = None
        self._vibration_curve_z = None
        self._vibration_curve_total = None
        self._vibration_vline = None
        self._vibration_marker_x = None
        self._vibration_marker_y = None
        self._vibration_marker_z = None
        self._vibration_marker_total = None

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        header = QHBoxLayout()
        title_label = QLabel("가공 해석 차트")
        title_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #ffffff;")
        header.addWidget(title_label)
        header.addStretch()

        self._color_mode_combo = QComboBox()
        self._color_mode_combo.addItems(["기본 색상", "스핀들 부하", "채터 위험"])
        self._color_mode_combo.setToolTip("3D 뷰어 공구경로 색상 모드 선택")
        self._color_mode_combo.setFixedWidth(120)
        header.addWidget(QLabel("뷰어 색상:"))
        header.addWidget(self._color_mode_combo)
        main_layout.addLayout(header)

        if not _PG_AVAILABLE:
            label = QLabel(
                "차트 표시를 위해 pyqtgraph를 설치하세요.\n"
                "pip install pyqtgraph"
            )
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: #aaaaaa; padding: 20px;")
            main_layout.addWidget(label)
            return

        pg.setConfigOptions(background="#1e1e1e", foreground="#cccccc")

        self._load_plot = self._create_single_curve_plot(
            title="스핀들 부하 추정 (%)",
            title_color="#aaaaff",
            left_label="부하(%)",
            line_color="#5588ff",
            fill_color=(80, 120, 255, 40),
            thresholds=[80, 100],
        )
        self._load_curve = self._load_plot.plot([], [], pen=pg.mkPen("#5588ff", width=1.5))
        self._load_fill = pg.FillBetweenItem(
            self._load_plot.plot([], [], pen=None),
            self._load_curve,
            brush=pg.mkBrush(80, 120, 255, 40),
        )
        self._load_plot.addItem(self._load_fill)
        self._load_vline = pg.InfiniteLine(
            pos=0,
            angle=90,
            pen=pg.mkPen("#ffff00", width=1.5, style=Qt.PenStyle.DashLine),
        )
        self._load_plot.addItem(self._load_vline)
        self._load_current_marker = pg.ScatterPlotItem(
            size=8,
            pen=pg.mkPen("#ffff00", width=1),
            brush=pg.mkBrush("#ffff00"),
        )
        self._load_plot.addItem(self._load_current_marker)
        main_layout.addWidget(self._wrap_plot("스핀들 부하 추정 (%)", "#aaaaff", self._load_plot))

        self._chatter_plot = self._create_single_curve_plot(
            title="채터/진동 위험도 추정 (%)",
            title_color="#ffaaaa",
            left_label="위험도(%)",
            line_color="#ff6655",
            fill_color=(255, 100, 80, 40),
            thresholds=[50, 75],
        )
        self._chatter_curve = self._chatter_plot.plot([], [], pen=pg.mkPen("#ff6655", width=1.5))
        self._chatter_fill = pg.FillBetweenItem(
            self._chatter_plot.plot([], [], pen=None),
            self._chatter_curve,
            brush=pg.mkBrush(255, 100, 80, 40),
        )
        self._chatter_plot.addItem(self._chatter_fill)
        self._chatter_vline = pg.InfiniteLine(
            pos=0,
            angle=90,
            pen=pg.mkPen("#ffff00", width=1.5, style=Qt.PenStyle.DashLine),
        )
        self._chatter_plot.addItem(self._chatter_vline)
        self._chatter_current_marker = pg.ScatterPlotItem(
            size=8,
            pen=pg.mkPen("#ffff00", width=1),
            brush=pg.mkBrush("#ffff00"),
        )
        self._chatter_plot.addItem(self._chatter_current_marker)
        main_layout.addWidget(self._wrap_plot("채터/진동 위험도 추정 (%)", "#ffaaaa", self._chatter_plot))

        self._vibration_plot = pg.PlotWidget()
        self._vibration_plot.setLabel("left", "진동(um)", color="#bbffbb")
        self._vibration_plot.setLabel("bottom", "블록 번호")
        self._vibration_plot.showGrid(x=True, y=True, alpha=0.25)
        self._vibration_plot.setMinimumHeight(150)
        self._vibration_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._vibration_curve_x = self._vibration_plot.plot(
            [], [], pen=pg.mkPen("#66c2ff", width=1.4), name="X"
        )
        self._vibration_curve_y = self._vibration_plot.plot(
            [], [], pen=pg.mkPen("#88ff99", width=1.4), name="Y"
        )
        self._vibration_curve_z = self._vibration_plot.plot(
            [], [], pen=pg.mkPen("#ffaa55", width=1.4), name="Z"
        )
        self._vibration_curve_total = self._vibration_plot.plot(
            [], [],
            pen=pg.mkPen("#ffffff", width=1.6, style=Qt.PenStyle.DashLine),
            name="합성",
        )
        self._vibration_vline = pg.InfiniteLine(
            pos=0,
            angle=90,
            pen=pg.mkPen("#ffff00", width=1.5, style=Qt.PenStyle.DashLine),
        )
        self._vibration_plot.addItem(self._vibration_vline)
        self._vibration_marker_x = self._make_marker("#66c2ff")
        self._vibration_marker_y = self._make_marker("#88ff99")
        self._vibration_marker_z = self._make_marker("#ffaa55")
        self._vibration_marker_total = self._make_marker("#ffffff")
        for marker in (
            self._vibration_marker_x,
            self._vibration_marker_y,
            self._vibration_marker_z,
            self._vibration_marker_total,
        ):
            self._vibration_plot.addItem(marker)
        main_layout.addWidget(self._wrap_plot("축별 예상 진동 (um)", "#bbffbb", self._vibration_plot))

        self._summary_label = QLabel("로드 대기 중...")
        self._summary_label.setStyleSheet(
            "QLabel { font-family: monospace; font-size: 11px; color: #cccccc; "
            "background: #1a1a1a; padding: 6px; border-radius: 3px; }"
        )
        self._summary_label.setWordWrap(True)
        main_layout.addWidget(self._summary_label)

    def _create_single_curve_plot(
        self,
        title: str,
        title_color: str,
        left_label: str,
        line_color: str,
        fill_color: tuple[int, int, int, int],
        thresholds: list[int],
    ):
        del title, line_color, fill_color  # 시그니처 가독성을 위해 유지
        plot = pg.PlotWidget()
        plot.setLabel("left", left_label, color=title_color)
        plot.setLabel("bottom", "블록 번호")
        plot.setYRange(0, 105)
        plot.showGrid(x=True, y=True, alpha=0.25)
        plot.setMinimumHeight(130)
        plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        for threshold in thresholds:
            color = "#ffaa00" if threshold < 90 else "#ff4444"
            plot.addLine(
                y=threshold,
                pen=pg.mkPen(color, width=1, style=Qt.PenStyle.DashLine),
            )
        return plot

    def _wrap_plot(self, title: str, title_color: str, plot_widget):
        group = QGroupBox(title)
        group.setStyleSheet(
            f"QGroupBox {{ color: {title_color}; font-weight: bold; border: 1px solid #444; "
            "border-radius: 4px; margin-top: 6px; padding-top: 6px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; }"
        )
        layout = QVBoxLayout(group)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.addWidget(plot_widget)
        return group

    def _make_marker(self, color: str):
        return pg.ScatterPlotItem(
            size=7,
            pen=pg.mkPen(color, width=1),
            brush=pg.mkBrush(color),
        )

    def load_analysis(self, analysis: MachiningAnalysis):
        """가공 해석 결과를 로드하고 차트를 갱신합니다."""

        self._analysis = analysis

        if not _PG_AVAILABLE or not analysis.results:
            return

        x = np.arange(len(analysis.results), dtype=float)
        zeros = np.zeros_like(x)

        load_y = analysis.get_spindle_load_array()
        chatter_y = analysis.get_chatter_risk_array()
        vib_x = analysis.get_vibration_array("x")
        vib_y = analysis.get_vibration_array("y")
        vib_z = analysis.get_vibration_array("z")
        vib_total = analysis.get_vibration_array("resultant")

        self._load_curve.setData(x, load_y)
        self._load_fill.setCurves(pg.PlotDataItem(x, zeros), pg.PlotDataItem(x, load_y))
        self._chatter_curve.setData(x, chatter_y)
        self._chatter_fill.setCurves(pg.PlotDataItem(x, zeros), pg.PlotDataItem(x, chatter_y))

        self._vibration_curve_x.setData(x, vib_x)
        self._vibration_curve_y.setData(x, vib_y)
        self._vibration_curve_z.setData(x, vib_z)
        self._vibration_curve_total.setData(x, vib_total)

        x_max = max(float(len(x)), 1.0)
        self._load_plot.setXRange(0, x_max, padding=0.02)
        self._chatter_plot.setXRange(0, x_max, padding=0.02)
        self._vibration_plot.setXRange(0, x_max, padding=0.02)

        vib_peak = max(
            float(np.max(vib_x)) if len(vib_x) else 0.0,
            float(np.max(vib_y)) if len(vib_y) else 0.0,
            float(np.max(vib_z)) if len(vib_z) else 0.0,
            float(np.max(vib_total)) if len(vib_total) else 0.0,
            1.0,
        )
        self._vibration_plot.setYRange(0.0, vib_peak * 1.20, padding=0.05)

        self._update_summary()
        logger.debug("분석 차트 로드 완료: %d개 세그먼트", len(analysis.results))

    def update_current_block(self, index: int):
        """현재 재생 중인 세그먼트를 차트에 표시합니다."""

        self._current_index = index

        if not _PG_AVAILABLE or self._analysis is None:
            return

        results = self._analysis.results
        if not results or index >= len(results):
            return

        result = results[index]

        self._load_vline.setPos(index)
        self._chatter_vline.setPos(index)
        self._vibration_vline.setPos(index)

        self._load_current_marker.setData([index], [result.spindle_load_pct])
        self._chatter_current_marker.setData([index], [result.chatter_risk_pct])
        self._vibration_marker_x.setData([index], [result.vibration_x_um])
        self._vibration_marker_y.setData([index], [result.vibration_y_um])
        self._vibration_marker_z.setData([index], [result.vibration_z_um])
        self._vibration_marker_total.setData([index], [result.resultant_vibration_um])

    def _update_summary(self):
        """요약 통계 텍스트를 갱신합니다."""

        if self._analysis is None:
            return

        analysis = self._analysis
        params = analysis.model_params

        # 가공 상태 분포 계산
        results = analysis.results
        total = len(results)
        cutting_n = sum(1 for r in results if r.is_cutting)
        air_n = sum(
            1 for r in results
            if not r.is_cutting and getattr(r, "machining_state", "") != "RAPID"
        )
        rapid_n = total - cutting_n - air_n

        # 스핀들 부하 분해 평균 (절삭 세그먼트 기준)
        cutting_results = [r for r in results if r.is_cutting]
        if cutting_results:
            avg_baseline = sum(
                getattr(r, "baseline_load_pct", 0.0) for r in cutting_results
            ) / len(cutting_results)
            avg_axis = sum(
                getattr(r, "axis_motion_load_pct", 0.0) for r in cutting_results
            ) / len(cutting_results)
            avg_cutting_comp = sum(
                getattr(r, "cutting_load_pct", 0.0) for r in cutting_results
            ) / len(cutting_results)
        else:
            avg_baseline = avg_axis = avg_cutting_comp = 0.0

        machine_name = getattr(analysis, "machine_profile_name", "Unknown")

        summary = (
            f"[기계] {machine_name}\n"
            f"[상태 분포] 절삭: {cutting_n}블록 | 공중이송: {air_n}블록 | 급속: {rapid_n}블록\n"
            f"[스핀들 부하] 최대/평균: {analysis.max_spindle_load_pct:.1f}% / "
            f"{analysis.avg_spindle_load_pct:.1f}%\n"
            f"  └ 부하 분해(절삭 평균): 기저 {avg_baseline:.1f}% | "
            f"이송 {avg_axis:.1f}% | 절삭 {avg_cutting_comp:.1f}%\n"
            f"[채터 위험] 최대/평균: {analysis.max_chatter_risk * 100:.1f}% / "
            f"{analysis.avg_chatter_risk * 100:.1f}%  "
            f"고위험 블록: {analysis.high_risk_segment_count}개 ({analysis.high_risk_pct:.1f}%)\n"
            f"[절삭 조건] AE 최대/평균: {analysis.max_radial_depth_ae:.2f} / "
            f"{analysis.avg_radial_depth_ae:.2f} mm  "
            f"AP 최대/평균: {analysis.max_axial_depth_ap:.2f} / "
            f"{analysis.avg_axial_depth_ap:.2f} mm\n"
            f"[진동] 합성 최대: {analysis.max_resultant_vibration_um:.2f} um  "
            f"X/Y/Z 최대: {analysis.max_vibration_x_um:.2f}/"
            f"{analysis.max_vibration_y_um:.2f}/{analysis.max_vibration_z_um:.2f} um\n"
            f"[모델] 재료={params.get('material', '?')}  "
            f"정격출력={params.get('spindle_rated_power_w', 0) / 1000:.1f} kW  "
            f"강성={params.get('k_n_per_um', 0):.0f} N/μm  "
            f"fn={params.get('f_natural_hz', 0):.0f} Hz"
        )
        self._summary_label.setText(summary)

    def get_color_mode(self) -> str:
        """현재 선택한 뷰어 색상 모드를 반환합니다."""

        idx = self._color_mode_combo.currentIndex() if _PG_AVAILABLE else 0
        return ["default", "load", "chatter"][idx]
