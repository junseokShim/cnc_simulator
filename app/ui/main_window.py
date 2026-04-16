"""
메인 윈도우(Main Window) 모듈
CNC 시뮬레이터 애플리케이션의 주 창입니다.
3D 뷰어, 시뮬레이션 제어, 공구 정보, 공구경로 목록을 통합합니다.
"""
from __future__ import annotations
import os
from typing import Optional, Dict, List

import numpy as np
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QToolBar, QStatusBar, QFileDialog,
    QMessageBox, QLabel, QApplication, QDockWidget
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QAction, QKeySequence, QIcon

from app.ui.viewer_3d import Viewer3D
from app.ui.simulation_controls import SimulationControlsWidget
from app.ui.tool_info_panel import ToolInfoPanel
from app.ui.toolpath_widget import ToolpathListWidget
from app.ui.report_dialog import ReportDialog

from app.parser.gcode_parser import GCodeParser
from app.simulation.machine_state import MachineState
from app.simulation.time_estimator import TimeEstimator
from app.verification.checker import VerificationChecker
from app.verification.rules import VerificationWarning
from app.geometry.stock_model import StockModel
from app.geometry.material_removal import MaterialRemovalSimulator
from app.models.toolpath import Toolpath, MotionType
from app.models.tool import Tool
from app.models.machine import MachineDef, create_default_machine
from app.models.project import ProjectConfig
from app.services.project_service import ProjectService
from app.services.report_service import ReportService
from app.utils.logger import get_logger

logger = get_logger("main_window")


class MainWindow(QMainWindow):
    """
    CNC 시뮬레이터 메인 윈도우

    레이아웃:
    - 메뉴 바: 파일, 뷰, 시뮬레이션, 도움말
    - 툴바: 자주 사용하는 작업의 빠른 접근
    - 중앙: 3D 뷰어 (가장 많은 공간)
    - 오른쪽 패널: 공구 정보 + 시뮬레이션 제어
    - 하단 패널: 공구경로 목록 (접을 수 있음)
    - 상태 바: 현재 파일, 경고 수
    """

    def __init__(self):
        super().__init__()

        # 애플리케이션 상태
        self._toolpath: Optional[Toolpath] = None
        self._warnings: List[VerificationWarning] = []
        self._machine: MachineDef = create_default_machine()
        self._tools: Dict[int, Tool] = {}
        self._stock_model: Optional[StockModel] = None
        self._project_config: Optional[ProjectConfig] = None

        # 시뮬레이션 상태
        self._machine_state = MachineState()
        self._is_playing = False
        self._play_speed = 1.0  # 재생 속도 배율

        # 타이머 (시뮬레이션 재생에 사용)
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._update_simulation_step)

        # 서비스 객체
        self._gcode_parser = GCodeParser()
        self._verifier = VerificationChecker()
        self._time_estimator = TimeEstimator()
        self._report_service = ReportService()
        self._project_service = ProjectService()

        # 기본 설정 로드
        self._load_default_configs()

        # UI 초기화
        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()

        # 윈도우 속성 설정
        self.setWindowTitle("CNC 시뮬레이터 - NC 코드 검증 시스템")
        self.resize(1400, 900)

        logger.info("메인 윈도우 초기화 완료")

    def _load_default_configs(self):
        """기본 설정 파일들을 로드합니다."""
        try:
            machine, tools, sim_options = self._project_service.load_default_configs("configs")
            self._machine = machine
            self._tools = tools

            # 검증 옵션 적용
            if 'verification' in sim_options:
                self._verifier.configure(sim_options['verification'])

            logger.info(f"기본 설정 로드: 머신={machine.name}, 공구={len(tools)}개")
        except Exception as e:
            logger.warning(f"기본 설정 로드 실패, 기본값 사용: {e}")

    def _setup_ui(self):
        """UI 레이아웃을 구성합니다."""
        # 중앙 위젯
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_layout = QHBoxLayout(central_widget)
        central_layout.setContentsMargins(4, 4, 4, 4)
        central_layout.setSpacing(4)

        # 수평 분할기: 3D 뷰어 | 오른쪽 패널
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- 왼쪽: 수직 분할기 (3D 뷰어 + 공구경로 목록) ---
        left_splitter = QSplitter(Qt.Orientation.Vertical)

        # 3D 뷰어
        self._viewer = Viewer3D()
        left_splitter.addWidget(self._viewer)

        # 공구경로 목록 (하단)
        self._toolpath_widget = ToolpathListWidget()
        self._toolpath_widget.setMaximumHeight(250)
        self._toolpath_widget.segment_selected.connect(self._on_segment_selected)
        left_splitter.addWidget(self._toolpath_widget)

        left_splitter.setSizes([600, 200])
        main_splitter.addWidget(left_splitter)

        # --- 오른쪽 패널: 공구 정보 + 시뮬레이션 제어 ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        # 공구 정보 패널
        self._tool_info_panel = ToolInfoPanel()
        right_layout.addWidget(self._tool_info_panel)

        # 시뮬레이션 제어 위젯
        self._sim_controls = SimulationControlsWidget()
        right_layout.addWidget(self._sim_controls)

        right_panel.setFixedWidth(280)
        main_splitter.addWidget(right_panel)

        main_splitter.setSizes([1100, 280])
        central_layout.addWidget(main_splitter)

        # 시뮬레이션 제어 신호 연결
        self._sim_controls.play_requested.connect(self._on_play)
        self._sim_controls.pause_requested.connect(self._on_pause)
        self._sim_controls.stop_requested.connect(self._on_stop)
        self._sim_controls.step_forward.connect(self._on_step_forward)
        self._sim_controls.step_backward.connect(self._on_step_backward)
        self._sim_controls.jump_to.connect(self._on_jump_to)
        self._sim_controls.speed_changed.connect(self._on_speed_changed)

    def _setup_menu(self):
        """메뉴 바를 구성합니다."""
        menubar = self.menuBar()

        # --- 파일 메뉴 ---
        file_menu = menubar.addMenu("파일(&F)")

        open_nc_action = QAction("NC 파일 열기(&O)...", self)
        open_nc_action.setShortcut(QKeySequence.StandardKey.Open)
        open_nc_action.setStatusTip("NC 파일을 열어 시뮬레이션을 시작합니다")
        open_nc_action.triggered.connect(self._on_open_nc_file)
        file_menu.addAction(open_nc_action)

        open_project_action = QAction("프로젝트 열기(&P)...", self)
        open_project_action.setStatusTip("저장된 프로젝트 파일을 엽니다")
        open_project_action.triggered.connect(self._on_open_project)
        file_menu.addAction(open_project_action)

        file_menu.addSeparator()

        save_report_action = QAction("검증 보고서 저장(&R)...", self)
        save_report_action.setStatusTip("NC 코드 검증 보고서를 저장합니다")
        save_report_action.triggered.connect(self._on_save_report)
        file_menu.addAction(save_report_action)

        file_menu.addSeparator()

        exit_action = QAction("종료(&X)", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # --- 뷰 메뉴 ---
        view_menu = menubar.addMenu("뷰(&V)")

        reset_camera_action = QAction("카메라 초기화(&C)", self)
        reset_camera_action.setShortcut("R")
        reset_camera_action.triggered.connect(self._viewer.reset_camera)
        view_menu.addAction(reset_camera_action)

        view_menu.addSeparator()

        self._show_stock_action = QAction("소재 표시(&S)", self)
        self._show_stock_action.setCheckable(True)
        self._show_stock_action.setChecked(True)
        self._show_stock_action.triggered.connect(self._on_toggle_stock)
        view_menu.addAction(self._show_stock_action)

        # --- 시뮬레이션 메뉴 ---
        sim_menu = menubar.addMenu("시뮬레이션(&S)")

        play_action = QAction("재생(&P)", self)
        play_action.setShortcut("Space")
        play_action.triggered.connect(self._on_play)
        sim_menu.addAction(play_action)

        pause_action = QAction("일시정지(&A)", self)
        pause_action.triggered.connect(self._on_pause)
        sim_menu.addAction(pause_action)

        step_fwd_action = QAction("한 단계 앞으로(&N)", self)
        step_fwd_action.setShortcut("Right")
        step_fwd_action.triggered.connect(self._on_step_forward)
        sim_menu.addAction(step_fwd_action)

        step_bwd_action = QAction("한 단계 뒤로(&B)", self)
        step_bwd_action.setShortcut("Left")
        step_bwd_action.triggered.connect(self._on_step_backward)
        sim_menu.addAction(step_bwd_action)

        # --- 도움말 메뉴 ---
        help_menu = menubar.addMenu("도움말(&H)")

        about_action = QAction("정보(&A)...", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _setup_toolbar(self):
        """툴바를 구성합니다."""
        toolbar = QToolBar("주요 도구")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # NC 파일 열기
        open_action = QAction("열기", self)
        open_action.setToolTip("NC 파일 열기")
        open_action.triggered.connect(self._on_open_nc_file)
        toolbar.addAction(open_action)

        toolbar.addSeparator()

        # 재생 제어
        self._tb_play = QAction("▶ 재생", self)
        self._tb_play.setToolTip("시뮬레이션 재생")
        self._tb_play.triggered.connect(self._on_play)
        toolbar.addAction(self._tb_play)

        self._tb_pause = QAction("⏸ 일시정지", self)
        self._tb_pause.setToolTip("시뮬레이션 일시정지")
        self._tb_pause.triggered.connect(self._on_pause)
        toolbar.addAction(self._tb_pause)

        tb_step = QAction("⏩ 단계", self)
        tb_step.setToolTip("한 단계 앞으로")
        tb_step.triggered.connect(self._on_step_forward)
        toolbar.addAction(tb_step)

        tb_stop = QAction("⏮ 정지", self)
        tb_stop.setToolTip("처음으로 이동")
        tb_stop.triggered.connect(self._on_stop)
        toolbar.addAction(tb_stop)

        toolbar.addSeparator()

        # 보고서
        tb_report = QAction("📄 보고서", self)
        tb_report.setToolTip("검증 보고서 보기")
        tb_report.triggered.connect(self._on_show_report)
        toolbar.addAction(tb_report)

    def _setup_statusbar(self):
        """상태 바를 설정합니다."""
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        self._status_file_label = QLabel("파일 없음")
        self._status_warning_label = QLabel("")

        self._statusbar.addWidget(self._status_file_label)
        self._statusbar.addPermanentWidget(self._status_warning_label)

    # --- 파일 로드 ---

    def load_nc_file(self, filepath: str):
        """
        NC 파일을 로드하고 시뮬레이션을 준비합니다.

        처리 순서:
        1. G-코드 파싱
        2. 소재 모델 초기화
        3. NC 코드 검증
        4. 모든 위젯 업데이트

        Args:
            filepath: 로드할 NC 파일 경로
        """
        if not os.path.exists(filepath):
            QMessageBox.critical(self, "파일 오류",
                                  f"파일을 찾을 수 없습니다:\n{filepath}")
            return

        logger.info(f"NC 파일 로드: {filepath}")
        self._statusbar.showMessage(f"파싱 중: {os.path.basename(filepath)}...")
        QApplication.processEvents()

        try:
            # 1. G-코드 파싱
            self._toolpath = self._gcode_parser.parse_file(filepath)

            # 2. 소재 모델 초기화
            if self._project_config:
                stock_min = self._project_config.stock_min
                stock_max = self._project_config.stock_max
                resolution = self._project_config.stock_resolution
            else:
                # 기본 소재 설정
                stock_min = np.array([-60.0, -60.0, -30.0])
                stock_max = np.array([60.0, 60.0, 0.0])
                resolution = 2.0

            self._stock_model = StockModel(stock_min, stock_max, resolution)

            # 3. NC 코드 검증
            self._statusbar.showMessage("검증 중...")
            QApplication.processEvents()

            self._warnings = self._verifier.run_all_checks(
                self._toolpath, self._stock_model, self._machine, self._tools
            )

            # 4. 시뮬레이션 상태 초기화
            self._machine_state.load_toolpath(self._toolpath)

            # 5. 예상 시간 계산
            est_time = self._time_estimator.estimate_total_time(
                self._toolpath, self._machine
            )
            self._toolpath.estimated_time = est_time

            # 6. 모든 위젯 업데이트
            self._update_all_widgets()

            # 7. 상태 바 업데이트
            filename = os.path.basename(filepath)
            error_count = sum(1 for w in self._warnings if w.severity == "ERROR")
            warning_count = sum(1 for w in self._warnings if w.severity == "WARNING")

            self._status_file_label.setText(
                f"파일: {filename} | "
                f"세그먼트: {len(self._toolpath.segments)} | "
                f"오류: {error_count} | "
                f"경고: {warning_count}"
            )

            if error_count > 0:
                self._status_warning_label.setText(f"⚠ 오류 {error_count}개")
                self._status_warning_label.setStyleSheet("color: #ff4444;")
            elif warning_count > 0:
                self._status_warning_label.setText(f"⚠ 경고 {warning_count}개")
                self._status_warning_label.setStyleSheet("color: #ffaa00;")
            else:
                self._status_warning_label.setText("✓ 검증 통과")
                self._status_warning_label.setStyleSheet("color: #44ff44;")

            self._statusbar.showMessage(
                f"로드 완료: {filename} - "
                f"{len(self._toolpath.segments)}개 세그먼트", 3000
            )
            logger.info(f"NC 파일 로드 완료: {filename}")

        except Exception as e:
            logger.error(f"NC 파일 로드 실패: {e}", exc_info=True)
            QMessageBox.critical(self, "로드 오류",
                                  f"NC 파일 로드 중 오류가 발생했습니다:\n{str(e)}")
            self._statusbar.showMessage("로드 실패", 3000)

    def load_project(self, filepath: str):
        """
        프로젝트 파일을 로드합니다.

        Args:
            filepath: 프로젝트 파일 경로 (.yaml)
        """
        try:
            self._project_config = self._project_service.load_project(filepath)
            self._machine = self._project_config.machine_config
            self._tools = self._project_config.get_tools_dict()

            if self._project_config.nc_file_path:
                self.load_nc_file(self._project_config.nc_file_path)

        except Exception as e:
            logger.error(f"프로젝트 로드 실패: {e}", exc_info=True)
            QMessageBox.critical(self, "프로젝트 오류",
                                  f"프로젝트 파일 로드 중 오류:\n{str(e)}")

    def _update_all_widgets(self):
        """모든 위젯을 현재 데이터로 업데이트합니다."""
        if self._toolpath is None:
            return

        # 3D 뷰어 업데이트
        self._viewer.set_toolpath(self._toolpath)
        if self._stock_model:
            self._viewer.set_stock(self._stock_model)

        # 공구경로 목록 업데이트
        self._toolpath_widget.load_toolpath(self._toolpath, self._warnings)

        # 시뮬레이션 제어 위젯 업데이트
        self._sim_controls.set_total_segments(len(self._toolpath.segments))
        self._sim_controls.set_playing(False)

        # 첫 번째 세그먼트로 이동
        self._update_ui_for_current_segment()

    def _update_ui_for_current_segment(self):
        """현재 세그먼트에 맞게 UI를 업데이트합니다."""
        if self._toolpath is None:
            return

        idx = self._machine_state.current_segment_index
        total = self._machine_state.total_segments
        pos = self._machine_state.current_position
        tool_num = self._machine_state.current_tool

        # 현재 세그먼트 정보 가져오기
        seg = self._machine_state.get_current_segment()
        line_num = seg.line_number if seg else 0
        motion_type = seg.motion_type if seg else None
        feedrate = seg.feedrate if seg else 0.0
        spindle_speed = seg.spindle_speed if seg else 0.0
        spindle_on = seg.spindle_on if seg else False

        # 공구 객체 조회
        current_tool = self._tools.get(tool_num)

        # 공구 정보 패널 업데이트
        self._tool_info_panel.update_tool(current_tool)
        self._tool_info_panel.update_machining_state(
            feedrate, spindle_speed, motion_type, spindle_on
        )

        # 거리 통계 계산 (현재까지)
        traveled_dist = sum(s.get_distance()
                            for s in self._toolpath.segments[:idx])
        cutting_dist = sum(s.get_distance()
                           for s in self._toolpath.segments[:idx]
                           if s.is_cutting_move)
        self._tool_info_panel.update_stats(
            self._machine_state.elapsed_time,
            traveled_dist, cutting_dist
        )

        # 시뮬레이션 제어 위젯 업데이트
        self._sim_controls.update_status(
            idx, total, line_num, tool_num, pos,
            self._machine_state.elapsed_time
        )

        # 3D 뷰어 업데이트
        self._viewer.set_current_position(pos, current_tool)
        self._viewer.highlight_segment(idx)

        # 공구경로 목록 하이라이트
        self._toolpath_widget.highlight_segment(idx)

    # --- 시뮬레이션 제어 슬롯 ---

    def _on_play(self):
        """재생 시작"""
        if self._toolpath is None:
            return

        if self._machine_state.is_at_end():
            self._machine_state.reset()

        self._is_playing = True
        self._sim_controls.set_playing(True)

        # 타이머 간격 계산 (기본 100ms, 속도 배율 적용)
        interval = max(16, int(100 / max(0.1, self._play_speed)))
        self._play_timer.start(interval)

    def _on_pause(self):
        """일시정지"""
        self._is_playing = False
        self._play_timer.stop()
        self._sim_controls.set_playing(False)

    def _on_stop(self):
        """정지 및 처음으로 이동"""
        self._on_pause()
        self._machine_state.reset()
        self._update_ui_for_current_segment()

    def _on_step_forward(self):
        """한 단계 앞으로"""
        if self._toolpath is None:
            return

        moved = self._machine_state.step_forward()
        if not moved:
            self._on_pause()
        self._update_ui_for_current_segment()

    def _on_step_backward(self):
        """한 단계 뒤로"""
        if self._toolpath is None:
            return

        self._machine_state.step_backward()
        self._update_ui_for_current_segment()

    def _on_jump_to(self, index: int):
        """특정 세그먼트로 점프"""
        if self._toolpath is None:
            return

        self._machine_state.jump_to(index)
        self._update_ui_for_current_segment()

    def _on_speed_changed(self, speed: float):
        """재생 속도 변경"""
        self._play_speed = speed

        # 타이머가 실행 중이면 간격 업데이트
        if self._play_timer.isActive():
            interval = max(16, int(100 / max(0.1, speed)))
            self._play_timer.setInterval(interval)

    def _update_simulation_step(self):
        """타이머에 의해 주기적으로 호출되는 시뮬레이션 단계 업데이트"""
        if self._toolpath is None:
            self._on_pause()
            return

        # 한 단계 진행
        moved = self._machine_state.step_forward()

        if not moved:
            # 끝에 도달
            self._on_pause()

        # UI 업데이트
        self._update_ui_for_current_segment()

    # --- 세그먼트 선택 ---

    def _on_segment_selected(self, index: int):
        """공구경로 목록에서 세그먼트 선택 시 처리"""
        self._on_jump_to(index)

    # --- 메뉴/툴바 액션 핸들러 ---

    def _on_open_nc_file(self):
        """NC 파일 열기 다이얼로그"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "NC 파일 열기",
            "", "NC 파일 (*.nc *.tap *.cnc *.gcode *.ngc);;모든 파일 (*)"
        )
        if filepath:
            self.load_nc_file(filepath)

    def _on_open_project(self):
        """프로젝트 파일 열기 다이얼로그"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "프로젝트 파일 열기",
            "", "YAML 프로젝트 (*.yaml *.yml);;모든 파일 (*)"
        )
        if filepath:
            self.load_project(filepath)

    def _on_save_report(self):
        """검증 보고서를 파일로 저장"""
        if self._toolpath is None:
            QMessageBox.information(self, "알림", "먼저 NC 파일을 로드하세요.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "보고서 저장",
            "nc_report.txt", "텍스트 파일 (*.txt)"
        )
        if filepath:
            report = self._report_service.generate_report(
                self._toolpath, self._warnings,
                self._machine, self._tools, self._project_config
            )
            self._report_service.save_report(report, filepath)
            QMessageBox.information(self, "저장 완료", f"보고서가 저장되었습니다:\n{filepath}")

    def _on_show_report(self):
        """검증 보고서 다이얼로그 표시"""
        if self._toolpath is None:
            QMessageBox.information(self, "알림", "먼저 NC 파일을 로드하세요.")
            return

        report = self._report_service.generate_report(
            self._toolpath, self._warnings,
            self._machine, self._tools, self._project_config
        )

        dialog = ReportDialog(report, self)
        dialog.exec()

    def _on_toggle_stock(self, checked: bool):
        """소재 표시 토글"""
        self._viewer.set_show_stock(checked)

    def _on_about(self):
        """프로그램 정보 다이얼로그"""
        QMessageBox.about(
            self, "CNC 시뮬레이터 정보",
            "<h2>CNC NC 코드 시뮬레이터</h2>"
            "<p>버전: 0.1.0</p>"
            "<p>CNC 가공 NC 코드를 파싱, 시뮬레이션, 검증하는 도구입니다.</p>"
            "<br>"
            "<p><b>지원 기능:</b></p>"
            "<ul>"
            "<li>G-코드 파싱 (G0, G1, G2, G3)</li>"
            "<li>3D 공구경로 시각화</li>"
            "<li>NC 코드 검증 (충돌, 범위 초과 등)</li>"
            "<li>검증 보고서 생성</li>"
            "</ul>"
        )
