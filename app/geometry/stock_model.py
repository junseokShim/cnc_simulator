"""
소재 모델(Stock Model) 모듈
Z-맵 방식으로 소재의 형상을 표현하고 재료 제거를 시뮬레이션합니다.
Z-맵은 각 XY 셀 위치에서의 최대 Z 높이를 저장하는 2D 배열입니다.
"""
from __future__ import annotations
from typing import Tuple, Optional
import numpy as np

from app.models.tool import Tool, ToolType
from app.utils.logger import get_logger

logger = get_logger("stock_model")


class StockModel:
    """
    Z-맵 기반 소재 모델 클래스

    소재를 2D 격자(그리드)로 표현합니다.
    각 셀은 해당 XY 위치에서의 최대 Z 높이를 저장합니다.
    재료가 제거되면 해당 셀의 Z 높이가 낮아집니다.
    """

    def __init__(self, min_corner: np.ndarray, max_corner: np.ndarray,
                 resolution: float = 1.0):
        """
        소재 모델을 초기화합니다.

        Args:
            min_corner: 소재 최소 모서리 [X, Y, Z]
            max_corner: 소재 최대 모서리 [X, Y, Z]
            resolution: 격자 셀 크기 (mm, 작을수록 정밀하지만 메모리 많이 사용)
        """
        self.min_corner = np.array(min_corner, dtype=float)
        self.max_corner = np.array(max_corner, dtype=float)
        self.resolution = float(resolution)

        # 격자 크기 계산
        size = self.max_corner - self.min_corner
        self._nx = max(1, int(np.ceil(size[0] / resolution)))  # X 방향 셀 수
        self._ny = max(1, int(np.ceil(size[1] / resolution)))  # Y 방향 셀 수

        # Z-맵 초기화: 모든 셀의 초기 Z 높이 = 소재 최대 Z
        self.grid = np.full((self._nx, self._ny), self.max_corner[2], dtype=float)

        logger.debug(f"소재 모델 생성: {self._nx}x{self._ny} 격자, "
                     f"해상도 {resolution}mm, "
                     f"범위 {min_corner} ~ {max_corner}")

    def _world_to_grid(self, x: float, y: float) -> Tuple[int, int]:
        """
        월드 좌표를 격자 인덱스로 변환합니다.

        Args:
            x, y: 월드 좌표

        Returns:
            (ix, iy) 격자 인덱스 (범위 클리핑 적용)
        """
        ix = int((x - self.min_corner[0]) / self.resolution)
        iy = int((y - self.min_corner[1]) / self.resolution)

        # 범위 클리핑
        ix = max(0, min(self._nx - 1, ix))
        iy = max(0, min(self._ny - 1, iy))

        return ix, iy

    def _grid_to_world(self, ix: int, iy: int) -> Tuple[float, float]:
        """
        격자 인덱스를 월드 좌표(셀 중심)로 변환합니다.

        Args:
            ix, iy: 격자 인덱스

        Returns:
            (x, y) 월드 좌표 (셀 중심)
        """
        x = self.min_corner[0] + (ix + 0.5) * self.resolution
        y = self.min_corner[1] + (iy + 0.5) * self.resolution
        return x, y

    def remove_material(self, start: np.ndarray, end: np.ndarray, tool: Tool):
        """
        공구가 두 점 사이를 이동하면서 재료를 제거합니다.
        공구 경로 아래의 Z-맵을 업데이트합니다.

        처리 방식:
        - 공구 경로 주위의 원통형 영역에서 재료 제거
        - 공구 반경 내의 모든 셀에 대해 Z 높이를 공구 끝점 Z로 업데이트

        Args:
            start: 이동 시작점 [X, Y, Z] (공구 끝 위치)
            end: 이동 끝점 [X, Y, Z]
            tool: 사용 중인 공구
        """
        radius = tool.radius

        # 이동 방향 벡터 (XY 평면)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dz = end[2] - start[2]
        dist_xy = np.sqrt(dx**2 + dy**2)

        # 영향 범위 계산 (공구 반경 + 여유 1셀)
        margin = radius + self.resolution

        # 경계 박스 계산
        x_min = min(start[0], end[0]) - margin
        x_max = max(start[0], end[0]) + margin
        y_min = min(start[1], end[1]) - margin
        y_max = max(start[1], end[1]) + margin

        # 격자 인덱스 범위 계산
        ix_min, iy_min = self._world_to_grid(x_min, y_min)
        ix_max, iy_max = self._world_to_grid(x_max, y_max)

        # 영향 범위 내의 모든 셀 처리
        for ix in range(ix_min, ix_max + 1):
            for iy in range(iy_min, iy_max + 1):
                # 셀 중심의 월드 좌표
                cx, cy = self._grid_to_world(ix, iy)

                # 이 셀에서의 공구 끝점 Z 높이 계산
                tool_z = self._get_tool_z_at(cx, cy, start, end, dist_xy, dz)

                if tool_z is None:
                    continue

                # 셀이 공구 반경 내에 있는지 확인
                dist_to_path = self._distance_to_segment_2d(cx, cy, start, end, dist_xy)

                if dist_to_path <= radius:
                    # 재료 제거: Z 높이를 공구 끝 높이로 낮춤
                    if tool_z < self.grid[ix, iy]:
                        self.grid[ix, iy] = tool_z

    def _get_tool_z_at(self, px: float, py: float,
                        start: np.ndarray, end: np.ndarray,
                        dist_xy: float, dz: float) -> Optional[float]:
        """
        주어진 XY 위치에서 공구 경로의 Z 높이를 계산합니다.

        Args:
            px, py: 확인할 XY 위치
            start, end: 공구 경로 시작/끝점
            dist_xy: XY 평면에서의 이동 거리
            dz: Z 방향 이동량

        Returns:
            해당 XY 위치에서의 공구 끝 Z 높이 (경로 범위 밖이면 None)
        """
        if dist_xy < 1e-6:
            # 순수 Z 이동 (수직 플런지)
            return min(start[2], end[2])

        # 경로 상의 가장 가까운 점의 t 파라미터 계산
        dx = end[0] - start[0]
        dy = end[1] - start[1]

        t = ((px - start[0]) * dx + (py - start[1]) * dy) / (dist_xy**2)
        t = max(0.0, min(1.0, t))

        # t에서의 Z 높이 계산 (선형 보간)
        z_at_t = start[2] + t * dz

        return z_at_t

    def _distance_to_segment_2d(self, px: float, py: float,
                                  start: np.ndarray, end: np.ndarray,
                                  dist: float) -> float:
        """
        2D 점에서 선분까지의 최단 거리를 계산합니다.

        Args:
            px, py: 점의 좌표
            start, end: 선분의 시작점과 끝점
            dist: 선분의 길이 (미리 계산)

        Returns:
            최단 거리 (mm)
        """
        if dist < 1e-6:
            # 점인 경우: 시작점까지의 거리
            return np.sqrt((px - start[0])**2 + (py - start[1])**2)

        dx = end[0] - start[0]
        dy = end[1] - start[1]

        # 점을 선분에 투영
        t = ((px - start[0]) * dx + (py - start[1]) * dy) / (dist**2)
        t = max(0.0, min(1.0, t))

        # 투영점에서의 거리
        proj_x = start[0] + t * dx
        proj_y = start[1] + t * dy

        return np.sqrt((px - proj_x)**2 + (py - proj_y)**2)

    def get_height_at(self, x: float, y: float) -> float:
        """
        주어진 XY 위치에서의 소재 높이를 반환합니다.

        Args:
            x, y: 조회할 XY 위치

        Returns:
            해당 위치의 Z 높이 (mm)
        """
        # 소재 범위 외부 처리
        if (x < self.min_corner[0] or x > self.max_corner[0] or
                y < self.min_corner[1] or y > self.max_corner[1]):
            return self.min_corner[2]  # 소재 밖은 최소 Z 반환

        ix, iy = self._world_to_grid(x, y)
        return float(self.grid[ix, iy])

    def to_mesh_data(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Z-맵을 3D 메시 데이터로 변환합니다.
        시각화에 사용됩니다.

        Returns:
            (vertices, faces) 튜플
            - vertices: N x 3 배열 [[x, y, z], ...]
            - faces: M x 3 배열 (삼각형 인덱스)
        """
        vertices = []
        faces = []

        # Z-맵의 각 격자점을 꼭짓점으로 변환
        for ix in range(self._nx):
            for iy in range(self._ny):
                x, y = self._grid_to_world(ix, iy)
                z = float(self.grid[ix, iy])
                vertices.append([x, y, z])

        # 인접한 4개의 꼭짓점으로 사각형(두 삼각형) 생성
        for ix in range(self._nx - 1):
            for iy in range(self._ny - 1):
                # 격자 꼭짓점 인덱스
                v00 = ix * self._ny + iy
                v01 = ix * self._ny + (iy + 1)
                v10 = (ix + 1) * self._ny + iy
                v11 = (ix + 1) * self._ny + (iy + 1)

                # 두 삼각형으로 분할
                faces.append([v00, v10, v11])
                faces.append([v00, v11, v01])

        if not vertices:
            return np.zeros((0, 3), dtype=float), np.zeros((0, 3), dtype=int)

        return np.array(vertices, dtype=float), np.array(faces, dtype=int)

    def get_stock_bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        소재의 현재 경계를 반환합니다.

        Returns:
            (min_corner, max_corner) 튜플
        """
        # 현재 Z-맵의 최솟값을 포함한 경계 계산
        current_max_z = float(np.max(self.grid))
        current_min_z = float(np.min(self.grid))

        min_corner = np.array([self.min_corner[0], self.min_corner[1], current_min_z])
        max_corner = np.array([self.max_corner[0], self.max_corner[1], current_max_z])

        return min_corner, max_corner

    def reset(self):
        """소재를 초기 상태(가공 전)로 되돌립니다."""
        self.grid.fill(self.max_corner[2])
        logger.debug("소재 모델 초기화됨")

    @property
    def grid_size(self) -> Tuple[int, int]:
        """격자 크기 (nx, ny)를 반환합니다."""
        return self._nx, self._ny
