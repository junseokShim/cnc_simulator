"""
3D 뷰어(Viewer3D) 모듈

공구경로와 현재 공구 위치뿐 아니라,
누적 가공 흔적(footprint) 오버레이를 함께 표시합니다.

[표시 요소]
- 스톡 경계
- 누적 가공 흔적 / 제거 영역 맵
- 공구경로 (급속/절삭/원호)
- 현재 공구 위치
"""
from __future__ import annotations
import math
from typing import List, Optional

import numpy as np

from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.geometry.stock_model import StockModel
from app.models.tool import Tool
from app.models.toolpath import MotionSegment, MotionType, Toolpath
from app.utils.logger import get_logger

logger = get_logger("viewer_3d")

_PYQTGRAPH_GL_AVAILABLE = False
try:
    import pyqtgraph as pg
    import pyqtgraph.opengl as gl
    from pyqtgraph.opengl import (
        GLImageItem,
        GLLinePlotItem,
        GLMeshItem,
        GLScatterPlotItem,
        GLViewWidget,
    )
    import OpenGL  # noqa: F401

    _PYQTGRAPH_GL_AVAILABLE = True
except Exception as exc:
    logger.warning(f"pyqtgraph.opengl 사용 불가: {exc} - 2D 폴백 뷰어 사용")


def _arc_to_polyline(seg: MotionSegment, min_steps: int = 8) -> np.ndarray:
    """원호 세그먼트를 폴리라인 점 집합으로 변환합니다."""
    if seg.arc_center is None or seg.arc_radius is None:
        return np.array([seg.start_pos, seg.end_pos], dtype=float)

    center = seg.arc_center
    start = seg.start_pos
    end = seg.end_pos
    clockwise = seg.motion_type == MotionType.ARC_CW

    start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
    end_angle = math.atan2(end[1] - center[1], end[0] - center[0])

    if clockwise and end_angle > start_angle:
        end_angle -= 2.0 * math.pi
    if not clockwise and end_angle < start_angle:
        end_angle += 2.0 * math.pi

    total_angle = abs(end_angle - start_angle)
    steps = max(min_steps, int(total_angle / (math.pi / 16.0)))
    pts = np.zeros((steps + 1, 3), dtype=float)
    for i in range(steps + 1):
        t = i / steps
        angle = start_angle + (end_angle - start_angle) * t
        pts[i, 0] = center[0] + seg.arc_radius * math.cos(angle)
        pts[i, 1] = center[1] + seg.arc_radius * math.sin(angle)
        pts[i, 2] = start[2] + (end[2] - start[2]) * t
    return pts


class _FallbackViewer2D(QWidget):
    """
    OpenGL이 없는 환경에서 사용하는 2D XY 뷰어

    footprint 이미지와 공구경로를 함께 그립니다.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._toolpath: Optional[Toolpath] = None
        self._stock_model: Optional[StockModel] = None
        self._current_pos: Optional[np.ndarray] = None
        self._current_tool: Optional[Tool] = None
        self._color_mode: str = "default"
        self._segment_color_data: Optional[np.ndarray] = None
        self._show_stock: bool = True
        self._plot = None
        self._trace_item = None
        self._pos_scatter = None
        self._stock_bounds_item = None
        self._pg_available = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        try:
            import pyqtgraph as pg

            pg.setConfigOptions(antialias=True, background="#262626")
            self._plot = pg.PlotWidget()
            self._plot.setLabel("bottom", "X (mm)")
            self._plot.setLabel("left", "Y (mm)")
            self._plot.setTitle("공구경로 / 가공 흔적 뷰")
            self._plot.showGrid(x=True, y=True, alpha=0.3)
            self._plot.setAspectLocked(True)
            layout.addWidget(self._plot)

            self._trace_item = pg.ImageItem()
            self._trace_item.setZValue(-20)
            self._plot.addItem(self._trace_item)

            self._pos_scatter = pg.ScatterPlotItem(
                size=12,
                pen=pg.mkPen("#ff5555", width=2),
                brush=pg.mkBrush(255, 90, 90, 220),
            )
            self._plot.addItem(self._pos_scatter)
            self._pg_available = True
        except Exception:
            lbl = QLabel("2D/3D 뷰어를 사용하려면 pyqtgraph가 필요합니다.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(lbl)

    def set_toolpath(self, toolpath: Toolpath):
        self._toolpath = toolpath
        self._redraw()

    def set_stock(self, stock_model: Optional[StockModel]):
        self._stock_model = stock_model
        self._update_stock_overlay()

    def set_current_position(self, pos: Optional[np.ndarray], tool: Optional[Tool] = None):
        self._current_pos = pos
        self._current_tool = tool
        if self._pg_available and self._pos_scatter is not None:
            if pos is None:
                self._pos_scatter.setData([], [])
            else:
                self._pos_scatter.setData([pos[0]], [pos[1]])

    def highlight_segment(self, index: int):
        # 2D 폴백에서는 별도 하이라이트 라인을 두지 않고 현재 공구 위치만 강조합니다.
        pass

    def reset_camera(self):
        if self._pg_available and self._plot is not None:
            self._plot.autoRange()

    def set_show_stock(self, show: bool):
        self._show_stock = show
        if self._trace_item is not None:
            self._trace_item.setVisible(show)
        if self._stock_bounds_item is not None:
            self._stock_bounds_item.setVisible(show)

    def set_color_mode(self, mode: str, data: Optional[np.ndarray] = None):
        self._color_mode = mode
        self._segment_color_data = data
        self._update_stock_overlay()
        self._redraw()

    def _update_stock_overlay(self):
        if not self._pg_available or self._trace_item is None:
            return

        if self._stock_model is None or not self._show_stock:
            self._trace_item.setImage(np.zeros((1, 1, 4), dtype=np.ubyte), autoLevels=False)
            if self._stock_bounds_item is not None:
                self._stock_bounds_item.setVisible(False)
            return

        mode = "footprint" if self._color_mode == "default" else self._color_mode
        rgba = self._stock_model.get_trace_image_rgba(mode=mode)
        # ImageItem은 (row, col, channel) 순서를 기대하므로 축을 교환합니다.
        img = np.transpose(rgba, (1, 0, 2))
        self._trace_item.setImage(img, autoLevels=False)
        rect = QRectF(
            float(self._stock_model.min_corner[0]),
            float(self._stock_model.min_corner[1]),
            float(self._stock_model.max_corner[0] - self._stock_model.min_corner[0]),
            float(self._stock_model.max_corner[1] - self._stock_model.min_corner[1]),
        )
        self._trace_item.setRect(rect)

        if self._stock_bounds_item is not None:
            self._plot.removeItem(self._stock_bounds_item)
            self._stock_bounds_item = None

        import pyqtgraph as pg

        x0, y0 = self._stock_model.min_corner[:2]
        x1, y1 = self._stock_model.max_corner[:2]
        path_x = [x0, x1, x1, x0, x0]
        path_y = [y0, y0, y1, y1, y0]
        self._stock_bounds_item = self._plot.plot(
            path_x, path_y, pen=pg.mkPen("#c79b45", width=1.5)
        )
        self._stock_bounds_item.setZValue(-5)

    def _redraw(self):
        if not self._pg_available or self._plot is None:
            return

        self._plot.clear()
        if self._trace_item is not None:
            self._plot.addItem(self._trace_item)
        self._update_stock_overlay()
        if self._pos_scatter is not None:
            self._plot.addItem(self._pos_scatter)

        if self._toolpath is None:
            return

        import pyqtgraph as pg

        def draw_segments(segments: List[MotionSegment], pen):
            if not segments:
                return
            x_coords: List[float | None] = []
            y_coords: List[float | None] = []
            for seg in segments:
                if seg.is_arc and seg.arc_center is not None:
                    pts = _arc_to_polyline(seg)
                    x_coords.extend(pts[:, 0].tolist() + [None])
                    y_coords.extend(pts[:, 1].tolist() + [None])
                else:
                    x_coords.extend([seg.start_pos[0], seg.end_pos[0], None])
                    y_coords.extend([seg.start_pos[1], seg.end_pos[1], None])
            self._plot.plot(x_coords, y_coords, pen=pen)

        rapid = [s for s in self._toolpath.segments if s.motion_type == MotionType.RAPID]
        cutting = [s for s in self._toolpath.segments if s.is_cutting_move]
        draw_segments(rapid, pg.mkPen("#4488ff", width=1.2))

        if self._color_mode == "default" or self._segment_color_data is None:
            draw_segments(cutting, pg.mkPen("#33ee66", width=2.0))
        else:
            for i, seg in enumerate(self._toolpath.segments):
                if not seg.is_cutting_move:
                    continue
                value = float(self._segment_color_data[i]) / 100.0 if i < len(self._segment_color_data) else 0.0
                value = float(np.clip(value, 0.0, 1.0))
                if value <= 0.5:
                    color = (int(value * 2.0 * 255), 255, 60)
                else:
                    color = (255, int((1.0 - (value - 0.5) * 2.0) * 255), 40)
                pts = _arc_to_polyline(seg) if seg.is_arc else np.array([seg.start_pos, seg.end_pos])
                self._plot.plot(
                    pts[:, 0], pts[:, 1],
                    pen=pg.mkPen(color=color, width=2.0),
                )


if _PYQTGRAPH_GL_AVAILABLE:
    class Viewer3D(GLViewWidget):
        """
        OpenGL 기반 3D 뷰어

        스톡 경계 + footprint 이미지 + 공구경로 + 현재 공구 위치를 함께 렌더링합니다.
        """

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setBackgroundColor("#262626")
            self.setCameraPosition(distance=250, elevation=30, azimuth=45)

            self._toolpath: Optional[Toolpath] = None
            self._stock_model: Optional[StockModel] = None
            self._current_pos: Optional[np.ndarray] = None
            self._current_tool: Optional[Tool] = None
            self._color_mode: str = "default"
            self._segment_color_data: Optional[np.ndarray] = None
            self._show_stock: bool = True

            self._path_items: List[GLLinePlotItem] = []
            self._grid_item = None
            self._axis_items: List[GLLinePlotItem] = []
            self._stock_bounds_item: Optional[GLLinePlotItem] = None
            self._stock_overlay_item: Optional[GLImageItem] = None
            self._stock_surface_item: Optional[GLMeshItem] = None
            self._pos_item: Optional[GLScatterPlotItem] = None

            self._add_grid_and_axes()
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.setMinimumSize(400, 300)

        def _add_grid_and_axes(self):
            grid = gl.GLGridItem()
            grid.setSize(200, 200)
            grid.setSpacing(10, 10)
            self.addItem(grid)
            self._grid_item = grid

            axis_defs = [
                (np.array([[0, 0, 0], [50, 0, 0]], dtype=np.float32), (1.0, 0.2, 0.2, 1.0)),
                (np.array([[0, 0, 0], [0, 50, 0]], dtype=np.float32), (0.2, 1.0, 0.2, 1.0)),
                (np.array([[0, 0, 0], [0, 0, 50]], dtype=np.float32), (0.2, 0.4, 1.0, 1.0)),
            ]
            for pts, color in axis_defs:
                item = GLLinePlotItem(pos=pts, color=color, width=2.0, antialias=True)
                self.addItem(item)
                self._axis_items.append(item)

        def _clear_path_items(self):
            for item in self._path_items:
                self.removeItem(item)
            self._path_items.clear()

        def _clear_pos_item(self):
            if self._pos_item is not None:
                self.removeItem(self._pos_item)
                self._pos_item = None

        def _clear_stock_items(self):
            if self._stock_bounds_item is not None:
                self.removeItem(self._stock_bounds_item)
                self._stock_bounds_item = None
            if self._stock_overlay_item is not None:
                self.removeItem(self._stock_overlay_item)
                self._stock_overlay_item = None
            if self._stock_surface_item is not None:
                self.removeItem(self._stock_surface_item)
                self._stock_surface_item = None

        def set_toolpath(self, toolpath: Toolpath):
            self._toolpath = toolpath
            self._redraw_toolpath()

            if toolpath is None or not toolpath.segments:
                return

            bounds_min, bounds_max = toolpath.get_bounds()
            center = (bounds_min + bounds_max) / 2.0
            size = float(np.linalg.norm(bounds_max - bounds_min))
            self.setCameraPosition(
                pos=pg.Vector(center[0], center[1], center[2]),
                distance=max(100.0, size * 2.0),
                elevation=30,
                azimuth=45,
            )

        def set_stock(self, stock_model: Optional[StockModel]):
            self._stock_model = stock_model
            self._update_stock_overlay()

        def set_current_position(self, pos: Optional[np.ndarray], tool: Optional[Tool] = None):
            self._current_pos = pos
            self._current_tool = tool
            self._clear_pos_item()

            if pos is None:
                return

            size = max(2.5, tool.radius if tool is not None else 3.0) * 4.0
            item = GLScatterPlotItem(
                pos=np.array([pos], dtype=np.float32),
                size=size,
                color=(1.0, 0.3, 0.3, 0.95),
                pxMode=False,
            )
            self.addItem(item)
            self._pos_item = item

        def highlight_segment(self, index: int):
            # 공구 위치와 footprint가 더 중요한 뷰이므로 별도 세그먼트 하이라이트는 생략합니다.
            pass

        def reset_camera(self):
            self.setCameraPosition(distance=250, elevation=30, azimuth=45)

        def set_show_stock(self, show: bool):
            self._show_stock = show
            if self._stock_overlay_item is not None:
                self._stock_overlay_item.setVisible(show)
            if self._stock_bounds_item is not None:
                self._stock_bounds_item.setVisible(show)

        def set_color_mode(self, mode: str, data: Optional[np.ndarray] = None):
            self._color_mode = mode
            self._segment_color_data = data
            self._redraw_toolpath()
            self._update_stock_overlay()

        def _update_stock_overlay(self):
            self._clear_stock_items()

            if not self._show_stock or self._stock_model is None:
                return

            min_c = self._stock_model.min_corner
            max_c = self._stock_model.max_corner

            edges = np.array([
                [min_c[0], min_c[1], min_c[2]], [max_c[0], min_c[1], min_c[2]], [np.nan, np.nan, np.nan],
                [max_c[0], min_c[1], min_c[2]], [max_c[0], max_c[1], min_c[2]], [np.nan, np.nan, np.nan],
                [max_c[0], max_c[1], min_c[2]], [min_c[0], max_c[1], min_c[2]], [np.nan, np.nan, np.nan],
                [min_c[0], max_c[1], min_c[2]], [min_c[0], min_c[1], min_c[2]], [np.nan, np.nan, np.nan],
                [min_c[0], min_c[1], max_c[2]], [max_c[0], min_c[1], max_c[2]], [np.nan, np.nan, np.nan],
                [max_c[0], min_c[1], max_c[2]], [max_c[0], max_c[1], max_c[2]], [np.nan, np.nan, np.nan],
                [max_c[0], max_c[1], max_c[2]], [min_c[0], max_c[1], max_c[2]], [np.nan, np.nan, np.nan],
                [min_c[0], max_c[1], max_c[2]], [min_c[0], min_c[1], max_c[2]], [np.nan, np.nan, np.nan],
                [min_c[0], min_c[1], min_c[2]], [min_c[0], min_c[1], max_c[2]], [np.nan, np.nan, np.nan],
                [max_c[0], min_c[1], min_c[2]], [max_c[0], min_c[1], max_c[2]], [np.nan, np.nan, np.nan],
                [max_c[0], max_c[1], min_c[2]], [max_c[0], max_c[1], max_c[2]], [np.nan, np.nan, np.nan],
                [min_c[0], max_c[1], min_c[2]], [min_c[0], max_c[1], max_c[2]], [np.nan, np.nan, np.nan],
            ], dtype=np.float32)

            self._stock_bounds_item = GLLinePlotItem(
                pos=edges,
                color=(0.80, 0.62, 0.24, 0.85),
                width=1.5,
                antialias=True,
            )
            self.addItem(self._stock_bounds_item)

            vertices, faces = self._stock_model.to_mesh_data()
            if len(vertices) > 0 and len(faces) > 0:
                mesh_data = gl.MeshData(
                    vertexes=vertices.astype(np.float32),
                    faces=faces.astype(np.uint32),
                )
                surface = GLMeshItem(
                    meshdata=mesh_data,
                    smooth=False,
                    drawEdges=False,
                    drawFaces=True,
                    color=(0.62, 0.52, 0.38, 0.55),
                    glOptions="translucent",
                )
                self.addItem(surface)
                self._stock_surface_item = surface

            overlay_mode = "footprint" if self._color_mode == "default" else self._color_mode
            image = self._stock_model.get_trace_image_rgba(mode=overlay_mode)
            overlay = GLImageItem(image, smooth=False, glOptions="translucent")
            overlay.scale(self._stock_model.resolution, self._stock_model.resolution, 1.0)
            overlay.translate(
                float(self._stock_model.min_corner[0]),
                float(self._stock_model.min_corner[1]),
                float(self._stock_model.max_corner[2] + 0.05),
            )
            self.addItem(overlay)
            self._stock_overlay_item = overlay

        def _redraw_toolpath(self):
            self._clear_path_items()
            if self._toolpath is None:
                return

            for i, seg in enumerate(self._toolpath.segments):
                pts = _arc_to_polyline(seg) if seg.is_arc else np.array([seg.start_pos, seg.end_pos], dtype=np.float32)
                color = self._segment_color(seg, i)
                width = 1.5 if seg.motion_type == MotionType.RAPID else 2.0
                item = GLLinePlotItem(
                    pos=pts.astype(np.float32),
                    color=color,
                    width=width,
                    antialias=True,
                )
                self.addItem(item)
                self._path_items.append(item)

        def _segment_color(self, seg: MotionSegment, index: int) -> tuple:
            if seg.motion_type == MotionType.RAPID:
                return (0.28, 0.55, 1.0, 0.55)

            if self._color_mode == "default" or self._segment_color_data is None:
                if seg.is_arc:
                    return (1.0, 0.82, 0.22, 1.0)
                return (0.22, 0.92, 0.36, 1.0)

            value = float(self._segment_color_data[index]) / 100.0 if index < len(self._segment_color_data) else 0.0
            value = float(np.clip(value, 0.0, 1.0))
            if value <= 0.5:
                r = value * 2.0
                g = 1.0
            else:
                r = 1.0
                g = 1.0 - (value - 0.5) * 2.0
            return (float(r), float(g), 0.10, 1.0)

else:
    class Viewer3D(_FallbackViewer2D):
        """OpenGL 사용 불가 시 2D 폴백 뷰어를 사용합니다."""
