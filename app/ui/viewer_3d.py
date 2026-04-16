"""
3D 뷰어(Viewer3D) 모듈

pyqtgraph.opengl(GLViewWidget)을 사용하여 공구경로를 3D로 시각화합니다.
pyqtgraph는 PyOpenGL보다 더 안정적인 Qt 통합을 제공합니다.

색상 코드:
  파란색 (0.3, 0.6, 1.0): 급속 이동 (G0)
  초록색 (0.2, 0.9, 0.3): 직선 절삭 (G1)
  노란색 (1.0, 0.8, 0.2): 원호 이동 (G2/G3)
  빨간색 (1.0, 0.3, 0.3): 현재 공구 위치

마우스 조작 (pyqtgraph.opengl 기본 지원):
  좌버튼 드래그: 궤도 회전
  우버튼 드래그 또는 스크롤: 확대/축소
  중간버튼 드래그: 이동(팬)
"""
from __future__ import annotations
import math
from typing import Optional, List
import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy

from app.models.toolpath import Toolpath, MotionType, MotionSegment
from app.models.tool import Tool
from app.geometry.stock_model import StockModel
from app.utils.logger import get_logger

logger = get_logger("viewer_3d")

# pyqtgraph.opengl 임포트 시도
_PYQTGRAPH_GL_AVAILABLE = False
try:
    import pyqtgraph as pg
    import pyqtgraph.opengl as gl
    from pyqtgraph.opengl import GLViewWidget, GLLinePlotItem, GLScatterPlotItem, GLMeshItem
    import OpenGL  # noqa
    _PYQTGRAPH_GL_AVAILABLE = True
    logger.debug("pyqtgraph.opengl 사용 가능 - 3D 렌더링 활성화")
except Exception as e:
    logger.warning(f"pyqtgraph.opengl 사용 불가: {e} → 2D 폴백 뷰어 사용")


def _arc_to_polyline(seg: MotionSegment, num_steps: int = 32) -> np.ndarray:
    """
    원호 세그먼트를 폴리라인 점 배열로 변환합니다.

    Returns:
        shape (N, 3) numpy 배열
    """
    if seg.arc_center is None or seg.arc_radius is None:
        return np.array([seg.start_pos, seg.end_pos])

    center = seg.arc_center
    start = seg.start_pos
    end = seg.end_pos
    clockwise = (seg.motion_type == MotionType.ARC_CW)

    start_a = math.atan2(start[1] - center[1], start[0] - center[0])
    end_a = math.atan2(end[1] - center[1], end[0] - center[0])

    if clockwise:
        if end_a > start_a:
            end_a -= 2 * math.pi
    else:
        if end_a < start_a:
            end_a += 2 * math.pi

    total_angle = abs(end_a - start_a)
    steps = max(8, int(total_angle / (math.pi / 16)))

    pts = np.zeros((steps + 1, 3))
    for i in range(steps + 1):
        t = i / steps
        a = start_a + t * (end_a - start_a)
        pts[i, 0] = center[0] + seg.arc_radius * math.cos(a)
        pts[i, 1] = center[1] + seg.arc_radius * math.sin(a)
        pts[i, 2] = start[2] + t * (end[2] - start[2])
    return pts


class _FallbackViewer2D(QWidget):
    """
    pyqtgraph.opengl 사용 불가 시 pyqtgraph PlotWidget을 사용하는 2D 폴백 뷰어.
    XY 평면 투영 공구경로를 표시합니다.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._toolpath: Optional[Toolpath] = None
        self._current_pos: Optional[np.ndarray] = None
        self._highlighted: int = -1
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        try:
            import pyqtgraph as pg
            pg.setConfigOptions(antialias=True, background='#262626')
            self._plot = pg.PlotWidget()
            self._plot.setLabel('bottom', 'X (mm)')
            self._plot.setLabel('left', 'Y (mm)')
            self._plot.setTitle('공구경로 (XY 평면 투영)')
            self._plot.showGrid(x=True, y=True, alpha=0.3)
            self._plot.setAspectLocked(True)
            layout.addWidget(self._plot)
            # 현재 위치 산점도 아이템 (항상 표시)
            self._pos_scatter = pg.ScatterPlotItem(
                size=12, pen=pg.mkPen('r', width=2), brush=pg.mkBrush(255, 80, 80, 200)
            )
            self._plot.addItem(self._pos_scatter)
            self._pg_available = True
        except Exception:
            lbl = QLabel("3D/2D 뷰어 사용 불가\n(pyqtgraph 설치 필요)")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)
            self._pg_available = False

    def set_toolpath(self, toolpath: Toolpath):
        self._toolpath = toolpath
        self._redraw()

    def set_current_position(self, pos: Optional[np.ndarray], tool=None):
        self._current_pos = pos
        if self._pg_available and pos is not None:
            self._pos_scatter.setData([{'pos': (pos[0], pos[1]), 'data': 1}])

    def highlight_segment(self, index: int):
        self._highlighted = index

    def set_stock(self, stock_model):
        pass  # 2D 뷰에서는 소재 경계를 XY 투영으로 표시

    def reset_camera(self):
        if self._pg_available:
            self._plot.autoRange()

    def set_show_stock(self, show: bool):
        pass

    def _redraw(self):
        if not self._pg_available or self._toolpath is None:
            return
        self._plot.clear()
        self._plot.addItem(self._pos_scatter)

        # 급속, 절삭, 원호를 각각 별도 선으로 그림
        rapid_x, rapid_y = [], []
        cut_x, cut_y = [], []
        arc_x, arc_y = [], []

        for seg in self._toolpath.segments:
            if seg.is_arc and seg.arc_center is not None:
                pts = _arc_to_polyline(seg)
                arc_x.extend(pts[:, 0].tolist() + [None])
                arc_y.extend(pts[:, 1].tolist() + [None])
            elif seg.motion_type == MotionType.RAPID:
                rapid_x.extend([seg.start_pos[0], seg.end_pos[0], None])
                rapid_y.extend([seg.start_pos[1], seg.end_pos[1], None])
            else:
                cut_x.extend([seg.start_pos[0], seg.end_pos[0], None])
                cut_y.extend([seg.start_pos[1], seg.end_pos[1], None])

        import pyqtgraph as pg
        if rapid_x:
            self._plot.plot(rapid_x, rapid_y, pen=pg.mkPen('#4488ff', width=1))
        if cut_x:
            self._plot.plot(cut_x, cut_y, pen=pg.mkPen('#33ee55', width=2))
        if arc_x:
            self._plot.plot(arc_x, arc_y, pen=pg.mkPen('#ffcc33', width=2))
        self._plot.addItem(self._pos_scatter)


if _PYQTGRAPH_GL_AVAILABLE:
    class Viewer3D(GLViewWidget):
        """
        pyqtgraph.opengl 기반 3D 공구경로 뷰어

        GLViewWidget을 상속하며, 공구경로/소재/공구 위치를 3D로 표시합니다.
        """

        def __init__(self, parent=None):
            super().__init__(parent)

            # 배경색 설정
            self.setBackgroundColor('#262626')

            # 카메라 초기 위치
            self.setCameraPosition(distance=250, elevation=30, azimuth=45)

            # 표시 데이터
            self._toolpath: Optional[Toolpath] = None
            self._stock_model: Optional[StockModel] = None
            self._current_pos: Optional[np.ndarray] = None
            self._current_tool: Optional[Tool] = None
            self._highlighted: int = -1
            self._show_stock: bool = True

            # GL 아이템 참조 (업데이트 시 제거/재생성)
            self._path_items: List = []
            self._stock_item = None
            self._pos_item = None
            self._grid_item = None
            self._axis_items: List = []

            # 좌표축 및 격자 초기 설정
            self._add_grid_and_axes()

            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.setMinimumSize(400, 300)

        def _add_grid_and_axes(self):
            """좌표 격자와 XYZ 축을 추가합니다."""
            # XY 평면 격자
            grid = gl.GLGridItem()
            grid.setSize(200, 200)
            grid.setSpacing(10, 10)
            self.addItem(grid)
            self._grid_item = grid

            # XYZ 좌표축 (길이 50mm)
            axis_data = [
                (np.array([[0,0,0],[50,0,0]]), (1.0, 0.2, 0.2, 1.0)),  # X: 빨간색
                (np.array([[0,0,0],[0,50,0]]), (0.2, 1.0, 0.2, 1.0)),  # Y: 초록색
                (np.array([[0,0,0],[0,0,50]]), (0.2, 0.4, 1.0, 1.0)),  # Z: 파란색
            ]
            for pts, color in axis_data:
                item = gl.GLLinePlotItem(pos=pts, color=color, width=2.5, antialias=True)
                self.addItem(item)
                self._axis_items.append(item)

        def _clear_path_items(self):
            """이전 공구경로 GL 아이템을 모두 제거합니다."""
            for item in self._path_items:
                self.removeItem(item)
            self._path_items.clear()

        def _clear_pos_item(self):
            """현재 위치 마커를 제거합니다."""
            if self._pos_item is not None:
                self.removeItem(self._pos_item)
                self._pos_item = None

        def _clear_stock_item(self):
            """소재 아이템을 제거합니다."""
            if self._stock_item is not None:
                self.removeItem(self._stock_item)
                self._stock_item = None

        def set_toolpath(self, toolpath: Toolpath):
            """
            표시할 공구경로를 설정하고 렌더링합니다.

            급속/직선/원호를 색상 구분하여 3D 선으로 표시합니다.
            """
            self._toolpath = toolpath
            self._clear_path_items()

            if not toolpath or not toolpath.segments:
                return

            # 세그먼트를 유형별로 분류하여 배치 처리 (성능 최적화)
            rapid_segs: List[MotionSegment] = []
            cut_segs: List[MotionSegment] = []
            arc_segs: List[MotionSegment] = []

            for seg in toolpath.segments:
                if seg.is_arc:
                    arc_segs.append(seg)
                elif seg.motion_type == MotionType.RAPID:
                    rapid_segs.append(seg)
                else:
                    cut_segs.append(seg)

            # 급속 이동 - 파란색
            if rapid_segs:
                self._add_line_batch(
                    rapid_segs, color=(0.3, 0.6, 1.0, 0.7), width=1.5
                )

            # 직선 절삭 - 초록색
            if cut_segs:
                self._add_line_batch(
                    cut_segs, color=(0.2, 0.9, 0.35, 1.0), width=2.0
                )

            # 원호 이동 - 노란색 (폴리라인으로 변환)
            for seg in arc_segs:
                pts = _arc_to_polyline(seg)
                item = gl.GLLinePlotItem(
                    pos=pts, color=(1.0, 0.8, 0.2, 1.0), width=2.0, antialias=True
                )
                self.addItem(item)
                self._path_items.append(item)

            # 카메라를 공구경로 중심으로 이동
            bounds_min, bounds_max = toolpath.get_bounds()
            center = (bounds_min + bounds_max) / 2.0
            size = float(np.linalg.norm(bounds_max - bounds_min))
            self.setCameraPosition(
                pos=pg.Vector(center[0], center[1], center[2]),
                distance=max(100.0, size * 2.0),
                elevation=30,
                azimuth=45,
            )

        def _add_line_batch(
            self, segs: List[MotionSegment], color: tuple, width: float
        ):
            """
            세그먼트 목록을 하나의 연결되지 않은 선 집합으로 추가합니다.

            GLLinePlotItem은 연속 선이므로, 세그먼트 사이에 NaN을 삽입하여
            불연속 선을 표현합니다.
            """
            pts_list = []
            for seg in segs:
                pts_list.append(seg.start_pos)
                pts_list.append(seg.end_pos)
                # NaN 구분자: 이전/다음 세그먼트 연결 차단
                pts_list.append(np.array([np.nan, np.nan, np.nan]))

            pts = np.array(pts_list, dtype=np.float32)
            item = gl.GLLinePlotItem(pos=pts, color=color, width=width, antialias=True)
            self.addItem(item)
            self._path_items.append(item)

        def set_current_position(self, pos: Optional[np.ndarray], tool: Optional[Tool] = None):
            """현재 공구 위치를 빨간 구체로 표시합니다."""
            self._current_pos = pos
            self._current_tool = tool
            self._clear_pos_item()

            if pos is None:
                return

            # 공구 직경에 따라 마커 크기 결정
            radius = 3.0
            if tool is not None:
                radius = max(2.0, tool.radius)

            scatter = gl.GLScatterPlotItem(
                pos=np.array([pos], dtype=np.float32),
                size=radius * 4,
                color=(1.0, 0.3, 0.3, 0.95),
                pxMode=False,
            )
            self.addItem(scatter)
            self._pos_item = scatter

        def highlight_segment(self, index: int):
            """특정 세그먼트 강조 (현재는 위치 업데이트로 대체)"""
            self._highlighted = index

        def set_stock(self, stock_model: Optional[StockModel]):
            """소재 경계 박스를 와이어프레임으로 표시합니다."""
            self._stock_model = stock_model
            self._clear_stock_item()

            if not self._show_stock or stock_model is None:
                return

            min_c, max_c = stock_model.get_stock_bounds()
            x0, y0, z0 = min_c
            x1, y1, z1 = max_c

            # 경계 박스 12개 엣지
            edges = np.array([
                # 하단면
                [x0,y0,z0], [x1,y0,z0], [np.nan]*3,
                [x1,y0,z0], [x1,y1,z0], [np.nan]*3,
                [x1,y1,z0], [x0,y1,z0], [np.nan]*3,
                [x0,y1,z0], [x0,y0,z0], [np.nan]*3,
                # 상단면
                [x0,y0,z1], [x1,y0,z1], [np.nan]*3,
                [x1,y0,z1], [x1,y1,z1], [np.nan]*3,
                [x1,y1,z1], [x0,y1,z1], [np.nan]*3,
                [x0,y1,z1], [x0,y0,z1], [np.nan]*3,
                # 수직 엣지
                [x0,y0,z0], [x0,y0,z1], [np.nan]*3,
                [x1,y0,z0], [x1,y0,z1], [np.nan]*3,
                [x1,y1,z0], [x1,y1,z1], [np.nan]*3,
                [x0,y1,z0], [x0,y1,z1], [np.nan]*3,
            ], dtype=np.float32)

            item = gl.GLLinePlotItem(
                pos=edges, color=(0.8, 0.6, 0.2, 0.7), width=1.5, antialias=True
            )
            self.addItem(item)
            self._stock_item = item

        def reset_camera(self):
            """카메라를 기본 위치로 초기화합니다."""
            self.setCameraPosition(distance=250, elevation=30, azimuth=45)

        def set_show_stock(self, show: bool):
            """소재 표시 여부를 설정합니다."""
            self._show_stock = show
            if self._stock_item is not None:
                self._stock_item.setVisible(show)

        def set_color_mode(self, mode: str, data: Optional[np.ndarray] = None):
            """
            공구경로 색상 모드를 변경합니다.

            Args:
                mode: 'default' | 'load' | 'chatter'
                data: 세그먼트별 수치 데이터 (0~100 범위)
            """
            if mode == 'default' or data is None or self._toolpath is None:
                self.set_toolpath(self._toolpath)
                return

            # 부하/채터 데이터로 색상 매핑 (초록→노랑→빨강)
            self._clear_path_items()
            if not self._toolpath:
                return

            n = len(self._toolpath.segments)
            for i, seg in enumerate(self._toolpath.segments):
                if not seg.is_cutting_move:
                    color = (0.3, 0.5, 1.0, 0.5)  # 급속: 반투명 파란색
                else:
                    v = float(data[i]) / 100.0 if i < len(data) else 0.0
                    v = float(np.clip(v, 0.0, 1.0))
                    # 초록(0) → 노랑(0.5) → 빨강(1.0)
                    if v <= 0.5:
                        r = v * 2.0
                        g = 1.0
                    else:
                        r = 1.0
                        g = 1.0 - (v - 0.5) * 2.0
                    color = (r, g, 0.1, 1.0)

                if seg.is_arc and seg.arc_center is not None:
                    pts = _arc_to_polyline(seg)
                else:
                    pts = np.array([seg.start_pos, seg.end_pos], dtype=np.float32)

                item = gl.GLLinePlotItem(
                    pos=pts.astype(np.float32),
                    color=color, width=2.0, antialias=True
                )
                self.addItem(item)
                self._path_items.append(item)

else:
    # pyqtgraph.opengl 사용 불가 → 2D 폴백
    class Viewer3D(_FallbackViewer2D):
        """
        pyqtgraph.opengl 사용 불가 시 활성화되는 2D 폴백 뷰어.
        XY 평면 투영 공구경로를 표시합니다.
        """
        def set_color_mode(self, mode: str, data=None):
            pass  # 폴백 뷰어에서는 색상 모드 미지원
