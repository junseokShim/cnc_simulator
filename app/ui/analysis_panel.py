"""
가공 해석 패널(Analysis Panel) 모듈

스핀들 부하와 채터/진동 위험도를 블록별로 차트로 표시합니다.
pyqtgraph PlotWidget을 사용하여 실시간 업데이트가 가능한 그래프를 제공합니다.

[표시 내용]
- 상단 차트: 스핀들 부하 (%) vs 블록 번호
- 하단 차트: 채터 위험도 (%) vs 블록 번호
- 현재 블록 위치: 수직 점선으로 표시
- 위험 임계값: 수평 기준선 표시
"""
from __future__ import annotations
from typing import Optional, List
import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGroupBox, QComboBox, QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, Signal

from app.models.machining_result import MachiningAnalysis
from app.utils.logger import get_logger

logger = get_logger("analysis_panel")

# pyqtgraph 가용성 확인
_PG_AVAILABLE = False
try:
    import pyqtgraph as pg
    pg.setConfigOptions(antialias=True)
    _PG_AVAILABLE = True
except ImportError:
    logger.warning("pyqtgraph 미설치 - 차트 표시 불가")


class MachiningAnalysisPanel(QWidget):
    """
    가공 해석 결과 시각화 패널

    스핀들 부하와 채터 위험도를 시간축(블록 번호) 기준 그래프로 표시합니다.

    신호:
        segment_hover(int): 마우스가 특정 블록 위에 있을 때 발생
    """

    segment_hover = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._analysis: Optional[MachiningAnalysis] = None
        self._current_index: int = 0

        # 차트 아이템 참조
        self._load_curve = None
        self._chatter_curve = None
        self._load_vline = None
        self._chatter_vline = None
        self._load_current_marker = None
        self._chatter_current_marker = None

        self._setup_ui()

    def _setup_ui(self):
        """UI 레이아웃을 구성합니다."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # ---- 제목 및 컨트롤 바 ----
        header = QHBoxLayout()
        title_label = QLabel("가공 해석 차트")
        title_label.setStyleSheet("font-weight: bold; font-size: 13px; color: #ffffff;")
        header.addWidget(title_label)
        header.addStretch()

        # 색상 모드 선택 콤보박스
        self._color_mode_combo = QComboBox()
        self._color_mode_combo.addItems(["기본 색상", "스핀들 부하", "채터 위험도"])
        self._color_mode_combo.setToolTip("3D 뷰어 공구경로 색상 모드 선택")
        self._color_mode_combo.setFixedWidth(120)
        header.addWidget(QLabel("뷰어 색상:"))
        header.addWidget(self._color_mode_combo)

        main_layout.addLayout(header)

        if not _PG_AVAILABLE:
            # pyqtgraph 없을 때 대체 텍스트
            lbl = QLabel("차트 표시를 위해 pyqtgraph를 설치하세요\n"
                         "pip install pyqtgraph")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #aaaaaa; padding: 20px;")
            main_layout.addWidget(lbl)
            return

        pg.setConfigOptions(background='#1e1e1e', foreground='#cccccc')

        # ---- 스핀들 부하 차트 ----
        load_group = QGroupBox("스핀들 부하 추정 (%)")
        load_group.setStyleSheet(
            "QGroupBox { color: #aaaaff; font-weight: bold; border: 1px solid #444; "
            "border-radius: 4px; margin-top: 6px; padding-top: 6px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; }"
        )
        load_layout = QVBoxLayout(load_group)
        load_layout.setContentsMargins(2, 2, 2, 2)

        self._load_plot = pg.PlotWidget()
        self._load_plot.setLabel('left', '부하 (%)', color='#aaaaff')
        self._load_plot.setLabel('bottom', '블록 번호')
        self._load_plot.setYRange(0, 105)
        self._load_plot.showGrid(x=True, y=True, alpha=0.25)
        self._load_plot.setMinimumHeight(130)
        self._load_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # 경고 기준선: 80% (노랑), 100% (빨강)
        self._load_plot.addLine(y=80, pen=pg.mkPen('#ffaa00', width=1, style=Qt.PenStyle.DashLine))
        self._load_plot.addLine(y=100, pen=pg.mkPen('#ff4444', width=1, style=Qt.PenStyle.DashLine))

        # 실제 부하 곡선
        self._load_curve = self._load_plot.plot(
            [], [], pen=pg.mkPen('#5588ff', width=1.5), name='스핀들 부하'
        )
        # 채워진 영역
        self._load_fill = pg.FillBetweenItem(
            self._load_plot.plot([], [], pen=None),
            self._load_curve,
            brush=pg.mkBrush(80, 120, 255, 40)
        )
        self._load_plot.addItem(self._load_fill)

        # 현재 블록 수직선
        self._load_vline = pg.InfiniteLine(
            pos=0, angle=90, pen=pg.mkPen('#ffff00', width=1.5, style=Qt.PenStyle.DashLine)
        )
        self._load_plot.addItem(self._load_vline)

        # 현재 블록 값 표시 점
        self._load_current_marker = pg.ScatterPlotItem(
            size=8, pen=pg.mkPen('#ffff00', width=1), brush=pg.mkBrush('#ffff00')
        )
        self._load_plot.addItem(self._load_current_marker)

        load_layout.addWidget(self._load_plot)
        main_layout.addWidget(load_group)

        # ---- 채터 위험도 차트 ----
        chatter_group = QGroupBox("채터/진동 위험도 추정 (%)")
        chatter_group.setStyleSheet(
            "QGroupBox { color: #ffaaaa; font-weight: bold; border: 1px solid #444; "
            "border-radius: 4px; margin-top: 6px; padding-top: 6px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; }"
        )
        chatter_layout = QVBoxLayout(chatter_group)
        chatter_layout.setContentsMargins(2, 2, 2, 2)

        self._chatter_plot = pg.PlotWidget()
        self._chatter_plot.setLabel('left', '위험도 (%)', color='#ffaaaa')
        self._chatter_plot.setLabel('bottom', '블록 번호')
        self._chatter_plot.setYRange(0, 105)
        self._chatter_plot.showGrid(x=True, y=True, alpha=0.25)
        self._chatter_plot.setMinimumHeight(130)
        self._chatter_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # 경고 기준선: 50% (노랑), 75% (빨강)
        self._chatter_plot.addLine(y=50, pen=pg.mkPen('#ffaa00', width=1, style=Qt.PenStyle.DashLine))
        self._chatter_plot.addLine(y=75, pen=pg.mkPen('#ff4444', width=1, style=Qt.PenStyle.DashLine))

        # 채터 위험도 곡선
        self._chatter_curve = self._chatter_plot.plot(
            [], [], pen=pg.mkPen('#ff6655', width=1.5), name='채터 위험도'
        )
        # 채워진 영역
        self._chatter_fill = pg.FillBetweenItem(
            self._chatter_plot.plot([], [], pen=None),
            self._chatter_curve,
            brush=pg.mkBrush(255, 100, 80, 40)
        )
        self._chatter_plot.addItem(self._chatter_fill)

        # 현재 블록 수직선
        self._chatter_vline = pg.InfiniteLine(
            pos=0, angle=90, pen=pg.mkPen('#ffff00', width=1.5, style=Qt.PenStyle.DashLine)
        )
        self._chatter_plot.addItem(self._chatter_vline)

        # 현재 블록 값 표시 점
        self._chatter_current_marker = pg.ScatterPlotItem(
            size=8, pen=pg.mkPen('#ffff00', width=1), brush=pg.mkBrush('#ffff00')
        )
        self._chatter_plot.addItem(self._chatter_current_marker)

        chatter_layout.addWidget(self._chatter_plot)
        main_layout.addWidget(chatter_group)

        # ---- 요약 수치 패널 ----
        self._summary_label = QLabel("로드 대기 중...")
        self._summary_label.setStyleSheet(
            "QLabel { font-family: monospace; font-size: 11px; color: #cccccc; "
            "background: #1a1a1a; padding: 6px; border-radius: 3px; }"
        )
        self._summary_label.setWordWrap(True)
        main_layout.addWidget(self._summary_label)

    def load_analysis(self, analysis: MachiningAnalysis):
        """
        가공 해석 결과를 로드하고 차트를 업데이트합니다.

        Args:
            analysis: MachiningAnalysis 인스턴스
        """
        self._analysis = analysis

        if not _PG_AVAILABLE or not analysis.results:
            return

        x = np.arange(len(analysis.results), dtype=float)
        load_y = analysis.get_spindle_load_array()
        chatter_y = analysis.get_chatter_risk_array()

        # 부하 차트 업데이트
        self._load_curve.setData(x, load_y)
        zeros = np.zeros_like(x)
        self._load_fill.setCurves(
            pg.PlotDataItem(x, zeros),
            pg.PlotDataItem(x, load_y)
        )

        # 채터 차트 업데이트
        self._chatter_curve.setData(x, chatter_y)
        self._chatter_fill.setCurves(
            pg.PlotDataItem(x, zeros),
            pg.PlotDataItem(x, chatter_y)
        )

        # X축 범위 설정
        self._load_plot.setXRange(0, len(x), padding=0.02)
        self._chatter_plot.setXRange(0, len(x), padding=0.02)

        # 요약 통계 업데이트
        self._update_summary()
        logger.debug(f"분석 차트 로드 완료: {len(analysis.results)}개 포인트")

    def update_current_block(self, index: int):
        """
        현재 재생 중인 블록 인덱스를 차트에 표시합니다.

        Args:
            index: 현재 세그먼트 인덱스
        """
        self._current_index = index

        if not _PG_AVAILABLE or self._analysis is None:
            return

        results = self._analysis.results
        if not results or index >= len(results):
            return

        # 수직선 위치 업데이트
        self._load_vline.setPos(index)
        self._chatter_vline.setPos(index)

        # 현재 값 마커 업데이트
        load_val = results[index].spindle_load_pct
        chatter_val = results[index].chatter_risk_pct
        self._load_current_marker.setData([index], [load_val])
        self._chatter_current_marker.setData([index], [chatter_val])

    def _update_summary(self):
        """요약 통계 레이블을 업데이트합니다."""
        if self._analysis is None:
            return

        a = self._analysis
        params = a.model_params

        summary = (
            f"【스핀들 부하】 최대: {a.max_spindle_load_pct:.1f}%  "
            f"평균: {a.avg_spindle_load_pct:.1f}%\n"
            f"【채터 위험도】 최대: {a.max_chatter_risk*100:.1f}%  "
            f"평균: {a.avg_chatter_risk*100:.1f}%\n"
            f"【고위험 구간】 {a.high_risk_segment_count}개 블록 "
            f"({a.high_risk_pct:.1f}%)  "
            f"최대 절삭력: {a.max_cutting_force:.0f}N\n"
            f"【모델 파라미터】 재료={params.get('material','?')}  "
            f"Kc1={params.get('Kc1',0):.0f}N/mm²  "
            f"정격출력={params.get('spindle_rated_power_w',0)/1000:.1f}kW"
        )
        self._summary_label.setText(summary)

    def get_color_mode(self) -> str:
        """현재 선택된 색상 모드를 반환합니다."""
        idx = self._color_mode_combo.currentIndex() if _PG_AVAILABLE else 0
        return ["default", "load", "chatter"][idx]
