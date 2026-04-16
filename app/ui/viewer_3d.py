"""
3D 뷰어(Viewer3D) 모듈
PyOpenGL을 사용하여 공구경로와 소재를 3D로 시각화합니다.
마우스 드래그로 궤도/이동/확대 기능을 제공합니다.
"""
from __future__ import annotations
from typing import Optional, List, Tuple
import math
import numpy as np

try:
    from PySide6.QtWidgets import QOpenGLWidget, QSizePolicy
    from PySide6.QtCore import Qt, QPoint, QTimer
    from PySide6.QtGui import QMouseEvent, QWheelEvent
    from OpenGL.GL import *
    from OpenGL.GLU import *
    _OPENGL_AVAILABLE = True
except ImportError:
    _OPENGL_AVAILABLE = False
    from PySide6.QtWidgets import QWidget as QOpenGLWidget

from app.models.toolpath import Toolpath, MotionType, MotionSegment
from app.models.tool import Tool
from app.geometry.stock_model import StockModel
from app.utils.logger import get_logger

logger = get_logger("viewer_3d")


class Viewer3D(QOpenGLWidget):
    """
    OpenGL 기반 3D 공구경로 뷰어 클래스

    공구경로를 색상별 선으로 표시합니다:
    - 파란색: 급속 이동 (G0)
    - 초록색: 절삭 이동 (G1)
    - 노란색: 원호 이동 (G2/G3)
    - 빨간색: 현재 위치 마커

    마우스 조작:
    - 좌버튼 드래그: 궤도 회전
    - 중간버튼 드래그: 화면 이동 (팬)
    - 스크롤 휠: 확대/축소
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 카메라 상태
        self._camera_azimuth = 45.0    # 수평 회전각 (도)
        self._camera_elevation = 30.0  # 수직 회전각 (도)
        self._camera_distance = 200.0  # 카메라 거리 (mm)
        self._camera_target = np.array([0.0, 0.0, 0.0])  # 카메라가 바라보는 중심점

        # 마우스 상태
        self._last_mouse_pos = QPoint()
        self._mouse_button = Qt.MouseButton.NoButton

        # 표시 데이터
        self._toolpath: Optional[Toolpath] = None
        self._stock_model: Optional[StockModel] = None
        self._current_position: Optional[np.ndarray] = None
        self._current_tool: Optional[Tool] = None
        self._highlighted_segment: int = -1

        # 시각화 설정
        self._rapid_color = (0.2, 0.5, 1.0)      # 파란색 (급속 이동)
        self._cutting_color = (0.2, 0.9, 0.3)    # 초록색 (절삭 이동)
        self._arc_color = (1.0, 0.8, 0.2)        # 노란색 (원호 이동)
        self._highlight_color = (1.0, 0.2, 0.2)  # 빨간색 (현재 위치)
        self._bg_color = (0.15, 0.15, 0.18, 1.0) # 배경색 (어두운 회색)

        # 표시 옵션
        self._show_stock = True
        self._show_grid = True
        self._line_width = 2.0

        # 크기 정책 설정
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(400, 300)

    def initializeGL(self):
        """OpenGL 초기화 - 뷰어 생성 시 한번 호출됩니다."""
        if not _OPENGL_AVAILABLE:
            return

        # 배경색 설정
        glClearColor(*self._bg_color)

        # 깊이 테스트 활성화 (앞에 있는 객체가 뒤에 있는 것을 가림)
        glEnable(GL_DEPTH_TEST)

        # 선 부드럽게 처리
        glEnable(GL_LINE_SMOOTH)
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)

        # 블렌딩 설정 (투명도 처리)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        # 조명 설정
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, [1.0, 1.0, 1.0, 0.0])
        glLightfv(GL_LIGHT0, GL_AMBIENT, [0.3, 0.3, 0.3, 1.0])
        glLightfv(GL_LIGHT0, GL_DIFFUSE, [0.8, 0.8, 0.8, 1.0])

        # 색상 재질 추적 활성화
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

        logger.debug("OpenGL 초기화 완료")

    def resizeGL(self, width: int, height: int):
        """뷰포트 크기 변경 시 호출됩니다."""
        if not _OPENGL_AVAILABLE:
            return

        if height == 0:
            height = 1

        glViewport(0, 0, width, height)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()

        # 원근 투영 설정
        aspect = width / height
        gluPerspective(45.0, aspect, 0.1, 10000.0)

        glMatrixMode(GL_MODELVIEW)

    def paintGL(self):
        """화면 그리기 - 매 프레임 호출됩니다."""
        if not _OPENGL_AVAILABLE:
            return

        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()

        # 카메라 위치 설정
        self._setup_camera()

        # 좌표축 그리기
        self._draw_axes()

        # 격자 그리기
        if self._show_grid:
            self._draw_grid()

        # 소재 경계 박스 그리기
        if self._show_stock and self._stock_model is not None:
            self._draw_stock()

        # 공구경로 그리기
        if self._toolpath is not None:
            self._draw_toolpath()

        # 현재 공구 위치 표시
        if self._current_position is not None:
            self._draw_current_position()

    def _setup_camera(self):
        """카메라 변환 행렬을 설정합니다."""
        if not _OPENGL_AVAILABLE:
            return

        # 구면 좌표계에서 카메라 위치 계산
        azimuth_rad = math.radians(self._camera_azimuth)
        elevation_rad = math.radians(self._camera_elevation)

        cam_x = self._camera_distance * math.cos(elevation_rad) * math.sin(azimuth_rad)
        cam_y = self._camera_distance * math.cos(elevation_rad) * math.cos(azimuth_rad)
        cam_z = self._camera_distance * math.sin(elevation_rad)

        # 카메라를 타겟에서 오프셋한 위치로 설정
        eye_x = self._camera_target[0] + cam_x
        eye_y = self._camera_target[1] + cam_y
        eye_z = self._camera_target[2] + cam_z

        gluLookAt(
            eye_x, eye_y, eye_z,               # 카메라 위치
            self._camera_target[0],             # 타겟 X
            self._camera_target[1],             # 타겟 Y
            self._camera_target[2],             # 타겟 Z
            0.0, 0.0, 1.0                       # 상방 벡터 (Z축)
        )

    def _draw_axes(self):
        """XYZ 좌표축을 그립니다."""
        if not _OPENGL_AVAILABLE:
            return

        glDisable(GL_LIGHTING)
        glLineWidth(2.0)

        axis_length = 50.0

        glBegin(GL_LINES)
        # X축 - 빨간색
        glColor3f(1.0, 0.2, 0.2)
        glVertex3f(0, 0, 0)
        glVertex3f(axis_length, 0, 0)

        # Y축 - 초록색
        glColor3f(0.2, 1.0, 0.2)
        glVertex3f(0, 0, 0)
        glVertex3f(0, axis_length, 0)

        # Z축 - 파란색
        glColor3f(0.2, 0.2, 1.0)
        glVertex3f(0, 0, 0)
        glVertex3f(0, 0, axis_length)
        glEnd()

        glEnable(GL_LIGHTING)

    def _draw_grid(self):
        """XY 평면에 참조 격자를 그립니다."""
        if not _OPENGL_AVAILABLE:
            return

        glDisable(GL_LIGHTING)
        glLineWidth(0.5)
        glColor4f(0.35, 0.35, 0.35, 0.6)

        grid_size = 100
        grid_step = 10

        glBegin(GL_LINES)
        for i in range(-grid_size, grid_size + 1, grid_step):
            glVertex3f(float(i), float(-grid_size), 0)
            glVertex3f(float(i), float(grid_size), 0)
            glVertex3f(float(-grid_size), float(i), 0)
            glVertex3f(float(grid_size), float(i), 0)
        glEnd()

        glEnable(GL_LIGHTING)

    def _draw_stock(self):
        """소재 경계 박스를 와이어프레임으로 그립니다."""
        if not _OPENGL_AVAILABLE or self._stock_model is None:
            return

        min_c, max_c = self._stock_model.get_stock_bounds()

        glDisable(GL_LIGHTING)
        glLineWidth(1.5)
        glColor4f(0.6, 0.5, 0.2, 0.8)

        # 경계 박스의 12개 엣지 그리기
        x0, y0, z0 = min_c[0], min_c[1], min_c[2]
        x1, y1, z1 = max_c[0], max_c[1], max_c[2]

        glBegin(GL_LINES)
        # 하단면 4개 엣지
        glVertex3f(x0, y0, z0); glVertex3f(x1, y0, z0)
        glVertex3f(x1, y0, z0); glVertex3f(x1, y1, z0)
        glVertex3f(x1, y1, z0); glVertex3f(x0, y1, z0)
        glVertex3f(x0, y1, z0); glVertex3f(x0, y0, z0)
        # 상단면 4개 엣지
        glVertex3f(x0, y0, z1); glVertex3f(x1, y0, z1)
        glVertex3f(x1, y0, z1); glVertex3f(x1, y1, z1)
        glVertex3f(x1, y1, z1); glVertex3f(x0, y1, z1)
        glVertex3f(x0, y1, z1); glVertex3f(x0, y0, z1)
        # 수직 4개 엣지
        glVertex3f(x0, y0, z0); glVertex3f(x0, y0, z1)
        glVertex3f(x1, y0, z0); glVertex3f(x1, y0, z1)
        glVertex3f(x1, y1, z0); glVertex3f(x1, y1, z1)
        glVertex3f(x0, y1, z0); glVertex3f(x0, y1, z1)
        glEnd()

        glEnable(GL_LIGHTING)

    def _draw_toolpath(self):
        """공구경로를 색상별 선으로 그립니다."""
        if not _OPENGL_AVAILABLE or self._toolpath is None:
            return

        glDisable(GL_LIGHTING)
        glLineWidth(self._line_width)

        for seg in self._toolpath.segments:
            # 하이라이트된 세그먼트는 특별 색상
            if seg.segment_id == self._highlighted_segment:
                glColor3f(*self._highlight_color)
                glLineWidth(self._line_width * 2.0)
            else:
                # 이동 유형별 색상 설정
                if seg.motion_type == MotionType.RAPID:
                    glColor3f(*self._rapid_color)
                elif seg.is_arc:
                    glColor3f(*self._arc_color)
                else:
                    glColor3f(*self._cutting_color)
                glLineWidth(self._line_width)

            # 원호 이동은 세분화하여 곡선으로 표현
            if seg.is_arc and seg.arc_center is not None:
                self._draw_arc_segment(seg)
            else:
                # 직선 이동
                glBegin(GL_LINES)
                glVertex3f(seg.start_pos[0], seg.start_pos[1], seg.start_pos[2])
                glVertex3f(seg.end_pos[0], seg.end_pos[1], seg.end_pos[2])
                glEnd()

        glEnable(GL_LIGHTING)

    def _draw_arc_segment(self, seg: MotionSegment):
        """원호 세그먼트를 여러 선분으로 분할하여 그립니다."""
        if not _OPENGL_AVAILABLE:
            return

        from app.utils.math_utils import calc_arc_angle

        if seg.arc_center is None or seg.arc_radius is None:
            return

        center = seg.arc_center
        start = seg.start_pos
        end = seg.end_pos
        clockwise = (seg.motion_type == MotionType.ARC_CW)

        # 시작각과 끝각 계산
        start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
        end_angle_raw = math.atan2(end[1] - center[1], end[0] - center[0])

        if clockwise:
            end_angle = end_angle_raw
            if end_angle > start_angle:
                end_angle -= 2 * math.pi
        else:
            end_angle = end_angle_raw
            if end_angle < start_angle:
                end_angle += 2 * math.pi

        # 충분한 분할 수 결정
        total_angle = abs(end_angle - start_angle)
        num_steps = max(8, int(total_angle / (math.pi / 16)))

        glBegin(GL_LINE_STRIP)
        for i in range(num_steps + 1):
            t = i / num_steps
            angle = start_angle + t * (end_angle - start_angle)
            z = start[2] + t * (end[2] - start[2])
            x = center[0] + seg.arc_radius * math.cos(angle)
            y = center[1] + seg.arc_radius * math.sin(angle)
            glVertex3f(x, y, z)
        glEnd()

    def _draw_current_position(self):
        """현재 공구 위치를 구체/실린더로 표시합니다."""
        if not _OPENGL_AVAILABLE or self._current_position is None:
            return

        pos = self._current_position

        glEnable(GL_LIGHTING)
        glColor3f(1.0, 0.3, 0.3)  # 빨간색 공구 표시

        # 현재 위치에 작은 구체 그리기
        glPushMatrix()
        glTranslatef(pos[0], pos[1], pos[2])

        # 공구 직경에 따른 구체 크기 결정
        radius = 3.0
        if self._current_tool is not None:
            radius = max(2.0, self._current_tool.radius)

        quadric = gluNewQuadric()
        gluSphere(quadric, radius, 12, 8)
        gluDeleteQuadric(quadric)

        glPopMatrix()

        # 수직선으로 위치 표시 (공구 축)
        glDisable(GL_LIGHTING)
        glLineWidth(1.0)
        glColor4f(1.0, 0.3, 0.3, 0.5)
        glBegin(GL_LINES)
        glVertex3f(pos[0], pos[1], 0)
        glVertex3f(pos[0], pos[1], pos[2])
        glEnd()
        glEnable(GL_LIGHTING)

    # --- 마우스 이벤트 처리 ---

    def mousePressEvent(self, event: QMouseEvent):
        """마우스 버튼 누름 이벤트 처리"""
        self._last_mouse_pos = event.position().toPoint()
        self._mouse_button = event.button()

    def mouseMoveEvent(self, event: QMouseEvent):
        """마우스 이동 이벤트 처리 - 카메라 조작"""
        current_pos = event.position().toPoint()
        dx = current_pos.x() - self._last_mouse_pos.x()
        dy = current_pos.y() - self._last_mouse_pos.y()

        if self._mouse_button == Qt.MouseButton.LeftButton:
            # 좌버튼 드래그: 궤도 회전
            self._camera_azimuth += dx * 0.5
            self._camera_elevation = max(-89.0, min(89.0, self._camera_elevation - dy * 0.5))

        elif self._mouse_button == Qt.MouseButton.MiddleButton:
            # 중간버튼 드래그: 화면 이동 (팬)
            pan_scale = self._camera_distance * 0.001
            azimuth_rad = math.radians(self._camera_azimuth)

            # 카메라 방향에 수직인 벡터로 이동
            right_x = math.cos(azimuth_rad)
            right_y = -math.sin(azimuth_rad)

            self._camera_target[0] -= dx * pan_scale * right_x
            self._camera_target[1] -= dx * pan_scale * right_y
            self._camera_target[2] += dy * pan_scale

        self._last_mouse_pos = current_pos
        self.update()  # 화면 갱신 요청

    def mouseReleaseEvent(self, event: QMouseEvent):
        """마우스 버튼 해제 이벤트 처리"""
        self._mouse_button = Qt.MouseButton.NoButton

    def wheelEvent(self, event: QWheelEvent):
        """마우스 휠 이벤트 처리 - 확대/축소"""
        delta = event.angleDelta().y()
        zoom_factor = 0.9 if delta > 0 else 1.1

        self._camera_distance = max(10.0, min(5000.0,
                                               self._camera_distance * zoom_factor))
        self.update()

    # --- 공개 API 메서드 ---

    def set_toolpath(self, toolpath: Toolpath):
        """
        표시할 공구경로를 설정합니다.

        Args:
            toolpath: 표시할 Toolpath 객체
        """
        self._toolpath = toolpath

        # 카메라를 공구경로 중심으로 이동
        if toolpath and toolpath.segments:
            bounds_min, bounds_max = toolpath.get_bounds()
            center = (bounds_min + bounds_max) / 2
            self._camera_target = center.copy()

            # 적절한 카메라 거리 계산
            size = np.linalg.norm(bounds_max - bounds_min)
            self._camera_distance = max(100.0, size * 2.0)

        self.update()

    def set_current_position(self, pos: np.ndarray, tool: Optional[Tool] = None):
        """
        현재 공구 위치와 공구 정보를 설정합니다.

        Args:
            pos: 현재 위치 [X, Y, Z]
            tool: 현재 공구 (없으면 None)
        """
        self._current_position = pos.copy() if pos is not None else None
        self._current_tool = tool
        self.update()

    def highlight_segment(self, index: int):
        """
        특정 세그먼트를 강조 표시합니다.

        Args:
            index: 강조할 세그먼트 인덱스
        """
        if self._toolpath and 0 <= index < len(self._toolpath.segments):
            self._highlighted_segment = self._toolpath.segments[index].segment_id
        else:
            self._highlighted_segment = -1
        self.update()

    def set_stock(self, stock_model: Optional[StockModel]):
        """
        표시할 소재 모델을 설정합니다.

        Args:
            stock_model: 소재 모델 (없으면 None)
        """
        self._stock_model = stock_model
        self.update()

    def reset_camera(self):
        """카메라를 초기 위치로 리셋합니다."""
        self._camera_azimuth = 45.0
        self._camera_elevation = 30.0
        self._camera_distance = 200.0
        self._camera_target = np.array([0.0, 0.0, 0.0])
        self.update()

    def set_show_stock(self, show: bool):
        """소재 표시 여부를 설정합니다."""
        self._show_stock = show
        self.update()
