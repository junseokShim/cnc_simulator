"""
시뮬레이션 제어 위젯(Simulation Controls Widget) 모듈
시뮬레이션 재생을 제어하는 버튼과 슬라이더를 제공합니다.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QSlider, QLabel, QGroupBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon

from app.utils.logger import get_logger

logger = get_logger("simulation_controls")


class SimulationControlsWidget(QWidget):
    """
    시뮬레이션 제어 위젯

    재생/일시정지, 단계 이동, 속도 조절, 진행률 슬라이더를 포함합니다.

    신호(Signals):
    - play_requested: 재생 요청
    - pause_requested: 일시정지 요청
    - step_forward: 한 단계 앞으로
    - step_backward: 한 단계 뒤로
    - jump_to(int): 특정 세그먼트로 이동
    - speed_changed(float): 재생 속도 변경
    """

    # 신호 정의
    play_requested = Signal()         # 재생 시작 요청
    pause_requested = Signal()        # 일시정지 요청
    stop_requested = Signal()         # 정지(처음으로) 요청
    step_forward = Signal()           # 한 단계 앞으로
    step_backward = Signal()          # 한 단계 뒤로
    jump_to = Signal(int)             # 특정 인덱스로 점프
    speed_changed = Signal(float)     # 재생 속도 변경 (배율)

    def __init__(self, parent=None):
        super().__init__(parent)

        # 현재 상태
        self._is_playing = False
        self._total_segments = 0
        self._current_index = 0
        self._speed_multiplier = 1.0

        self._setup_ui()

    def _setup_ui(self):
        """UI 레이아웃과 위젯을 설정합니다."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # --- 그룹 박스: 시뮬레이션 제어 ---
        group = QGroupBox("시뮬레이션 제어")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(6)

        # 현재 상태 표시 레이블
        self._status_label = QLabel("블록: 0/0  |  라인: -  |  T0")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(
            "QLabel { font-family: monospace; font-size: 11px; "
            "background: #1a1a1a; color: #00ff88; padding: 4px; "
            "border-radius: 3px; }"
        )
        group_layout.addWidget(self._status_label)

        # 위치 표시 레이블
        self._position_label = QLabel("X: 0.000   Y: 0.000   Z: 0.000")
        self._position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._position_label.setStyleSheet(
            "QLabel { font-family: monospace; font-size: 11px; "
            "background: #1a1a1a; color: #88ccff; padding: 4px; "
            "border-radius: 3px; }"
        )
        group_layout.addWidget(self._position_label)

        # 진행률 슬라이더
        slider_layout = QHBoxLayout()
        slider_layout.addWidget(QLabel("블록:"))

        self._progress_slider = QSlider(Qt.Orientation.Horizontal)
        self._progress_slider.setMinimum(0)
        self._progress_slider.setMaximum(0)
        self._progress_slider.setValue(0)
        self._progress_slider.setTracking(True)
        self._progress_slider.sliderMoved.connect(self._on_slider_moved)
        slider_layout.addWidget(self._progress_slider)

        group_layout.addLayout(slider_layout)

        # 재생 제어 버튼들
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(4)

        # 처음으로 버튼
        self._btn_stop = QPushButton("⏮")
        self._btn_stop.setToolTip("처음으로 (Stop/Reset)")
        self._btn_stop.setFixedSize(36, 36)
        self._btn_stop.clicked.connect(self._on_stop)
        btn_layout.addWidget(self._btn_stop)

        # 한 단계 뒤로 버튼
        self._btn_prev = QPushButton("⏪")
        self._btn_prev.setToolTip("한 단계 뒤로 (Step Backward)")
        self._btn_prev.setFixedSize(36, 36)
        self._btn_prev.clicked.connect(self.step_backward.emit)
        btn_layout.addWidget(self._btn_prev)

        # 재생/일시정지 버튼 (토글)
        self._btn_play = QPushButton("▶")
        self._btn_play.setToolTip("재생/일시정지 (Play/Pause)")
        self._btn_play.setFixedSize(44, 36)
        self._btn_play.clicked.connect(self._on_play_pause)
        btn_layout.addWidget(self._btn_play)

        # 한 단계 앞으로 버튼
        self._btn_next = QPushButton("⏩")
        self._btn_next.setToolTip("한 단계 앞으로 (Step Forward)")
        self._btn_next.setFixedSize(36, 36)
        self._btn_next.clicked.connect(self.step_forward.emit)
        btn_layout.addWidget(self._btn_next)

        # 끝으로 버튼
        self._btn_end = QPushButton("⏭")
        self._btn_end.setToolTip("끝으로 이동")
        self._btn_end.setFixedSize(36, 36)
        self._btn_end.clicked.connect(self._on_goto_end)
        btn_layout.addWidget(self._btn_end)

        group_layout.addLayout(btn_layout)

        # 속도 조절 슬라이더
        speed_layout = QHBoxLayout()
        speed_layout.addWidget(QLabel("속도:"))

        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setMinimum(1)   # 0.1x (1 = 0.1x)
        self._speed_slider.setMaximum(100) # 10x (100 = 10x)
        self._speed_slider.setValue(10)    # 1.0x (10 = 1.0x)
        self._speed_slider.setTickInterval(10)
        self._speed_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._speed_slider.valueChanged.connect(self._on_speed_changed)
        speed_layout.addWidget(self._speed_slider)

        self._speed_label = QLabel("1.0x")
        self._speed_label.setFixedWidth(40)
        speed_layout.addWidget(self._speed_label)

        group_layout.addLayout(speed_layout)

        main_layout.addWidget(group)
        main_layout.addStretch()

        # 버튼 스타일 적용
        self._apply_button_style()

    def _apply_button_style(self):
        """버튼 스타일을 설정합니다."""
        btn_style = """
            QPushButton {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #444;
                border-radius: 4px;
                font-size: 14px;
                padding: 2px;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #666;
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
            }
            QPushButton:disabled {
                color: #555;
            }
        """
        for btn in [self._btn_stop, self._btn_prev, self._btn_play,
                    self._btn_next, self._btn_end]:
            btn.setStyleSheet(btn_style)

    # --- 이벤트 핸들러 ---

    def _on_play_pause(self):
        """재생/일시정지 버튼 클릭 처리"""
        if self._is_playing:
            self.pause_requested.emit()
        else:
            self.play_requested.emit()

    def _on_stop(self):
        """처음으로 이동 버튼 클릭 처리"""
        self.stop_requested.emit()
        self.jump_to.emit(0)

    def _on_goto_end(self):
        """끝으로 이동 버튼 클릭 처리"""
        if self._total_segments > 0:
            self.jump_to.emit(self._total_segments - 1)

    def _on_slider_moved(self, value: int):
        """진행률 슬라이더 이동 처리"""
        self.jump_to.emit(value)

    def _on_speed_changed(self, value: int):
        """속도 슬라이더 변경 처리"""
        # 1~100 범위를 0.1x~10x로 변환
        speed = value / 10.0
        self._speed_multiplier = speed
        self._speed_label.setText(f"{speed:.1f}x")
        self.speed_changed.emit(speed)

    # --- 공개 API 메서드 ---

    def set_playing(self, playing: bool):
        """
        재생 상태를 업데이트합니다.

        Args:
            playing: True=재생 중, False=일시정지
        """
        self._is_playing = playing
        self._btn_play.setText("⏸" if playing else "▶")
        self._btn_play.setToolTip(
            "일시정지 (Pause)" if playing else "재생 (Play)"
        )

    def set_total_segments(self, total: int):
        """
        전체 세그먼트 수를 설정합니다.

        Args:
            total: 전체 세그먼트 수
        """
        self._total_segments = total
        self._progress_slider.setMaximum(max(0, total - 1))

    def update_status(self, segment_index: int, total: int,
                      line_number: int = 0, tool_number: int = 0,
                      position=None, elapsed_time: float = 0.0):
        """
        현재 상태 표시를 업데이트합니다.

        Args:
            segment_index: 현재 세그먼트 인덱스
            total: 전체 세그먼트 수
            line_number: 현재 라인 번호
            tool_number: 현재 공구 번호
            position: 현재 위치 [X, Y, Z]
            elapsed_time: 경과 시간 (초)
        """
        self._current_index = segment_index

        # 상태 레이블 업데이트
        time_str = self._format_time(elapsed_time)
        status = f"블록: {segment_index+1}/{total}  |  라인: {line_number}  |  T{tool_number}  |  {time_str}"
        self._status_label.setText(status)

        # 위치 레이블 업데이트
        if position is not None:
            pos_str = f"X: {position[0]:8.3f}   Y: {position[1]:8.3f}   Z: {position[2]:8.3f}"
            self._position_label.setText(pos_str)

        # 슬라이더 위치 업데이트 (슬라이더에 의한 이동 시 무한루프 방지)
        self._progress_slider.blockSignals(True)
        self._progress_slider.setValue(segment_index)
        self._progress_slider.blockSignals(False)

    def _format_time(self, seconds: float) -> str:
        """초를 mm:ss 형식으로 변환합니다."""
        if seconds < 0:
            return "00:00"
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"
