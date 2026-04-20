"""
공구 기하학(Tool Geometry) 모듈
공구의 형상 정보를 계산하고 제공합니다.
절삭 원통, 스윕 볼륨 경계 박스 등을 계산합니다.
"""
from __future__ import annotations
from typing import Dict, Tuple
import numpy as np

from app.models.tool import Tool, ToolType
from app.utils.logger import get_logger

logger = get_logger("tool_geometry")


class ToolGeometry:
    """
    공구 기하학 계산 클래스

    공구의 물리적 형상을 기하학적으로 표현하고
    가공 시뮬레이션에 필요한 형상 데이터를 제공합니다.
    """

    @staticmethod
    def get_cutting_cylinder(tool: Tool) -> Dict:
        """
        공구의 절삭 원통 형상을 반환합니다.
        원통의 중심 축은 Z축 방향입니다.

        Args:
            tool: 공구 정보

        Returns:
            절삭 원통 정보 딕셔너리:
            - center: 원통 중심 [X, Y, Z] (공구 끝점 기준)
            - radius: 원통 반경 (mm)
            - height: 절삭날 길이 (mm)
            - type: 공구 종류
        """
        return {
            'center': np.array([0.0, 0.0, 0.0]),  # 공구 끝점이 원점
            'radius': tool.radius_mm,
            'height': tool.flute_length,
            'type': tool.tool_type,
            'corner_radius': tool.corner_radius,
        }

    @staticmethod
    def get_swept_volume_bbox(start: np.ndarray, end: np.ndarray,
                               tool: Tool) -> Tuple[np.ndarray, np.ndarray]:
        """
        공구가 두 점 사이를 이동할 때 스윕되는 볼륨의 경계 박스를 계산합니다.
        공구 반경과 절삭날 길이를 고려합니다.

        Args:
            start: 이동 시작점 [X, Y, Z]
            end: 이동 끝점 [X, Y, Z]
            tool: 공구 정보

        Returns:
            (min_corner, max_corner) 경계 박스 튜플
        """
        radius_mm = tool.radius_mm

        # 기본 경계 박스: 시작점과 끝점의 최솟값/최댓값
        min_corner = np.minimum(start, end)
        max_corner = np.maximum(start, end)

        # XY 방향으로 공구 반경만큼 확장
        min_corner[0] -= radius_mm
        min_corner[1] -= radius_mm
        max_corner[0] += radius_mm
        max_corner[1] += radius_mm

        # Z 방향으로 절삭날 길이만큼 위로 확장 (공구 몸통 고려)
        # 공구 끝점이 start/end이므로 절삭날은 그 위에 있음
        max_corner[2] = max(max_corner[2] + tool.flute_length,
                            min_corner[2] + tool.flute_length)

        return min_corner, max_corner

    @staticmethod
    def generate_tool_mesh(tool: Tool, position: np.ndarray,
                           num_segments: int = 16) -> Tuple[np.ndarray, np.ndarray]:
        """
        시각화를 위한 공구 3D 메시 데이터를 생성합니다.
        원통형으로 단순화하여 표현합니다.

        Args:
            tool: 공구 정보
            position: 공구 끝점 위치 [X, Y, Z]
            num_segments: 원통 분할 수 (클수록 부드러움)

        Returns:
            (vertices, faces) 메시 데이터 튜플
        """
        radius_mm = tool.radius_mm
        flute_length = tool.flute_length
        shank_radius = radius_mm * 0.8  # 생크 반경 (날부보다 약간 작게)

        vertices = []
        faces = []

        # 공구 끝점부터 위쪽으로 생성
        # 바닥 원 (공구 끝)
        bottom_z = position[2]
        top_z = position[2] + flute_length

        angles = np.linspace(0, 2 * np.pi, num_segments, endpoint=False)

        # 바닥 원 꼭짓점
        bottom_center_idx = len(vertices)
        vertices.append([position[0], position[1], bottom_z])

        for angle in angles:
            x = position[0] + radius_mm * np.cos(angle)
            y = position[1] + radius_mm * np.sin(angle)
            vertices.append([x, y, bottom_z])

        # 상단 원 꼭짓점
        top_center_idx = len(vertices)
        vertices.append([position[0], position[1], top_z])

        for angle in angles:
            x = position[0] + radius_mm * np.cos(angle)
            y = position[1] + radius_mm * np.sin(angle)
            vertices.append([x, y, top_z])

        # 바닥 면 (팬 형태)
        for i in range(num_segments):
            next_i = (i + 1) % num_segments
            faces.append([bottom_center_idx,
                          bottom_center_idx + 1 + i,
                          bottom_center_idx + 1 + next_i])

        # 측면 (쿼드를 삼각형 두 개로 분할)
        for i in range(num_segments):
            next_i = (i + 1) % num_segments
            b1 = bottom_center_idx + 1 + i
            b2 = bottom_center_idx + 1 + next_i
            t1 = top_center_idx + 1 + i
            t2 = top_center_idx + 1 + next_i

            faces.append([b1, b2, t1])
            faces.append([b2, t2, t1])

        # 상단 면 (팬 형태)
        for i in range(num_segments):
            next_i = (i + 1) % num_segments
            faces.append([top_center_idx,
                          top_center_idx + 1 + next_i,
                          top_center_idx + 1 + i])

        return np.array(vertices, dtype=float), np.array(faces, dtype=int)

    @staticmethod
    def get_tool_color(tool: Tool) -> Tuple[float, float, float]:
        """
        공구 종류에 따른 시각화 색상을 반환합니다.

        Args:
            tool: 공구 정보

        Returns:
            RGB 색상 튜플 (0.0 ~ 1.0)
        """
        color_map = {
            ToolType.END_MILL: (0.7, 0.7, 0.2),    # 노란색 계열
            ToolType.BALL_END: (0.2, 0.7, 0.7),    # 청록색 계열
            ToolType.DRILL: (0.7, 0.3, 0.3),       # 빨간색 계열
            ToolType.FACE_MILL: (0.3, 0.7, 0.3),   # 초록색 계열
            ToolType.TAP: (0.7, 0.3, 0.7),         # 보라색 계열
        }
        return color_map.get(tool.tool_type, (0.7, 0.7, 0.7))
