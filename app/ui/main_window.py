"""
메인 윈도우(Main Window) 모듈

CNC 시뮬레이터 애플리케이션의 주 창입니다.
3D 뷰어, 가공 해석 차트, 시뮬레이션 제어, 공구 정보, 공구경로 목록을 통합합니다.

[통합 기능]
- G코드 파싱 → 가공 수치 모델 해석 → 검증 → 시각화
- 스핀들 부하 추정 차트 (블록별)
- 채터/진동 위험도 추정 차트 (블록별)
- 블록별 재생 및 공구경로 탐색
"""
from __future__ import annotations
import os
from typing import Optional, Dict, List

import numpy as np
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QToolBar, QStatusBar, QFileDialog,
    QMessageBox, QLabel, QApplication, QTabWidget
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence

from app.ui.viewer_3d import Viewer3D
from app.ui.simulation_controls import SimulationControlsWidget
from app.ui.tool_info_panel import ToolInfoPanel
from app.ui.tool_library_panel import ToolLibraryPanel
from app.ui.toolpath_widget import ToolpathListWidget
from app.ui.report_dialog import ReportDialog
from app.ui.analysis_panel import MachiningAnalysisPanel
from app.ui.stock_settings_panel import StockSettingsPanel

from app.parser.gcode_parser import GCodeParser
from app.simulation.machine_state import MachineState
from app.simulation.time_estimator import TimeEstimator
from app.simulation.machining_model import MachiningModel, create_machining_model_from_config
from app.verification.checker import VerificationChecker
from app.verification.rules import VerificationWarning
from app.geometry.stock_model import StockModel
from app.geometry.material_removal import MaterialRemovalSimulator
from app.models.toolpath import Toolpath, MotionType
from app.models.tool import Tool
from app.models.machine import MachineDef, create_default_machine
from app.models.project import (
    ProjectConfig,
    compute_stock_bounds_from_origin,
    normalize_stock_origin_mode,
)
from app.models.machining_result import MachiningAnalysis
from app.services.project_service import ProjectService
from app.services.report_service import ReportService
from app.services.tool_library_service import ToolLibraryService
from app.utils.logger import get_logger

logger = get_logger("main_window")


class MainWindow(QMainWindow):
    """
    CNC 시뮬레이터 메인 윈도우

    레이아웃:
    - 메뉴 바: 파일, 뷰, 시뮬레이션, 도움말
    - 툴바: 자주 사용하는 작업
    - 중앙 왼쪽: 3D 뷰어 + 공구경로 목록
    - 중앙 오른쪽 탭: 공구정보/시뮬레이션 제어 | 가공 해석 차트
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
        self._simulation_stock_model: Optional[StockModel] = None
        self._project_config: Optional[ProjectConfig] = None
        self._machining_analysis: Optional[MachiningAnalysis] = None
        self._sim_options: dict = {}

        # 시뮬레이션 상태
        self._machine_state = MachineState()
        self._is_playing = False
        self._play_speed = 1.0

        # 재생 프레임 카운터 (UI 스로틀링 용도)
        self._playback_frame_count: int = 0

        # 누적 이동 거리 캐시 (매 프레임 O(N) 합산 방지)
        self._cumulative_distances: Optional[np.ndarray] = None
        self._cumulative_cutting_distances: Optional[np.ndarray] = None

        # 사전 계산된 세그먼트 메트릭 (재생 중 dict 생성 방지)
        self._precomputed_metrics: Optional[list] = None

        # 성능 프로파일링 (프레임 시간, 씬 아이템 수 모니터링)
        self._perf_frame_times: list = []
        self._perf_last_log_frame: int = 0

        # 타이머 (재생 드라이브)
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._update_simulation_step)

        # 서비스 객체
        self._gcode_parser = GCodeParser()
        self._verifier = VerificationChecker()
        self._time_estimator = TimeEstimator()
        self._report_service = ReportService()
        self._project_service = ProjectService()
        self._tool_library_service = ToolLibraryService()
        self._machining_model: Optional[MachiningModel] = None
        self._material_removal = MaterialRemovalSimulator()

        # 기본 설정 로드
        self._load_default_configs()

        # UI 초기화
        self._setup_ui()
        self._setup_menu()
        self._setup_toolbar()
        self._setup_statusbar()

        self.setWindowTitle("CNC 시뮬레이터 - NC 코드 시뮬레이션 및 검증")
        self.resize(1500, 950)
        logger.info("메인 윈도우 초기화 완료")

    def _load_default_configs(self):
        """기본 설정 파일을 로드하고 가공 모델을 초기화합니다."""
        try:
            machine, tools, sim_options = self._project_service.load_default_configs("configs")
            self._machine = machine
            self._tools = tools
            self._sim_options = sim_options

            # 검증 옵션 적용
            if 'verification' in sim_options:
                self._verifier.configure(sim_options['verification'])

            # 가공 수치 모델 초기화
            machining_cfg = sim_options.get('machining', {})
            self._machining_model = create_machining_model_from_config(machining_cfg)

            logger.info(f"기본 설정 로드: 머신={machine.name}, 공구={len(tools)}개")
        except Exception as e:
            logger.warning(f"기본 설정 로드 실패, 기본값 사용: {e}")
            self._machining_model = MachiningModel()

    def _precompute_toolpath_distances(self):
        """
        공구경로의 누적 이동 거리를 미리 계산합니다.

        재생 중 매 프레임 O(N) 합산을 O(1) 조회로 대체하여 성능을 개선합니다.
        """
        if self._toolpath is None:
            self._cumulative_distances = None
            self._cumulative_cutting_distances = None
            return

        segs = self._toolpath.segments
        n = len(segs)
        dist = np.zeros(n + 1, dtype=float)
        cut_dist = np.zeros(n + 1, dtype=float)
        for i, seg in enumerate(segs):
            d = seg.get_distance()
            dist[i + 1] = dist[i] + d
            cut_dist[i + 1] = cut_dist[i] + (d if seg.is_cutting_move else 0.0)
        self._cumulative_distances = dist
        self._cumulative_cutting_distances = cut_dist

    def _precompute_segment_metrics(self):
        """
        세그먼트별 부하/채터 메트릭을 리스트로 미리 캐싱합니다.

        재생 중 매 프레임 dict 객체 생성을 방지합니다.
        """
        if self._machining_analysis is None:
            self._precomputed_metrics = None
            return
        self._precomputed_metrics = [
            {
                "spindle_load_pct": r.spindle_load_pct,
                "chatter_risk_score": r.chatter_risk_score,
            }
            for r in self._machining_analysis.results
        ]

    def _setup_ui(self):
        """UI 레이아웃을 구성합니다."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        central_layout = QHBoxLayout(central_widget)
        central_layout.setContentsMargins(4, 4, 4, 4)
        central_layout.setSpacing(4)

        # 주 수평 분할기: 왼쪽(뷰어+목록) | 오른쪽(정보+차트)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---- 왼쪽: 수직 분할기 (3D 뷰어 + 공구경로 목록) ----
        left_splitter = QSplitter(Qt.Orientation.Vertical)

        self._viewer = Viewer3D()
        left_splitter.addWidget(self._viewer)

        self._toolpath_widget = ToolpathListWidget()
        self._toolpath_widget.setMaximumHeight(220)
        self._toolpath_widget.segment_selected.connect(self._on_segment_selected)
        left_splitter.addWidget(self._toolpath_widget)

        left_splitter.setSizes([650, 220])
        main_splitter.addWidget(left_splitter)

        # ---- 오른쪽: 탭 위젯 (공구/제어 탭 | 가공 해석 탭) ----
        right_tab = QTabWidget()
        right_tab.setFixedWidth(320)
        right_tab.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #444; background: #1a1a1a; } "
            "QTabBar::tab { background: #2a2a2a; color: #aaa; padding: 5px 10px; } "
            "QTabBar::tab:selected { background: #3a3a3a; color: #fff; } "
        )

        # 탭 1: 공구 정보 + 시뮬레이션 제어
        ctrl_tab_widget = QWidget()
        ctrl_layout = QVBoxLayout(ctrl_tab_widget)
        ctrl_layout.setContentsMargins(2, 2, 2, 2)
        ctrl_layout.setSpacing(4)

        self._tool_info_panel = ToolInfoPanel()
        ctrl_layout.addWidget(self._tool_info_panel)

        self._stock_settings_panel = StockSettingsPanel()
        ctrl_layout.addWidget(self._stock_settings_panel)

        self._sim_controls = SimulationControlsWidget()
        ctrl_layout.addWidget(self._sim_controls)
        ctrl_layout.addStretch()

        right_tab.addTab(ctrl_tab_widget, "공구/제어")

        # 탭 2: 가공 해석 차트 (스핀들 부하 + 채터 위험도)
        self._analysis_panel = MachiningAnalysisPanel()
        right_tab.addTab(self._analysis_panel, "가공 해석")

        # 탭 3: 공구 라이브러리 편집
        self._tool_library_panel = ToolLibraryPanel()
        right_tab.addTab(self._tool_library_panel, "공구 라이브러리")

        main_splitter.addWidget(right_tab)
        main_splitter.setSizes([1180, 320])
        central_layout.addWidget(main_splitter)

        # 시뮬레이션 제어 신호 연결
        self._sim_controls.play_requested.connect(self._on_play)
        self._sim_controls.pause_requested.connect(self._on_pause)
        self._sim_controls.stop_requested.connect(self._on_stop)
        self._sim_controls.step_forward.connect(self._on_step_forward)
        self._sim_controls.step_backward.connect(self._on_step_backward)
        self._sim_controls.jump_to.connect(self._on_jump_to)
        self._sim_controls.speed_changed.connect(self._on_speed_changed)

        # 분석 패널 색상 모드 변경 시 뷰어 업데이트
        self._analysis_panel._color_mode_combo.currentIndexChanged.connect(
            self._on_color_mode_changed
        )
        self._stock_settings_panel.apply_requested.connect(self._on_stock_settings_applied)
        self._tool_library_panel.apply_requested.connect(self._on_tool_library_applied)
        self._tool_library_panel.save_requested.connect(self._on_tool_library_saved)
        self._sync_stock_settings_panel()
        self._sync_tool_library_panel()

    def _setup_menu(self):
        """메뉴 바를 구성합니다."""
        menubar = self.menuBar()

        # 파일 메뉴
        file_menu = menubar.addMenu("파일(&F)")

        open_nc_action = QAction("NC 파일 열기(&O)...", self)
        open_nc_action.setShortcut(QKeySequence.StandardKey.Open)
        open_nc_action.triggered.connect(self._on_open_nc_file)
        file_menu.addAction(open_nc_action)

        open_project_action = QAction("프로젝트 열기(&P)...", self)
        open_project_action.triggered.connect(self._on_open_project)
        file_menu.addAction(open_project_action)

        file_menu.addSeparator()

        save_report_action = QAction("검증 보고서 저장(&R)...", self)
        save_report_action.triggered.connect(self._on_save_report)
        file_menu.addAction(save_report_action)

        save_csv_action = QAction("해석 결과 CSV 저장(&C)...", self)
        save_csv_action.triggered.connect(self._on_save_analysis_csv)
        file_menu.addAction(save_csv_action)

        file_menu.addSeparator()

        exit_action = QAction("종료(&X)", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 뷰 메뉴
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

        # 시뮬레이션 메뉴
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

        # 도움말 메뉴
        help_menu = menubar.addMenu("도움말(&H)")
        about_action = QAction("정보(&A)...", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _setup_toolbar(self):
        """툴바를 구성합니다."""
        toolbar = QToolBar("주요 도구")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        open_action = QAction("열기", self)
        open_action.setToolTip("NC 파일 열기 (Ctrl+O)")
        open_action.triggered.connect(self._on_open_nc_file)
        toolbar.addAction(open_action)

        toolbar.addSeparator()

        self._tb_play = QAction("▶ 재생", self)
        self._tb_play.setToolTip("시뮬레이션 재생 (Space)")
        self._tb_play.triggered.connect(self._on_play)
        toolbar.addAction(self._tb_play)

        self._tb_pause = QAction("⏸ 일시정지", self)
        self._tb_pause.triggered.connect(self._on_pause)
        toolbar.addAction(self._tb_pause)

        tb_step = QAction("⏩ 단계", self)
        tb_step.setToolTip("한 단계 앞으로 (→)")
        tb_step.triggered.connect(self._on_step_forward)
        toolbar.addAction(tb_step)

        tb_stop = QAction("⏮ 정지", self)
        tb_stop.triggered.connect(self._on_stop)
        toolbar.addAction(tb_stop)

        toolbar.addSeparator()

        tb_report = QAction("보고서", self)
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

    # ====================================================
    # 파일 로드 (핵심 파이프라인)
    # ====================================================

    def _legacy_load_nc_file_unused(self, filepath: str):
        """
        NC 파일을 로드하고 전체 시뮬레이션 파이프라인을 실행합니다.

        파이프라인:
        1. G코드 파싱 → Toolpath
        2. 소재 모델 초기화
        3. 가공 수치 모델 해석 (스핀들 부하, 채터 위험도)
        4. NC 코드 검증 (경고/오류)
        5. 시뮬레이션 상태 초기화
        6. 전체 UI 업데이트
        """
        if not os.path.exists(filepath):
            QMessageBox.critical(self, "파일 오류", f"파일을 찾을 수 없습니다:\n{filepath}")
            return

        logger.info(f"NC 파일 로드: {filepath}")
        self._statusbar.showMessage(f"파싱 중: {os.path.basename(filepath)}...")
        QApplication.processEvents()

        try:
            # 1. G코드 파싱
            self._toolpath = self._gcode_parser.parse_file(filepath)
            self._statusbar.showMessage(
                f"파싱 완료 ({len(self._toolpath.segments)}개 세그먼트), 수치 모델 계산 중..."
            )
            QApplication.processEvents()

            # 2. 소재 모델 초기화
            stock_min, stock_max, resolution, _ = self._get_active_stock_config()
            self._stock_model = StockModel(stock_min, stock_max, resolution)
            self._sync_stock_settings_panel()

            # 3. 가공 수치 모델 해석 (스핀들 부하 + 채터 위험도)
            if self._machining_model is None:
                self._machining_model = MachiningModel()
            self._machining_analysis = self._machining_model.analyze_toolpath(
                self._toolpath, self._tools, self._stock_model
            )

            # 4. NC 코드 검증
            self._statusbar.showMessage("검증 중...")
            QApplication.processEvents()
            self._warnings = self._verifier.run_all_checks(
                self._toolpath, self._stock_model, self._machine, self._tools
            )

            # 5. 시뮬레이션 상태 초기화
            self._machine_state.load_toolpath(self._toolpath)
            self._reset_simulation_stock()
            est_time = self._time_estimator.estimate_total_time(self._toolpath, self._machine)
            self._toolpath.estimated_time = est_time

            # 6. 전체 UI 업데이트
            self._update_all_widgets()

            # 7. 상태 바 업데이트
            filename = os.path.basename(filepath)
            self._update_status_summary()

            analysis = self._machining_analysis
            self._status_file_label.setText(
                f"파일: {filename}  |  "
                f"세그먼트: {len(self._toolpath.segments)}  |  "
                f"최대부하: {analysis.max_spindle_load_pct:.1f}%  |  "
                f"최대채터위험: {analysis.max_chatter_risk*100:.1f}%  |  "
                f"오류/경고: {error_count}/{warning_count}"
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

            self._statusbar.showMessage(f"로드 완료: {filename}", 3000)
            logger.info(f"NC 파일 로드 완료: {filename}")

        except Exception as e:
            logger.error(f"NC 파일 로드 실패: {e}", exc_info=True)
            QMessageBox.critical(self, "로드 오류",
                                 f"NC 파일 로드 중 오류가 발생했습니다:\n{str(e)}")
            self._statusbar.showMessage("로드 실패", 3000)

    def _legacy_load_project_unused(self, filepath: str):
        """프로젝트 파일을 로드합니다."""
        try:
            self._project_config = self._project_service.load_project(filepath)
            self._machine = self._project_config.machine_config
            self._tools = self._project_config.get_tools_dict()
            if self._project_config.nc_file_path:
                self.load_nc_file(self._project_config.nc_file_path)
        except Exception as e:
            logger.error(f"프로젝트 로드 실패: {e}", exc_info=True)
            QMessageBox.critical(self, "프로젝트 오류", f"프로젝트 파일 로드 중 오류:\n{str(e)}")

    def load_nc_file(self, filepath: str):
        """
        NC 파일을 로드하고 전체 시뮬레이션 파이프라인을 다시 계산합니다.

        처리 순서:
        1. G코드 파싱
        2. 소재 설정 기준으로 스톡 모델 생성
        3. AE/AP-aware 가공 해석 수행
        4. 검증 규칙 실행
        5. 재생 상태 및 UI 갱신
        """
        if not os.path.exists(filepath):
            QMessageBox.critical(self, "파일 오류", f"파일을 찾을 수 없습니다:\n{filepath}")
            return

        logger.info("NC 파일 로드: %s", filepath)
        self._statusbar.showMessage(f"파싱 중: {os.path.basename(filepath)}...")
        QApplication.processEvents()

        try:
            self._toolpath = self._gcode_parser.parse_file(filepath)
            self._statusbar.showMessage(
                f"파싱 완료 ({len(self._toolpath.segments)}개 세그먼트), 가공 해석 계산 중..."
            )
            QApplication.processEvents()

            stock_min, stock_max, resolution, _ = self._get_active_stock_config()
            self._stock_model = StockModel(stock_min, stock_max, resolution)
            self._sync_stock_settings_panel()

            if self._machining_model is None:
                self._machining_model = MachiningModel()
            self._machining_analysis = self._machining_model.analyze_toolpath(
                self._toolpath,
                self._tools,
                self._stock_model,
            )

            self._statusbar.showMessage("검증 중...")
            QApplication.processEvents()
            self._warnings = self._verifier.run_all_checks(
                self._toolpath,
                self._stock_model,
                self._machine,
                self._tools,
            )

            self._machine_state.load_toolpath(self._toolpath)
            self._reset_simulation_stock()
            estimated_time = self._time_estimator.estimate_total_time(self._toolpath, self._machine)
            self._toolpath.estimated_time = estimated_time

            # 누적 거리 및 세그먼트 메트릭 사전 계산 (재생 중 O(N)/dict 생성 제거)
            self._precompute_toolpath_distances()
            self._precompute_segment_metrics()

            self._update_all_widgets()
            self._update_status_summary()

            filename = os.path.basename(filepath)
            self._statusbar.showMessage(f"로드 완료: {filename}", 3000)
            logger.info("NC 파일 로드 완료: %s", filename)

        except Exception as exc:
            logger.error("NC 파일 로드 실패: %s", exc, exc_info=True)
            QMessageBox.critical(
                self,
                "로드 오류",
                f"NC 파일 로드 중 오류가 발생했습니다:\n{str(exc)}",
            )
            self._statusbar.showMessage("로드 실패", 3000)

    def load_project(self, filepath: str):
        """프로젝트 파일을 로드합니다."""
        try:
            self._project_config = self._project_service.load_project(filepath)
            self._machine = self._project_config.machine_config
            self._tools = self._project_config.get_tools_dict()
            self._sync_stock_settings_panel()
            self._sync_tool_library_panel()

            if self._project_config.nc_file_path:
                self.load_nc_file(self._project_config.nc_file_path)
                return

            stock_min, stock_max, resolution, _ = self._get_active_stock_config()
            self._stock_model = StockModel(stock_min, stock_max, resolution)
            self._reset_simulation_stock()

            stock_size = stock_max - stock_min
            self._status_file_label.setText(
                f"프로젝트: {self._project_config.project_name}  |  "
                f"소재 크기: {stock_size[0]:.1f} x {stock_size[1]:.1f} x {stock_size[2]:.1f} mm"
            )
            self._status_warning_label.setText("")
            self._statusbar.showMessage("프로젝트 로드 완료", 3000)
        except Exception as exc:
            logger.error("프로젝트 로드 실패: %s", exc, exc_info=True)
            QMessageBox.critical(
                self,
                "프로젝트 오류",
                f"프로젝트 파일 로드 중 오류:\n{str(exc)}",
            )

    def _get_active_stock_config(self) -> tuple[np.ndarray, np.ndarray, float, str]:
        """현재 프로젝트 또는 기본 설정에서 활성 소재 범위를 가져옵니다."""
        if self._project_config is not None:
            return (
                np.array(self._project_config.stock_min, dtype=float),
                np.array(self._project_config.stock_max, dtype=float),
                float(self._project_config.stock_resolution),
                self._project_config.stock_origin_mode,
            )

        stock_cfg = self._sim_options.get("stock", {})
        resolution = float(stock_cfg.get("resolution", 2.0))
        origin_mode = normalize_stock_origin_mode(stock_cfg.get("origin_mode", "top_center"))

        if "origin" in stock_cfg and "size" in stock_cfg:
            stock_min, stock_max = compute_stock_bounds_from_origin(
                stock_cfg.get("origin"),
                stock_cfg.get("size"),
                origin_mode,
            )
        else:
            stock_min = np.array(stock_cfg.get("min", [-60.0, -60.0, -30.0]), dtype=float)
            stock_max = np.array(stock_cfg.get("max", [60.0, 60.0, 0.0]), dtype=float)

        return stock_min, stock_max, resolution, origin_mode

    def _sync_stock_settings_panel(self):
        """현재 소재 설정을 우측 패널에 반영합니다."""
        if not hasattr(self, "_stock_settings_panel"):
            return

        stock_min, stock_max, resolution, origin_mode = self._get_active_stock_config()
        self._stock_settings_panel.set_stock_config(
            stock_min,
            stock_max,
            resolution,
            origin_mode=origin_mode,
        )

    def _default_tool_library_path(self) -> str:
        """프로젝트가 없을 때 사용할 기본 공구 라이브러리 경로를 반환합니다."""

        return os.path.normpath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "..",
                "configs",
                "default_tools.yaml",
            )
        )

    def _tool_library_source_text(self) -> str:
        """공구 라이브러리 패널에 표시할 현재 저장 대상을 구성합니다."""

        if self._project_config is not None and self._project_config.project_file_path:
            lines = [f"저장 대상: 프로젝트 파일 {self._project_config.project_file_path}"]
            if self._project_config.tool_library_file:
                lines.append(f"참조 라이브러리: {self._project_config.tool_library_file}")
            lines.append("프로젝트 저장 시 tools 항목에 현재 공구 정의가 반영됩니다.")
            return "\n".join(lines)

        return (
            f"저장 대상: 기본 공구 라이브러리 {self._default_tool_library_path()}\n"
            "프로젝트를 열지 않은 상태에서는 이 파일에 저장됩니다."
        )

    def _sync_tool_library_panel(self):
        """현재 공구 정의를 공구 라이브러리 편집 패널에 반영합니다."""

        if not hasattr(self, "_tool_library_panel"):
            return

        ordered_tools = [self._tools[key] for key in sorted(self._tools)]
        self._tool_library_panel.set_tools(
            ordered_tools,
            source_label=self._tool_library_source_text(),
        )

    def _set_active_tools(self, tools: Dict[int, Tool]):
        """현재 시뮬레이터와 프로젝트 상태에 공구 정의를 반영합니다."""

        self._tools = {tool_number: tools[tool_number] for tool_number in sorted(tools)}
        if self._project_config is not None:
            self._project_config.tools = [self._tools[key] for key in sorted(self._tools)]

    def _rebuild_tool_dependent_state(self, reset_playback: bool = True):
        """공구 변경 후 해석/검증/UI 상태를 다시 계산합니다."""

        if self._toolpath is not None and self._stock_model is None:
            stock_min, stock_max, resolution, _ = self._get_active_stock_config()
            self._stock_model = StockModel(stock_min, stock_max, resolution)
            self._reset_simulation_stock()

        self._sync_tool_library_panel()

        if self._toolpath is not None and self._stock_model is not None:
            self._recompute_stock_dependent_state(reset_playback=reset_playback)
            return

        tool_count = len(self._tools)
        self._status_file_label.setText(
            f"공구 라이브러리: {tool_count}개 | 입력값은 직경(mm), 내부 반경은 직경/2"
        )
        self._status_warning_label.setText("")
        self._statusbar.showMessage("공구 라이브러리 적용 완료", 3000)

    def _persist_active_tools(self) -> str:
        """현재 공구 정의를 프로젝트 또는 기본 라이브러리 파일에 저장합니다."""

        if self._project_config is not None and self._project_config.project_file_path:
            target = self._project_config.project_file_path
            self._project_service.save_project(self._project_config, target)
            return target

        target = self._default_tool_library_path()
        self._tool_library_service.save_file(
            target,
            self._tools,
            source_note="앱에서 저장한 기본 공구 라이브러리",
        )
        return target

    def _apply_stock_settings_to_project(self, settings: dict):
        """패널 입력값을 프로젝트 또는 기본 시뮬레이션 설정에 반영합니다."""
        if self._project_config is not None:
            self._project_config.set_stock_from_origin(
                settings["origin"],
                settings["size"],
                settings["origin_mode"],
            )
            self._project_config.stock_resolution = float(settings["resolution"])
            return

        stock_cfg = self._sim_options.setdefault("stock", {})
        stock_cfg["min"] = settings["min"].tolist()
        stock_cfg["max"] = settings["max"].tolist()
        stock_cfg["origin"] = settings["origin"].tolist()
        stock_cfg["size"] = settings["size"].tolist()
        stock_cfg["origin_mode"] = settings["origin_mode"]
        stock_cfg["resolution"] = float(settings["resolution"])

    def _recompute_stock_dependent_state(self, reset_playback: bool = False):
        """소재 변경 시 스톡 기반 해석과 검증을 다시 수행합니다."""
        if self._stock_model is None:
            return

        if self._toolpath is None:
            if reset_playback:
                self._machine_state.reset()
            self._reset_simulation_stock()
            return

        self._statusbar.showMessage("소재 기준으로 가공 해석 재계산 중...")
        QApplication.processEvents()

        if self._machining_model is None:
            self._machining_model = MachiningModel()

        self._machining_analysis = self._machining_model.analyze_toolpath(
            self._toolpath,
            self._tools,
            self._stock_model,
        )
        self._warnings = self._verifier.run_all_checks(
            self._toolpath,
            self._stock_model,
            self._machine,
            self._tools,
        )

        if reset_playback:
            # 소재 기준이 바뀌면 기존 재생 흔적을 다시 전부 복원하는 것보다
            # 재생 상태를 처음으로 돌리는 편이 자연스럽고 적용 렉도 크게 줄어듭니다.
            self._machine_state.reset()
            self._reset_simulation_stock(refresh_surface=True)
        else:
            completed = min(self._machine_state.completed_segments, len(self._toolpath.segments))
            self._rebuild_simulation_stock(completed)
        self._update_all_widgets()
        self._update_status_summary()
        self._statusbar.showMessage("소재 설정 반영 완료", 3000)

    def _update_status_summary(self):
        """상태바 요약 정보를 갱신합니다."""
        if self._toolpath is None or self._machining_analysis is None:
            return

        error_count = sum(1 for warning in self._warnings if warning.severity == "ERROR")
        warning_count = sum(1 for warning in self._warnings if warning.severity == "WARNING")
        analysis = self._machining_analysis
        filename = os.path.basename(self._toolpath.source_file) if self._toolpath.source_file else "메모리"

        self._status_file_label.setText(
            f"파일: {filename}  |  "
            f"세그먼트: {len(self._toolpath.segments)}  |  "
            f"최대부하 {analysis.max_spindle_load_pct:.1f}%  |  "
            f"최대채터 {analysis.max_chatter_risk * 100:.1f}%  |  "
            f"최대합성진동 {analysis.max_resultant_vibration_um:.2f} um  |  "
            f"오류/경고: {error_count}/{warning_count}"
        )

        if error_count > 0:
            self._status_warning_label.setText(f"오류 {error_count}개")
            self._status_warning_label.setStyleSheet("color: #ff4444;")
        elif warning_count > 0:
            self._status_warning_label.setText(f"경고 {warning_count}개")
            self._status_warning_label.setStyleSheet("color: #ffaa00;")
        else:
            self._status_warning_label.setText("검증 통과")
            self._status_warning_label.setStyleSheet("color: #44ff44;")

    def _on_stock_settings_applied(self, settings: dict):
        """소재 패널의 적용 버튼을 누르면 스톡/해석/UI를 모두 갱신합니다."""
        try:
            self._on_pause()
            self._apply_stock_settings_to_project(settings)

            self._stock_model = StockModel(
                np.array(settings["min"], dtype=float),
                np.array(settings["max"], dtype=float),
                float(settings["resolution"]),
            )
            self._reset_simulation_stock()
            self._sync_stock_settings_panel()
            self._recompute_stock_dependent_state(reset_playback=True)

            if self._toolpath is None:
                size = settings["size"]
                self._status_file_label.setText(
                    f"소재 크기: {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm  |  "
                    f"원점 기준: {settings['origin_mode']}"
                )
                self._statusbar.showMessage("소재 설정 적용 완료", 3000)
        except Exception as exc:
            logger.error("소재 설정 적용 실패: %s", exc, exc_info=True)
            QMessageBox.critical(
                self,
                "소재 설정 오류",
                f"소재 설정 적용 중 오류가 발생했습니다:\n{str(exc)}",
            )

    def _on_tool_library_applied(self, tools: Dict[int, Tool]):
        """공구 라이브러리 편집 내용을 현재 시뮬레이션에 반영합니다."""

        try:
            self._on_pause()
            self._set_active_tools(tools)
            self._rebuild_tool_dependent_state(reset_playback=True)
        except Exception as exc:
            logger.error("공구 라이브러리 적용 실패: %s", exc, exc_info=True)
            QMessageBox.critical(
                self,
                "공구 라이브러리 오류",
                f"공구 라이브러리 적용 중 오류가 발생했습니다:\n{str(exc)}",
            )

    def _on_tool_library_saved(self, tools: Dict[int, Tool]):
        """공구 라이브러리 편집 내용을 저장하고 시뮬레이션 상태에 반영합니다."""

        try:
            self._on_pause()
            self._set_active_tools(tools)
            self._rebuild_tool_dependent_state(reset_playback=True)
            saved_path = self._persist_active_tools()
            self._sync_tool_library_panel()
            self._statusbar.showMessage(f"공구 라이브러리 저장 완료: {saved_path}", 4000)
        except Exception as exc:
            logger.error("공구 라이브러리 저장 실패: %s", exc, exc_info=True)
            QMessageBox.critical(
                self,
                "공구 라이브러리 저장 오류",
                f"공구 라이브러리 저장 중 오류가 발생했습니다:\n{str(exc)}",
            )

    def _update_all_widgets(self):
        """모든 위젯을 현재 데이터로 업데이트합니다."""
        if self._toolpath is None:
            return

        # 3D 뷰어 업데이트
        self._viewer.set_toolpath(self._toolpath)
        if self._simulation_stock_model:
            self._viewer.set_stock(self._simulation_stock_model)

        # 가공 해석 차트 업데이트
        if self._machining_analysis:
            self._analysis_panel.load_analysis(self._machining_analysis)

        # 공구경로 목록 업데이트
        self._toolpath_widget.load_toolpath(self._toolpath, self._warnings)

        # 시뮬레이션 제어 위젯 업데이트
        self._sim_controls.set_total_segments(len(self._toolpath.segments))
        self._sim_controls.set_playing(False)

        # 첫 번째 세그먼트로 초기화
        self._update_ui_for_current_segment()

    def _update_ui_for_current_segment(self, playback_throttle: bool = False):
        """현재 세그먼트에 맞게 UI를 업데이트합니다.

        Args:
            playback_throttle: True이면 재생 중 스로틀링을 적용합니다.
                               매 4프레임마다 패널/차트를 갱신합니다.
        """
        if self._toolpath is None:
            return

        idx = self._machine_state.current_segment_index
        total = self._machine_state.total_segments
        completed = self._machine_state.completed_segments
        pos = self._machine_state.current_position
        tool_num = self._machine_state.current_tool

        seg = self._machine_state.get_current_segment()
        line_num = seg.line_number if seg else 0
        motion_type = seg.motion_type if seg else None
        feedrate = seg.feedrate if seg else 0.0
        spindle_speed = seg.spindle_speed if seg else 0.0
        spindle_on = seg.spindle_on if seg else False

        current_tool = self._tools.get(tool_num)

        # 재생 중 스로틀링: 매 4프레임마다만 패널 업데이트
        # (수동 조작 시에는 항상 갱신)
        update_panels = (not playback_throttle) or (self._playback_frame_count % 4 == 0)

        # 현재까지 이동 거리 계산 (사전 계산 배열로 O(1) 조회)
        if self._cumulative_distances is not None and completed <= len(self._cumulative_distances) - 1:
            traveled_dist = float(self._cumulative_distances[completed])
            cutting_dist = float(self._cumulative_cutting_distances[completed])
        else:
            traveled_dist = sum(s.get_distance() for s in self._toolpath.segments[:completed])
            cutting_dist = sum(
                s.get_distance() for s in self._toolpath.segments[:completed]
                if s.is_cutting_move
            )

        # 현재 블록의 가공 해석 결과 가져오기
        current_result = None
        result_idx = idx
        if completed > 0:
            result_idx = min(completed - 1, len(self._machining_analysis.results) - 1) if self._machining_analysis else idx
        if self._machining_analysis and result_idx < len(self._machining_analysis.results):
            mr = self._machining_analysis.results[result_idx]
            current_result = mr
            if mr.is_cutting:
                spindle_speed = mr.spindle_speed
                feedrate = mr.feedrate

        if update_panels:
            # 공구 정보 패널 업데이트 (스로틀링 적용)
            self._tool_info_panel.update_tool(current_tool, requested_tool_number=tool_num)
            self._tool_info_panel.update_machining_state(
                feedrate, spindle_speed, motion_type, spindle_on
            )
            self._tool_info_panel.update_stats(
                self._machine_state.elapsed_time, traveled_dist, cutting_dist
            )
            self._tool_info_panel.update_analysis(current_result)

            # 가공 해석 패널 현재 블록 표시 (스로틀링 적용)
            self._analysis_panel.update_current_block(result_idx)

            # 공구경로 목록 하이라이트 (스로틀링 적용)
            self._toolpath_widget.highlight_segment(idx)

        # 항상 갱신: 3D 뷰어 공구 위치 + 시뮬레이션 제어 상태
        self._sim_controls.update_status(idx, total, line_num, tool_num, pos,
                                         self._machine_state.elapsed_time)
        self._viewer.set_current_position(pos, current_tool)
        self._viewer.highlight_segment(idx)

    # ====================================================
    # 시뮬레이션 제어 슬롯
    # ====================================================

    def _on_play(self):
        """재생 시작"""
        if self._toolpath is None:
            return
        if self._machine_state.is_at_end():
            self._machine_state.reset()
            self._reset_simulation_stock()
        self._is_playing = True
        self._playback_frame_count = 0
        self._sim_controls.set_playing(True)
        interval = max(16, int(100 / max(0.1, self._play_speed)))
        self._play_timer.start(interval)

    def _on_pause(self):
        """일시정지"""
        self._is_playing = False
        self._play_timer.stop()
        self._sim_controls.set_playing(False)

    def _on_stop(self):
        """정지 및 처음으로"""
        self._on_pause()
        self._machine_state.reset()
        self._reset_simulation_stock(refresh_surface=False)
        self._update_ui_for_current_segment()

    def _on_step_forward(self):
        """한 단계 앞으로"""
        if self._toolpath is None:
            return
        prev_completed = self._machine_state.completed_segments
        moved = self._machine_state.step_forward()
        if moved:
            self._apply_simulation_segment(prev_completed)
        if not moved:
            self._on_pause()
        self._update_ui_for_current_segment()

    def _on_step_backward(self):
        """한 단계 뒤로"""
        if self._toolpath is None:
            return
        self._machine_state.step_backward()
        self._rebuild_simulation_stock(self._machine_state.completed_segments)
        self._update_ui_for_current_segment()

    def _on_jump_to(self, index: int):
        """특정 세그먼트로 점프"""
        if self._toolpath is None:
            return
        self._machine_state.jump_to(index)
        self._rebuild_simulation_stock(self._machine_state.completed_segments)
        self._update_ui_for_current_segment()

    def _on_speed_changed(self, speed: float):
        """재생 속도 변경"""
        self._play_speed = speed
        if self._play_timer.isActive():
            interval = max(16, int(100 / max(0.1, speed)))
            self._play_timer.setInterval(interval)

    def _update_simulation_step(self):
        """타이머 콜백: 재생 중 한 단계 진행"""
        if self._toolpath is None:
            self._on_pause()
            return

        import time as _time
        _t0 = _time.perf_counter()

        self._playback_frame_count += 1
        prev_completed = self._machine_state.completed_segments
        moved = self._machine_state.step_forward()
        if moved:
            self._apply_simulation_segment(prev_completed)
        if not moved:
            self._on_pause()
            self._update_ui_for_current_segment(playback_throttle=False)
            return
        self._update_ui_for_current_segment(playback_throttle=True)

        # 프레임 시간 수집 및 주기적 로깅 (성능 모니터링)
        _dt_ms = (_time.perf_counter() - _t0) * 1000.0
        self._perf_frame_times.append(_dt_ms)
        if len(self._perf_frame_times) >= 30:
            avg = sum(self._perf_frame_times) / len(self._perf_frame_times)
            peak = max(self._perf_frame_times)
            item_count = self._get_scene_item_count()
            logger.debug(
                "[성능] 프레임 시간 avg=%.1f ms, peak=%.1f ms | GL 씬 아이템=%d개 | "
                "프레임=%d",
                avg, peak, item_count, self._playback_frame_count,
            )
            self._perf_frame_times.clear()

    def _get_scene_item_count(self) -> int:
        """GL 씬의 현재 아이템 수를 반환합니다 (메모리·렌더링 누수 감지용)."""
        try:
            return len(self._viewer.items)
        except Exception:
            return -1

    def _reset_simulation_stock(self, refresh_surface: bool = True):
        """재생용 스톡을 초기 상태로 되돌립니다."""
        if self._stock_model is None:
            self._simulation_stock_model = None
            return
        self._simulation_stock_model = self._stock_model.copy()
        self._viewer.set_stock(self._simulation_stock_model, refresh_surface=refresh_surface)

    def _segment_metrics(self, segment_index: int) -> dict | None:
        """세그먼트의 부하/채터 정보를 반환합니다.

        사전 계산된 캐시를 사용하여 재생 중 dict 생성을 방지합니다.
        """
        if self._precomputed_metrics is not None:
            if 0 <= segment_index < len(self._precomputed_metrics):
                return self._precomputed_metrics[segment_index]
            return None
        # 폴백: 분석 결과에서 직접 조회
        if self._machining_analysis is None:
            return None
        if segment_index < 0 or segment_index >= len(self._machining_analysis.results):
            return None
        result = self._machining_analysis.results[segment_index]
        return {
            "spindle_load_pct": result.spindle_load_pct,
            "chatter_risk_score": result.chatter_risk_score,
        }

    def _apply_simulation_segment(self, segment_index: int):
        """재생용 스톡에 단일 세그먼트를 누적 반영합니다.

        재료 변경이 없는 세그먼트(급속이동/드웰/스핀들OFF)는
        _rgba_dirty가 False로 유지되므로 GL 뷰어 업데이트를 건너뜁니다.
        """
        if self._simulation_stock_model is None or self._toolpath is None:
            return

        self._material_removal.simulate_step(
            segment_index,
            self._toolpath,
            self._simulation_stock_model,
            self._tools,
            self._segment_metrics(segment_index),
        )

        # _rgba_dirty == True: 이번 세그먼트에서 remove_material()이 호출됨
        # → 소재 형상이 바뀌었으므로 GL 뷰어 업데이트 필요
        # _rgba_dirty == False: 아무것도 변경되지 않음(급속이동 등)
        # → GPU 업로드·렌더링 불필요 (프레임당 비용 절감)
        if self._simulation_stock_model._rgba_dirty:
            self._viewer.set_stock(
                self._simulation_stock_model,
                refresh_surface=self._should_refresh_stock_surface(segment_index),
            )

    def _should_refresh_stock_surface(self, segment_index: int) -> bool:
        """
        3D 표면 메쉬 갱신 주기를 조절합니다.

        footprint 오버레이는 매 세그먼트마다 갱신하되, 무거운 3D 표면 메쉬는
        격자 수가 많을 때 간헐적으로만 갱신해 재생/소재 적용 렉을 줄입니다.
        """
        if self._simulation_stock_model is None:
            return True

        nx, ny = self._simulation_stock_model.grid_size
        cell_count = nx * ny
        if cell_count <= 12000:
            return True
        return segment_index % 8 == 0

    def _rebuild_simulation_stock(self, completed_segments: int):
        """특정 재생 위치까지의 가공 흔적을 처음부터 다시 누적합니다."""
        self._reset_simulation_stock(refresh_surface=False)
        if self._simulation_stock_model is None or self._toolpath is None:
            return

        for i in range(max(0, completed_segments)):
            self._material_removal.simulate_step(
                i,
                self._toolpath,
                self._simulation_stock_model,
                self._tools,
                self._segment_metrics(i),
            )
        self._viewer.set_stock(self._simulation_stock_model, refresh_surface=True)

    # ====================================================
    # 뷰어 색상 모드 변경
    # ====================================================

    def _on_color_mode_changed(self, index: int):
        """3D 뷰어 색상 모드를 변경합니다."""
        if self._machining_analysis is None or self._toolpath is None:
            return
        mode = ["default", "load", "chatter"][index]
        data = None
        if mode == "load":
            data = self._machining_analysis.get_spindle_load_array()
        elif mode == "chatter":
            data = self._machining_analysis.get_chatter_risk_array()

        try:
            self._viewer.set_color_mode(mode, data)
        except AttributeError:
            pass  # 폴백 뷰어는 set_color_mode 미지원

    # ====================================================
    # 메뉴/툴바 액션 핸들러
    # ====================================================

    def _on_segment_selected(self, index: int):
        """공구경로 목록에서 세그먼트 선택"""
        self._on_jump_to(index)

    def _on_open_nc_file(self):
        """NC 파일 열기 다이얼로그"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "NC 파일 열기", "",
            "NC 파일 (*.nc *.tap *.cnc *.gcode *.ngc);;모든 파일 (*)"
        )
        if filepath:
            self.load_nc_file(filepath)

    def _on_open_project(self):
        """프로젝트 파일 열기 다이얼로그"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "프로젝트 파일 열기", "",
            "YAML 프로젝트 (*.yaml *.yml);;모든 파일 (*)"
        )
        if filepath:
            self.load_project(filepath)

    def _on_save_report(self):
        """검증 보고서를 파일로 저장"""
        if self._toolpath is None:
            QMessageBox.information(self, "알림", "먼저 NC 파일을 로드하세요.")
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "보고서 저장", "nc_report.txt", "텍스트 파일 (*.txt)"
        )
        if filepath:
            report = self._report_service.generate_report(
                self._toolpath, self._warnings,
                self._machine, self._tools, self._project_config,
                self._machining_analysis
            )
            self._report_service.save_report(report, filepath)
            QMessageBox.information(self, "저장 완료", f"보고서가 저장되었습니다:\n{filepath}")

    def _on_save_analysis_csv(self):
        """해석/검증 결과를 CSV 묶음으로 저장합니다."""
        if self._toolpath is None:
            QMessageBox.information(self, "알림", "먼저 NC 파일을 로드해 주세요.")
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "CSV 저장",
            "nc_analysis.csv",
            "CSV 파일 (*.csv)",
        )
        if not filepath:
            return

        try:
            saved_paths = self._report_service.save_analysis_csv_bundle(
                filepath,
                self._toolpath,
                self._warnings,
                self._machine,
                self._tools,
                self._project_config,
                self._machining_analysis,
            )
            msg = (
                "CSV 저장이 완료되었습니다.\n\n"
                f"- 요약: {saved_paths['summary']}\n"
                f"- 공구: {saved_paths['tools']}\n"
                f"- 경고: {saved_paths['warnings']}\n"
                f"- 세그먼트: {saved_paths['segments']}"
            )
            QMessageBox.information(self, "저장 완료", msg)
        except Exception as exc:
            logger.error("CSV 저장 실패: %s", exc, exc_info=True)
            QMessageBox.critical(
                self,
                "CSV 저장 오류",
                f"해석 결과 CSV 저장 중 오류가 발생했습니다:\n{str(exc)}",
            )

    def _on_show_report(self):
        """검증 보고서 다이얼로그 표시"""
        if self._toolpath is None:
            QMessageBox.information(self, "알림", "먼저 NC 파일을 로드하세요.")
            return
        report = self._report_service.generate_report(
            self._toolpath, self._warnings,
            self._machine, self._tools, self._project_config,
            self._machining_analysis
        )
        dialog = ReportDialog(report, self)
        dialog.exec()

    def _on_toggle_stock(self, checked: bool):
        """소재 표시 토글"""
        self._viewer.set_show_stock(checked)

    def _on_about(self):
        """프로그램 정보"""
        QMessageBox.about(
            self, "CNC 시뮬레이터 정보",
            "<h2>CNC NC 코드 시뮬레이터</h2>"
            "<p>버전: 0.2.0</p>"
            "<p>3축 CNC 가공 NC 코드를 파싱, 시뮬레이션, 수치 해석, 검증하는 도구입니다.</p>"
            "<br>"
            "<p><b>핵심 기능:</b></p>"
            "<ul>"
            "<li>G코드 파싱 (G0, G1, G2, G3)</li>"
            "<li>pyqtgraph.opengl 기반 3D 공구경로 시각화</li>"
            "<li>스핀들 부하 추정 (Kienzle 단순화 모델)</li>"
            "<li>채터/진동 위험도 추정 (복합 휴리스틱 모델)</li>"
            "<li>블록별 가공 해석 차트</li>"
            "<li>NC 코드 검증 및 보고서</li>"
            "</ul>"
            "<br>"
            "<p><b>주의:</b> 이 소프트웨어의 수치 모델은 연구/개발/교육 목적의 "
            "공학적 근사 모델입니다. 실제 가공에서의 정확성을 보장하지 않습니다.</p>"
        )
