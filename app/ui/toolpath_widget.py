"""
공구경로 목록 위젯(Toolpath List Widget) 모듈
공구경로의 세그먼트 목록을 테이블 형태로 표시합니다.
재생 중 현재 세그먼트를 강조하고 경고 세그먼트를 색상으로 구분합니다.
"""
from __future__ import annotations
from typing import List, Dict, Optional, Set

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QLabel
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QBrush, QFont

from app.models.toolpath import Toolpath, MotionSegment, MotionType
from app.verification.rules import VerificationWarning
from app.utils.logger import get_logger

logger = get_logger("toolpath_widget")


class ToolpathListWidget(QWidget):
    """
    공구경로 세그먼트 목록 테이블 위젯

    각 행은 하나의 이동 세그먼트를 나타냅니다.
    경고가 있는 세그먼트는 색상으로 표시됩니다:
    - 빨간색: ERROR 수준 경고
    - 주황색: WARNING 수준 경고
    - 일반: 정상 세그먼트
    - 파란 배경: 현재 재생 중인 세그먼트

    신호(Signals):
    - segment_selected(int): 세그먼트 클릭 시 해당 인덱스 전달
    """

    segment_selected = Signal(int)  # 세그먼트 선택 신호

    # 열 인덱스 상수
    COL_INDEX = 0     # 번호
    COL_TYPE = 1      # 이동 유형
    COL_FROM_X = 2    # 시작 X
    COL_FROM_Y = 3    # 시작 Y
    COL_FROM_Z = 4    # 시작 Z
    COL_TO_X = 5      # 끝 X
    COL_TO_Y = 6      # 끝 Y
    COL_TO_Z = 7      # 끝 Z
    COL_FEED = 8      # 이송 속도
    COL_LINE = 9      # NC 라인 번호
    NUM_COLS = 10

    def __init__(self, parent=None):
        super().__init__(parent)

        # 현재 하이라이트된 세그먼트 인덱스
        self._current_index: int = -1

        # 경고가 있는 세그먼트 집합 {세그먼트_id: 최대_심각도}
        self._warning_segments: Dict[int, str] = {}

        self._setup_ui()

    def _setup_ui(self):
        """UI 레이아웃을 설정합니다."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        # 요약 레이블
        self._summary_label = QLabel("공구경로 로드 전")
        self._summary_label.setStyleSheet(
            "QLabel { padding: 2px 6px; color: #aaaaaa; font-size: 11px; }"
        )
        layout.addWidget(self._summary_label)

        # 테이블 위젯
        self._table = QTableWidget(0, self.NUM_COLS)
        self._table.setHorizontalHeaderLabels([
            "#", "유형", "시작 X", "시작 Y", "시작 Z",
            "끝 X", "끝 Y", "끝 Z", "이송(mm/min)", "라인"
        ])

        # 테이블 설정
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(True)

        # 열 너비 설정
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(self.COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_INDEX, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_LINE, QHeaderView.ResizeMode.ResizeToContents)

        # 나머지 열은 균등 분할
        for col in range(self.COL_FROM_X, self.COL_LINE):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)

        # 테이블 스타일
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #1e1e1e;
                color: #cccccc;
                gridline-color: #333333;
                font-size: 11px;
                font-family: monospace;
            }
            QTableWidget::item:selected {
                background-color: #2a5080;
            }
            QHeaderView::section {
                background-color: #2a2a2a;
                color: #aaaaaa;
                padding: 3px;
                border: 1px solid #333;
            }
        """)

        # 클릭 시 세그먼트 선택 신호 발생
        self._table.cellClicked.connect(self._on_cell_clicked)

        layout.addWidget(self._table)

    def load_toolpath(self, toolpath: Toolpath,
                       warnings: Optional[List[VerificationWarning]] = None):
        """
        공구경로 데이터를 테이블에 로드합니다.

        Args:
            toolpath: 표시할 공구경로
            warnings: 검증 경고 목록 (없으면 None)
        """
        # 경고 세그먼트 집합 구성
        self._warning_segments = {}
        if warnings:
            for w in warnings:
                if w.segment_id >= 0:
                    # 더 심각한 경고가 우선
                    existing = self._warning_segments.get(w.segment_id, "INFO")
                    if (w.severity == "ERROR" or
                            (w.severity == "WARNING" and existing != "ERROR")):
                        self._warning_segments[w.segment_id] = w.severity

        # 테이블 채우기
        segments = toolpath.segments
        self._table.setRowCount(len(segments))

        for row, seg in enumerate(segments):
            self._fill_row(row, seg)

        # 요약 레이블 업데이트
        error_count = sum(1 for v in self._warning_segments.values() if v == "ERROR")
        warning_count = sum(1 for v in self._warning_segments.values() if v == "WARNING")

        summary = (f"총 {len(segments)}개 세그먼트  |  "
                   f"오류 {error_count}개  |  경고 {warning_count}개")
        self._summary_label.setText(summary)

        logger.debug(f"공구경로 목록 로드: {len(segments)}개 행")

    def _fill_row(self, row: int, seg: MotionSegment):
        """테이블의 한 행을 세그먼트 데이터로 채웁니다."""
        # 이동 유형 표시 문자열
        type_map = {
            MotionType.RAPID: "G0 급속",
            MotionType.LINEAR: "G1 직선",
            MotionType.ARC_CW: "G2 CW",
            MotionType.ARC_CCW: "G3 CCW",
            MotionType.DWELL: "G4 드웰",
        }
        type_str = type_map.get(seg.motion_type, str(seg.motion_type.value))

        # 이송 속도 표시
        if seg.motion_type == MotionType.RAPID:
            feed_str = "RAPID"
        else:
            feed_str = f"{seg.feedrate:.0f}"

        # 행 데이터 설정
        values = [
            str(seg.segment_id + 1),
            type_str,
            f"{seg.start_pos[0]:.3f}",
            f"{seg.start_pos[1]:.3f}",
            f"{seg.start_pos[2]:.3f}",
            f"{seg.end_pos[0]:.3f}",
            f"{seg.end_pos[1]:.3f}",
            f"{seg.end_pos[2]:.3f}",
            feed_str,
            str(seg.line_number),
        ]

        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, col, item)

        # 경고에 따른 행 색상 설정
        self._apply_row_color(row, seg.segment_id)

    def _apply_row_color(self, row: int, segment_id: int):
        """경고 심각도에 따라 행 배경색을 설정합니다."""
        severity = self._warning_segments.get(segment_id)

        if severity == "ERROR":
            # 오류: 어두운 빨간색 배경
            bg_color = QColor(80, 20, 20)
        elif severity == "WARNING":
            # 경고: 어두운 주황색 배경
            bg_color = QColor(70, 45, 10)
        else:
            # 정상: 기본 배경색 (교대 색상)
            bg_color = QColor(30, 30, 30) if row % 2 == 0 else QColor(25, 25, 25)

        for col in range(self.NUM_COLS):
            item = self._table.item(row, col)
            if item:
                item.setBackground(QBrush(bg_color))

    def highlight_segment(self, index: int):
        """
        현재 재생 중인 세그먼트를 강조 표시하고 스크롤합니다.

        Args:
            index: 강조할 행 인덱스
        """
        # 이전 하이라이트 해제
        if self._current_index >= 0 and self._current_index < self._table.rowCount():
            prev_row = self._current_index
            # 이전 세그먼트의 segment_id로 원래 색상 복원
            for col in range(self.NUM_COLS):
                item = self._table.item(prev_row, col)
                if item:
                    seg_id = prev_row  # 인덱스로 segment_id 추정
                    self._apply_row_color(prev_row, seg_id)

        self._current_index = index

        if index < 0 or index >= self._table.rowCount():
            return

        # 현재 세그먼트 하이라이트 (파란색 배경)
        highlight_color = QColor(20, 60, 120)
        for col in range(self.NUM_COLS):
            item = self._table.item(index, col)
            if item:
                item.setBackground(QBrush(highlight_color))

        # 현재 행이 보이도록 스크롤
        self._table.scrollToItem(
            self._table.item(index, 0),
            QAbstractItemView.ScrollHint.EnsureVisible
        )

        # 행 선택
        self._table.selectRow(index)

    def _on_cell_clicked(self, row: int, col: int):
        """테이블 셀 클릭 시 세그먼트 선택 신호 발생"""
        self.segment_selected.emit(row)

    def clear(self):
        """테이블을 초기화합니다."""
        self._table.setRowCount(0)
        self._warning_segments = {}
        self._current_index = -1
        self._summary_label.setText("공구경로 로드 전")
