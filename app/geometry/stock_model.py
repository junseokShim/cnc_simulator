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

        # RGBA 이미지 캐시 (재료 제거가 있을 때만 재생성)
        self._rgba_dirty: bool = True
        self._rgba_cache: dict = {}  # mode -> np.ndarray

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
        # 새 복사본은 항상 dirty 상태로 시작 (캐시를 공유하지 않음)
        copied._rgba_dirty = True
        copied._rgba_cache = {}
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

    def _mark_rgba_dirty(self):
        """RGBA 이미지 캐시를 무효화합니다."""
        self._rgba_dirty = True
        self._rgba_cache.clear()

    def remove_material(self, start: np.ndarray, end: np.ndarray, tool: Tool,
                        segment_metrics: Optional[dict] = None):
        """
        공구가 두 점 사이를 이동하면서 재료를 제거합니다.

        [모델 가정]
        - 평면 XY로 투영한 공구 스윕 영역 안의 셀을 절삭 후보로 봅니다.
        - 해당 셀의 공구 끝점 Z보다 현재 스톡 높이가 높으면 재료가 존재한다고 판단합니다.
        - 재료가 더 제거되지 않더라도 절삭 스윕이 지나간 셀은 trace_intensity에 누적합니다.

        [성능 개선]
        Python 이중 루프를 numpy 벡터화 연산으로 교체하여 재생 중 지연을 제거합니다.

        Args:
            start: 이동 시작점 [X, Y, Z]
            end: 이동 끝점 [X, Y, Z]
            tool: 사용 중인 공구
            segment_metrics: 세그먼트 해석 결과 일부
                예) {"spindle_load_pct": 42.0, "chatter_risk_score": 0.32}
        """
        radius = tool.radius
        coverage_radius = radius + self.resolution * 0.5

        dx = float(end[0] - start[0])
        dy = float(end[1] - start[1])
        dz = float(end[2] - start[2])
        dist_xy = float(np.hypot(dx, dy))

        margin = coverage_radius + self.resolution
        x_min = min(start[0], end[0]) - margin
        x_max = max(start[0], end[0]) + margin
        y_min = min(start[1], end[1]) - margin
        y_max = max(start[1], end[1]) + margin

        ix_min, iy_min = self._world_to_grid(x_min, y_min)
        ix_max, iy_max = self._world_to_grid(x_max, y_max)

        if ix_min > ix_max or iy_min > iy_max:
            return

        load_pct = float(segment_metrics.get("spindle_load_pct", 0.0)) if segment_metrics else 0.0
        chatter_score = float(segment_metrics.get("chatter_risk_score", 0.0)) if segment_metrics else 0.0

        # ── numpy 벡터화: Python 이중 루프 제거 ──────────────────────────
        # 서브그리드 셀 중심 좌표 행렬 계산
        ix_arr = np.arange(ix_min, ix_max + 1, dtype=float)
        iy_arr = np.arange(iy_min, iy_max + 1, dtype=float)
        # CX, CY: shape (nx_sub, ny_sub) — 각 격자 셀의 월드 좌표
        CX = self.min_corner[0] + (ix_arr[:, np.newaxis] + 0.5) * self.resolution
        CY = self.min_corner[1] + (iy_arr[np.newaxis, :] + 0.5) * self.resolution

        nx_sub = len(ix_arr)
        ny_sub = len(iy_arr)

        if dist_xy >= 1e-6:
            # 각 셀에서 선분까지의 매개변수 t와 투영 거리 계산
            # CX: (nx_sub, 1), CY: (1, ny_sub) → 브로드캐스트 → (nx_sub, ny_sub)
            t_param = ((CX - start[0]) * dx + (CY - start[1]) * dy) / (dist_xy ** 2)
            t_param = np.clip(t_param, 0.0, 1.0)
            TOOL_Z = start[2] + t_param * dz          # (nx_sub, ny_sub)
            PROJ_X = start[0] + t_param * dx
            PROJ_Y = start[1] + t_param * dy
            DIST = np.hypot(CX - PROJ_X, CY - PROJ_Y)
        else:
            # 점/수직 이동: 거리는 점까지의 직선 거리
            # TOOL_Z를 (nx_sub, ny_sub) 크기로 명시적으로 생성
            TOOL_Z = np.full((nx_sub, ny_sub), min(float(start[2]), float(end[2])))
            DIST = np.hypot(CX - start[0], CY - start[1])  # 브로드캐스트 → (nx_sub, ny_sub)

        # 공구 반경 내 셀 마스크
        in_range = DIST <= coverage_radius
        if not np.any(in_range):
            return

        # ── 서브그리드 슬라이스 뷰(view) — in-place 수정으로 원본 배열 갱신 ──
        sg_grid    = self.grid[ix_min:ix_max + 1, iy_min:iy_max + 1]
        sg_removed = self.removed_depth_grid[ix_min:ix_max + 1, iy_min:iy_max + 1]
        sg_trace   = self.trace_intensity_grid[ix_min:ix_max + 1, iy_min:iy_max + 1]
        sg_pass    = self.pass_count_grid[ix_min:ix_max + 1, iy_min:iy_max + 1]
        sg_load    = self.load_map[ix_min:ix_max + 1, iy_min:iy_max + 1]
        sg_chatter = self.chatter_map[ix_min:ix_max + 1, iy_min:iy_max + 1]

        # 공구가 지나간 흔적은 절삭량과 무관하게 누적합니다.
        sg_pass[in_range] += 1
        sg_trace[in_range] = np.minimum(1.0, sg_trace[in_range] + 0.18)
        if load_pct > 0.0:
            sg_load[in_range] = np.maximum(sg_load[in_range], load_pct)
        if chatter_score > 0.0:
            sg_chatter[in_range] = np.maximum(sg_chatter[in_range], chatter_score * 100.0)

        # 재료 제거: 공구 Z보다 소재 높이가 높은 셀만 낮춥니다.
        removal_mask = in_range & (TOOL_Z < sg_grid)
        if np.any(removal_mask):
            sg_grid[removal_mask] = TOOL_Z[removal_mask]
            sg_removed[removal_mask] = np.maximum(
                sg_removed[removal_mask],
                self.initial_top_z - TOOL_Z[removal_mask],
            )

        # 변경이 있었으므로 RGBA 캐시 무효화
        self._mark_rgba_dirty()

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

    def has_material_removal(self, threshold: float = 0.01) -> bool:
        """
        실제로 제거된 재질이 있는지 빠르게 판별합니다.

        큰 소재에서 3D 메쉬를 매번 만들면 렌더링 비용이 커지므로,
        초기 상태처럼 제거 흔적이 없을 때는 메쉬 생성을 생략하는
        기준으로 사용합니다.
        """
        return bool(np.any(self.removed_depth_grid > threshold))

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

    def _expand_field(self, field: np.ndarray, radius_cells: int = 1) -> np.ndarray:
        """
        표시용 footprint를 약간 키우는 최대값 확장입니다.

        실제 제거 형상은 유지하고, 화면에 보이는 흔적만 살짝 넓혀서
        공구가 지나간 자리가 더 선명하게 보이도록 합니다.

        [성능 개선]
        반경 1 셀의 경우 numpy 슬라이싱을 사용하여 np.roll 호출 36번(임시 배열 생성)을
        8번의 in-place 최대값 연산으로 대체합니다.
        """
        radius_cells = max(0, int(radius_cells))
        if radius_cells == 0 or field.size == 0:
            return field.copy()

        if radius_cells == 1:
            # 빠른 경로: 8방향 이웃의 최대값을 numpy 슬라이싱으로 계산
            # (np.roll 없이 임시 배열 0개로 처리)
            result = field.copy()
            result[1:, :]    = np.maximum(result[1:, :],    field[:-1, :])    # 위 → 아래
            result[:-1, :]   = np.maximum(result[:-1, :],   field[1:, :])     # 아래 → 위
            result[:, 1:]    = np.maximum(result[:, 1:],    field[:, :-1])    # 왼 → 오른
            result[:, :-1]   = np.maximum(result[:, :-1],   field[:, 1:])     # 오른 → 왼
            result[1:, 1:]   = np.maximum(result[1:, 1:],   field[:-1, :-1])  # 대각 ↙
            result[1:, :-1]  = np.maximum(result[1:, :-1],  field[:-1, 1:])   # 대각 ↘
            result[:-1, 1:]  = np.maximum(result[:-1, 1:],  field[1:, :-1])   # 대각 ↖
            result[:-1, :-1] = np.maximum(result[:-1, :-1], field[1:, 1:])    # 대각 ↗
            return result

        # 반경 > 1 셀: 기존 np.roll 방식 유지
        expanded = field.copy()
        for dx in range(-radius_cells, radius_cells + 1):
            for dy in range(-radius_cells, radius_cells + 1):
                if dx == 0 and dy == 0:
                    continue
                shifted = np.roll(field, shift=(dx, dy), axis=(0, 1))
                if dx > 0:
                    shifted[:dx, :] = 0.0
                elif dx < 0:
                    shifted[dx:, :] = 0.0
                if dy > 0:
                    shifted[:, :dy] = 0.0
                elif dy < 0:
                    shifted[:, dy:] = 0.0
                expanded = np.maximum(expanded, shifted)
        return expanded

    def get_trace_image_rgba(self, mode: str = "footprint") -> np.ndarray:
        """
        뷰어 오버레이용 RGBA 이미지를 생성합니다.

        재료 제거가 없으면 캐시된 이미지를 반환합니다(재생 성능 개선).

        mode:
          - footprint: 제거 깊이/가공 흔적 기반
          - load: 최대 스핀들 부하 기반
          - chatter: 최대 채터 위험도 기반
        """
        # 변경이 없으면 캐시 반환
        if not self._rgba_dirty and mode in self._rgba_cache:
            return self._rgba_cache[mode]

        total_depth = max(1.0, self.initial_top_z - float(self.min_corner[2]))
        display_radius = 1 if self.resolution <= 3.0 else 2

        removed_display = self._expand_field(
            self.removed_depth_grid,
            radius_cells=display_radius,
        )
        trace_display = self._expand_field(
            self.trace_intensity_grid,
            radius_cells=display_radius,
        )
        load_display = self._expand_field(
            self.load_map,
            radius_cells=display_radius,
        )
        chatter_display = self._expand_field(
            self.chatter_map,
            radius_cells=display_radius,
        )

        removed_norm = np.clip(removed_display / total_depth, 0.0, 1.0)
        trace_norm = np.clip(
            np.maximum(removed_norm, np.minimum(1.0, trace_display)),
            0.0,
            1.0,
        )
        mask = (removed_display > 0.01) | (trace_display > 0.01)

        rgba = np.zeros((self._nx, self._ny, 4), dtype=np.ubyte)

        # 미가공 영역도 아주 옅게 깔아 주면 스톡 영역과 가공 영역의 대비가 좋아집니다.
        rgba[..., 0] = 166
        rgba[..., 1] = 138
        rgba[..., 2] = 102
        rgba[..., 3] = 18

        if mode == "load":
            value = np.clip(load_display / 100.0, 0.0, 1.0)
            red = (60 + value * 180).astype(np.ubyte)
            green = (180 - value * 120).astype(np.ubyte)
            blue = (170 - value * 140).astype(np.ubyte)
        elif mode == "chatter":
            value = np.clip(chatter_display / 100.0, 0.0, 1.0)
            red = (80 + value * 175).astype(np.ubyte)
            green = (170 - value * 120).astype(np.ubyte)
            blue = (200 - value * 170).astype(np.ubyte)
        else:
            # 기본 footprint 모드에서는 제거 깊이가 깊을수록 더 차갑고 진하게 보이도록
            # 색상을 줘서 Z 방향 절삭 깊이 차이가 시각적으로 남게 합니다.
            value = np.clip(np.maximum(trace_norm, removed_norm), 0.0, 1.0)
            red = (88 - removed_norm * 52).astype(np.ubyte)
            green = (124 + value * 82 - removed_norm * 24).astype(np.ubyte)
            blue = (136 + removed_norm * 118).astype(np.ubyte)

        alpha = (65 + value * 185).astype(np.ubyte)

        rgba[mask, 0] = red[mask]
        rgba[mask, 1] = green[mask]
        rgba[mask, 2] = blue[mask]
        rgba[mask, 3] = alpha[mask]

        # 결과를 캐시에 저장
        self._rgba_cache[mode] = rgba
        self._rgba_dirty = False
        return rgba

    def to_mesh_data(self, max_vertices: int = 30000) -> Tuple[np.ndarray, np.ndarray]:
        """
        Z-맵을 3D 메시 데이터로 변환합니다.

        [성능 개선]
        Python 이중 루프를 numpy 벡터화 연산으로 교체하였습니다.
        """
        if self._nx <= 0 or self._ny <= 0:
            return np.zeros((0, 3), dtype=float), np.zeros((0, 3), dtype=int)

        total_vertices = self._nx * self._ny
        stride = 1
        if max_vertices > 0 and total_vertices > max_vertices:
            stride = int(math.ceil(math.sqrt(total_vertices / float(max_vertices))))

        x_indices = np.arange(0, self._nx, stride, dtype=int)
        y_indices = np.arange(0, self._ny, stride, dtype=int)

        if x_indices[-1] != self._nx - 1:
            x_indices = np.append(x_indices, self._nx - 1)
        if y_indices[-1] != self._ny - 1:
            y_indices = np.append(y_indices, self._ny - 1)

        sample_grid = self.grid[np.ix_(x_indices, y_indices)]
        sample_nx = len(x_indices)
        sample_ny = len(y_indices)

        if sample_nx < 2 or sample_ny < 2:
            return np.zeros((0, 3), dtype=float), np.zeros((0, 3), dtype=int)

        # ── 벡터화: 정점 배열 생성 ─────────────────────────────────────────
        # 각 샘플 인덱스에 대응하는 월드 좌표 1D 배열
        X_1d = self.min_corner[0] + (x_indices + 0.5) * self.resolution
        Y_1d = self.min_corner[1] + (y_indices + 0.5) * self.resolution
        # meshgrid로 (sample_nx, sample_ny) 행렬 생성
        X, Y = np.meshgrid(X_1d, Y_1d, indexing='ij')
        # flatten to (n_vertices, 3)
        vertices = np.stack([X.ravel(), Y.ravel(), sample_grid.ravel()], axis=-1)

        # ── 벡터화: 면(삼각형) 인덱스 배열 생성 ──────────────────────────
        # 각 (i, j) 쌍에서 두 개의 삼각형 생성
        R, C = np.meshgrid(
            np.arange(sample_nx - 1, dtype=np.int32),
            np.arange(sample_ny - 1, dtype=np.int32),
            indexing='ij',
        )
        v00 = (R * sample_ny + C).ravel()
        v01 = (R * sample_ny + (C + 1)).ravel()
        v10 = ((R + 1) * sample_ny + C).ravel()
        v11 = ((R + 1) * sample_ny + (C + 1)).ravel()

        # 삼각형 1: [v00, v10, v11], 삼각형 2: [v00, v11, v01]
        faces = np.stack([
            np.concatenate([v00, v00]),
            np.concatenate([v10, v11]),
            np.concatenate([v11, v01]),
        ], axis=-1)

        return vertices, faces

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
        self._mark_rgba_dirty()
        logger.debug("소재 모델 초기화됨")

    @property
    def grid_size(self) -> Tuple[int, int]:
        """격자 크기 (nx, ny)를 반환합니다."""
        return self._nx, self._ny
