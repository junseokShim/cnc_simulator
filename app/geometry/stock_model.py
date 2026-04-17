"""
소재 모델(Stock Model) 모듈
Z-맵 기반으로 소재의 높이와 가공 흔적을 함께 관리합니다.

[핵심 역할]
1. 현재 소재 상면 높이(grid) 관리
2. 공구 스윕에 따른 재료 제거
3. 누적 가공 흔적/가공 횟수/부하·채터 맵 축적
4. 가공 전 상태를 기준으로 세그먼트의 ae/ap를 근사 추정
"""
from __future__ import annotations
import math
from typing import Tuple, Optional
import numpy as np

from app.models.tool import Tool
from app.utils.logger import get_logger

logger = get_logger("stock_model")


class StockModel:
    """
    Z-맵 기반 소재 모델 클래스

    소재를 2D 격자(그리드)로 표현합니다.
    각 셀은 해당 XY 위치에서의 현재 상면 Z 높이를 저장합니다.

    추가로 다음 보조 맵을 함께 유지합니다.
    - removed_depth_grid: 초기 상면 대비 제거 깊이
    - trace_intensity_grid: 공구가 지나간 흔적 강도
    - pass_count_grid: 절삭 스윕이 지나간 횟수
    - load_map/chatter_map: 해당 위치에서 관측된 최대 부하/채터
    """

    def __init__(self, min_corner: np.ndarray, max_corner: np.ndarray,
                 resolution: float = 1.0):
        """
        소재 모델을 초기화합니다.

        Args:
            min_corner: 소재 최소 모서리 [X, Y, Z]
            max_corner: 소재 최대 모서리 [X, Y, Z]
            resolution: 격자 셀 크기 (mm)
        """
        self.min_corner = np.array(min_corner, dtype=float)
        self.max_corner = np.array(max_corner, dtype=float)
        self.resolution = float(resolution)
        self.initial_top_z = float(self.max_corner[2])

        # 격자 크기 계산
        size = self.max_corner - self.min_corner
        self._nx = max(1, int(np.ceil(size[0] / resolution)))
        self._ny = max(1, int(np.ceil(size[1] / resolution)))

        # Z-맵: 현재 소재의 상면 높이
        self.grid = np.full((self._nx, self._ny), self.initial_top_z, dtype=float)

        # 누적 가공 흔적과 공정 메타데이터 맵
        self.removed_depth_grid = np.zeros((self._nx, self._ny), dtype=float)
        self.trace_intensity_grid = np.zeros((self._nx, self._ny), dtype=float)
        self.pass_count_grid = np.zeros((self._nx, self._ny), dtype=np.int32)
        self.load_map = np.zeros((self._nx, self._ny), dtype=float)
        self.chatter_map = np.zeros((self._nx, self._ny), dtype=float)

        logger.debug(
            f"소재 모델 생성: {self._nx}x{self._ny} 격자, "
            f"해상도 {resolution}mm, "
            f"범위 {min_corner} ~ {max_corner}"
        )

    def copy(self) -> "StockModel":
        """
        소재 모델을 깊은 복사합니다.

        가공 해석용 임시 스톡과 재생용 스톡을 분리하기 위해 사용합니다.
        """
        copied = StockModel(self.min_corner.copy(), self.max_corner.copy(), self.resolution)
        copied.grid = self.grid.copy()
        copied.removed_depth_grid = self.removed_depth_grid.copy()
        copied.trace_intensity_grid = self.trace_intensity_grid.copy()
        copied.pass_count_grid = self.pass_count_grid.copy()
        copied.load_map = self.load_map.copy()
        copied.chatter_map = self.chatter_map.copy()
        return copied

    def _world_to_grid(self, x: float, y: float) -> Tuple[int, int]:
        """
        월드 좌표를 격자 인덱스로 변환합니다.

        Args:
            x, y: 월드 좌표

        Returns:
            (ix, iy) 격자 인덱스
        """
        ix = int((x - self.min_corner[0]) / self.resolution)
        iy = int((y - self.min_corner[1]) / self.resolution)

        ix = max(0, min(self._nx - 1, ix))
        iy = max(0, min(self._ny - 1, iy))
        return ix, iy

    def _grid_to_world(self, ix: int, iy: int) -> Tuple[float, float]:
        """
        격자 인덱스를 월드 좌표(셀 중심)로 변환합니다.
        """
        x = self.min_corner[0] + (ix + 0.5) * self.resolution
        y = self.min_corner[1] + (iy + 0.5) * self.resolution
        return x, y

    def remove_material(self, start: np.ndarray, end: np.ndarray, tool: Tool,
                        segment_metrics: Optional[dict] = None):
        """
        공구가 두 점 사이를 이동하면서 재료를 제거합니다.

        [모델 가정]
        - 평면 XY로 투영한 공구 스윕 영역 안의 셀을 절삭 후보로 봅니다.
        - 해당 셀의 공구 끝점 Z보다 현재 스톡 높이가 높으면 재료가 존재한다고 판단합니다.
        - 재료가 더 제거되지 않더라도 절삭 스윕이 지나간 셀은 trace_intensity에 누적합니다.

        Args:
            start: 이동 시작점 [X, Y, Z]
            end: 이동 끝점 [X, Y, Z]
            tool: 사용 중인 공구
            segment_metrics: 세그먼트 해석 결과 일부
                예) {"spindle_load_pct": 42.0, "chatter_risk_score": 0.32}
        """
        radius = tool.radius
        coverage_radius = radius + self.resolution * 0.5

        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dz = end[2] - start[2]
        dist_xy = float(np.hypot(dx, dy))

        margin = coverage_radius + self.resolution
        x_min = min(start[0], end[0]) - margin
        x_max = max(start[0], end[0]) + margin
        y_min = min(start[1], end[1]) - margin
        y_max = max(start[1], end[1]) + margin

        ix_min, iy_min = self._world_to_grid(x_min, y_min)
        ix_max, iy_max = self._world_to_grid(x_max, y_max)

        load_pct = float(segment_metrics.get("spindle_load_pct", 0.0)) if segment_metrics else 0.0
        chatter_score = float(segment_metrics.get("chatter_risk_score", 0.0)) if segment_metrics else 0.0

        for ix in range(ix_min, ix_max + 1):
            for iy in range(iy_min, iy_max + 1):
                cx, cy = self._grid_to_world(ix, iy)
                tool_z = self._get_tool_z_at(cx, cy, start, end, dist_xy, dz)
                if tool_z is None:
                    continue

                dist_to_path = self._distance_to_segment_2d(cx, cy, start, end, dist_xy)
                if dist_to_path > coverage_radius:
                    continue

                # 공구가 지나간 흔적은 절삭량과 무관하게 누적합니다.
                self.pass_count_grid[ix, iy] += 1
                self.trace_intensity_grid[ix, iy] = min(
                    1.0,
                    self.trace_intensity_grid[ix, iy] + 0.18
                )
                self.load_map[ix, iy] = max(self.load_map[ix, iy], load_pct)
                self.chatter_map[ix, iy] = max(self.chatter_map[ix, iy], chatter_score * 100.0)

                if tool_z < self.grid[ix, iy]:
                    self.grid[ix, iy] = tool_z
                    self.removed_depth_grid[ix, iy] = max(
                        self.removed_depth_grid[ix, iy],
                        self.initial_top_z - tool_z
                    )

    def estimate_segment_engagement(self, start: np.ndarray, end: np.ndarray,
                                    tool: Tool, sample_count: int = 7) -> dict:
        """
        현재 스톡 형상을 기준으로 세그먼트의 실제 ae/ap를 근사 추정합니다.

        [근사 방식]
        - 세그먼트 길이를 따라 여러 샘플 위치를 잡습니다.
        - 각 샘플에서 공구 반경 내 격자 셀 중 아직 제거되지 않은 재료를 찾습니다.
        - 남아 있는 재료 높이와 공구 Z의 차이로 ap를,
          진행 방향 법선 방향으로 남아 있는 재료 폭을 ae로 근사합니다.

        Returns:
            {
              "ae": 반경방향 맞물림(mm),
              "ap": 축방향 절입(mm),
              "engagement_ratio": 접촉 비율(0~1),
              "engaged_samples": 유효 샘플 수,
            }
        """
        radius = max(tool.radius, self.resolution * 0.5)
        diameter = max(tool.diameter, self.resolution)
        flute_length = max(tool.flute_length, diameter * 0.5)

        dx = float(end[0] - start[0])
        dy = float(end[1] - start[1])
        dz = float(end[2] - start[2])
        dist_xy = float(np.hypot(dx, dy))
        seg_len = max(float(np.linalg.norm(end - start)), 0.0)

        if seg_len < 1e-9:
            return {"ae": 0.0, "ap": 0.0, "engagement_ratio": 0.0, "engaged_samples": 0}

        if dist_xy > 1e-9:
            tangent = np.array([dx, dy], dtype=float) / dist_xy
            normal = np.array([-tangent[1], tangent[0]], dtype=float)
        else:
            tangent = None
            normal = np.array([1.0, 0.0], dtype=float)

        sample_count = max(3, int(sample_count))
        if dist_xy > 0.0:
            sample_count = max(sample_count, min(21, int(math.ceil(dist_xy / max(self.resolution * 2.0, 1.0))) + 1))

        sample_ae = []
        sample_ap = []
        sample_area_ratio = []

        for t in np.linspace(0.0, 1.0, sample_count):
            center = start + (end - start) * float(t)
            bbox_min = center[:2] - (radius + self.resolution)
            bbox_max = center[:2] + (radius + self.resolution)
            ix_min, iy_min = self._world_to_grid(bbox_min[0], bbox_min[1])
            ix_max, iy_max = self._world_to_grid(bbox_max[0], bbox_max[1])

            engaged_aps = []
            normal_coords = []
            engaged_cell_area = 0.0

            for ix in range(ix_min, ix_max + 1):
                for iy in range(iy_min, iy_max + 1):
                    cx, cy = self._grid_to_world(ix, iy)
                    rel = np.array([cx - center[0], cy - center[1]], dtype=float)
                    radial_dist = float(np.linalg.norm(rel))
                    if radial_dist > radius:
                        continue

                    stock_z = self.grid[ix, iy]
                    local_ap = min(flute_length, max(0.0, stock_z - center[2]))
                    if local_ap <= 1e-4:
                        continue

                    engaged_aps.append(local_ap)
                    engaged_cell_area += self.resolution ** 2

                    if tangent is not None:
                        normal_coords.append(float(np.dot(rel, normal)))
                    else:
                        normal_coords.append(radial_dist)

            if not engaged_aps:
                continue

            sample_ap.append(float(np.percentile(engaged_aps, 70)))

            if dist_xy > 1e-9:
                width = (max(normal_coords) - min(normal_coords)) + self.resolution
                ae = min(diameter, max(self.resolution, width))
            else:
                ae = min(diameter, max(self.resolution, 2.0 * max(normal_coords)))

            cross_section_area = math.pi * (radius ** 2)
            area_ratio = min(1.0, engaged_cell_area / max(cross_section_area, 1e-6))

            sample_ae.append(float(ae))
            sample_area_ratio.append(float(area_ratio))

        if not sample_ap:
            return {"ae": 0.0, "ap": 0.0, "engagement_ratio": 0.0, "engaged_samples": 0}

        return {
            "ae": float(np.mean(sample_ae)),
            "ap": float(np.mean(sample_ap)),
            "engagement_ratio": float(np.mean(sample_area_ratio)),
            "engaged_samples": len(sample_ap),
        }

    def _get_tool_z_at(self, px: float, py: float,
                       start: np.ndarray, end: np.ndarray,
                       dist_xy: float, dz: float) -> Optional[float]:
        """
        주어진 XY 위치에서 공구 경로의 Z 높이를 계산합니다.
        """
        if dist_xy < 1e-6:
            return min(start[2], end[2])

        dx = end[0] - start[0]
        dy = end[1] - start[1]

        t = ((px - start[0]) * dx + (py - start[1]) * dy) / (dist_xy ** 2)
        t = max(0.0, min(1.0, t))
        return float(start[2] + t * dz)

    def _distance_to_segment_2d(self, px: float, py: float,
                                start: np.ndarray, end: np.ndarray,
                                dist: float) -> float:
        """
        2D 점에서 선분까지의 최단 거리를 계산합니다.
        """
        if dist < 1e-6:
            return float(np.hypot(px - start[0], py - start[1]))

        dx = end[0] - start[0]
        dy = end[1] - start[1]
        t = ((px - start[0]) * dx + (py - start[1]) * dy) / (dist ** 2)
        t = max(0.0, min(1.0, t))
        proj_x = start[0] + t * dx
        proj_y = start[1] + t * dy
        return float(np.hypot(px - proj_x, py - proj_y))

    def get_height_at(self, x: float, y: float) -> float:
        """
        주어진 XY 위치에서의 소재 높이를 반환합니다.
        """
        if (x < self.min_corner[0] or x > self.max_corner[0] or
                y < self.min_corner[1] or y > self.max_corner[1]):
            return float(self.min_corner[2])

        ix, iy = self._world_to_grid(x, y)
        return float(self.grid[ix, iy])

    def get_removed_depth_map(self) -> np.ndarray:
        """초기 상면 기준 제거 깊이 맵을 반환합니다."""
        return self.removed_depth_grid.copy()

    def get_surface_grid(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """현재 스톡 상면의 X/Y 격자 중심 좌표와 Z-grid를 반환합니다."""
        x_coords = self.min_corner[0] + (np.arange(self._nx) + 0.5) * self.resolution
        y_coords = self.min_corner[1] + (np.arange(self._ny) + 0.5) * self.resolution
        return x_coords.astype(float), y_coords.astype(float), self.grid.copy()

    def get_machined_mask(self, threshold: float = 0.01) -> np.ndarray:
        """
        누적 가공 흔적 마스크를 반환합니다.

        제거 깊이가 거의 없어도 trace_intensity가 있으면 이미 공구가 지나간 영역으로 봅니다.
        """
        return (
            (self.removed_depth_grid > threshold) |
            (self.trace_intensity_grid > threshold)
        )

    def get_trace_image_rgba(self, mode: str = "footprint") -> np.ndarray:
        """
        뷰어 오버레이용 RGBA 이미지를 생성합니다.

        mode:
          - footprint: 제거 깊이/가공 흔적 기반
          - load: 최대 스핀들 부하 기반
          - chatter: 최대 채터 위험도 기반
        """
        total_depth = max(1.0, self.initial_top_z - float(self.min_corner[2]))
        removed_norm = np.clip(self.removed_depth_grid / total_depth, 0.0, 1.0)
        trace_norm = np.clip(
            np.maximum(removed_norm, np.minimum(1.0, self.trace_intensity_grid)),
            0.0, 1.0
        )
        mask = self.get_machined_mask()

        rgba = np.zeros((self._nx, self._ny, 4), dtype=np.ubyte)

        # 미가공 영역도 아주 옅게 깔아 주면 스톡 영역과 가공 영역의 대비가 좋아집니다.
        rgba[..., 0] = 166
        rgba[..., 1] = 138
        rgba[..., 2] = 102
        rgba[..., 3] = 26

        if mode == "load":
            value = np.clip(self.load_map / 100.0, 0.0, 1.0)
            red = (60 + value * 180).astype(np.ubyte)
            green = (180 - value * 120).astype(np.ubyte)
            blue = (170 - value * 140).astype(np.ubyte)
        elif mode == "chatter":
            value = np.clip(self.chatter_map / 100.0, 0.0, 1.0)
            red = (80 + value * 175).astype(np.ubyte)
            green = (170 - value * 120).astype(np.ubyte)
            blue = (200 - value * 170).astype(np.ubyte)
        else:
            # 기본 footprint 모드에서는 제거 깊이가 깊을수록 더 차갑고 진하게 보이도록
            # 색상을 줘서 Z 방향 절삭 깊이 차이가 시각적으로 남게 합니다.
            value = np.clip(np.maximum(trace_norm, removed_norm), 0.0, 1.0)
            red = (85 - removed_norm * 45).astype(np.ubyte)
            green = (120 + value * 70 - removed_norm * 18).astype(np.ubyte)
            blue = (135 + removed_norm * 115).astype(np.ubyte)

        alpha = (40 + value * 170).astype(np.ubyte)

        rgba[mask, 0] = red[mask]
        rgba[mask, 1] = green[mask]
        rgba[mask, 2] = blue[mask]
        rgba[mask, 3] = alpha[mask]

        return rgba

    def to_mesh_data(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Z-맵을 3D 메시 데이터로 변환합니다.
        """
        vertices = []
        faces = []

        for ix in range(self._nx):
            for iy in range(self._ny):
                x, y = self._grid_to_world(ix, iy)
                z = float(self.grid[ix, iy])
                vertices.append([x, y, z])

        for ix in range(self._nx - 1):
            for iy in range(self._ny - 1):
                v00 = ix * self._ny + iy
                v01 = ix * self._ny + (iy + 1)
                v10 = (ix + 1) * self._ny + iy
                v11 = (ix + 1) * self._ny + (iy + 1)

                faces.append([v00, v10, v11])
                faces.append([v00, v11, v01])

        if not vertices:
            return np.zeros((0, 3), dtype=float), np.zeros((0, 3), dtype=int)

        return np.array(vertices, dtype=float), np.array(faces, dtype=int)

    def get_stock_bounds(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        소재의 현재 경계를 반환합니다.
        """
        current_max_z = float(np.max(self.grid))
        current_min_z = float(np.min(self.grid))

        min_corner = np.array([self.min_corner[0], self.min_corner[1], current_min_z])
        max_corner = np.array([self.max_corner[0], self.max_corner[1], current_max_z])
        return min_corner, max_corner

    def reset(self):
        """소재와 누적 흔적을 모두 초기 상태로 되돌립니다."""
        self.grid.fill(self.initial_top_z)
        self.removed_depth_grid.fill(0.0)
        self.trace_intensity_grid.fill(0.0)
        self.pass_count_grid.fill(0)
        self.load_map.fill(0.0)
        self.chatter_map.fill(0.0)
        logger.debug("소재 모델 초기화됨")

    @property
    def grid_size(self) -> Tuple[int, int]:
        """격자 크기 (nx, ny)를 반환합니다."""
        return self._nx, self._ny
