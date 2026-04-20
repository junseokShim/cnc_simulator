"""
프로젝트(Project) 데이터 모델 모듈

CNC 시뮬레이터 프로젝트의 전체 설정을 관리합니다.
특히 소재(스톡)는 기존 min/max 방식과 함께
원점(origin) + 크기(size) + 원점 기준(origin_mode) 방식도 지원합니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from app.models.machine import MachineDef, create_default_machine
from app.models.tool import Tool


STOCK_ORIGIN_MODES = {
    "top_center",
    "top_min_corner",
    "bottom_center",
    "bottom_min_corner",
    "center",
}


def normalize_stock_origin_mode(origin_mode: Optional[str]) -> str:
    """지원하지 않는 원점 기준이 들어오면 기본값으로 정규화합니다."""

    if origin_mode in STOCK_ORIGIN_MODES:
        return str(origin_mode)
    return "top_center"


def compute_stock_bounds_from_origin(
    origin: np.ndarray | List[float],
    size: np.ndarray | List[float],
    origin_mode: str = "top_center",
) -> tuple[np.ndarray, np.ndarray]:
    """
    원점 좌표와 소재 크기에서 stock min/max를 계산합니다.

    origin_mode 의미:
    - top_center: 원점이 소재 상면 중심
    - top_min_corner: 원점이 소재 상면 최소 코너(Xmin, Ymin, Zmax)
    - bottom_center: 원점이 소재 바닥 중심
    - bottom_min_corner: 원점이 소재 바닥 최소 코너(Xmin, Ymin, Zmin)
    - center: 원점이 소재 중심
    """

    origin_mode = normalize_stock_origin_mode(origin_mode)
    origin_arr = np.asarray(origin, dtype=float)
    size_arr = np.asarray(size, dtype=float)

    if origin_arr.shape != (3,) or size_arr.shape != (3,):
        raise ValueError("origin과 size는 [X, Y, Z] 3개 값이어야 합니다.")
    if np.any(size_arr <= 0.0):
        raise ValueError("소재 크기는 모든 축에서 0보다 커야 합니다.")

    half = size_arr / 2.0

    if origin_mode == "top_center":
        stock_min = np.array([origin_arr[0] - half[0], origin_arr[1] - half[1], origin_arr[2] - size_arr[2]])
        stock_max = np.array([origin_arr[0] + half[0], origin_arr[1] + half[1], origin_arr[2]])
    elif origin_mode == "top_min_corner":
        stock_min = np.array([origin_arr[0], origin_arr[1], origin_arr[2] - size_arr[2]])
        stock_max = np.array([origin_arr[0] + size_arr[0], origin_arr[1] + size_arr[1], origin_arr[2]])
    elif origin_mode == "bottom_center":
        stock_min = np.array([origin_arr[0] - half[0], origin_arr[1] - half[1], origin_arr[2]])
        stock_max = np.array([origin_arr[0] + half[0], origin_arr[1] + half[1], origin_arr[2] + size_arr[2]])
    elif origin_mode == "bottom_min_corner":
        stock_min = np.array([origin_arr[0], origin_arr[1], origin_arr[2]])
        stock_max = np.array([origin_arr[0] + size_arr[0], origin_arr[1] + size_arr[1], origin_arr[2] + size_arr[2]])
    else:  # center
        stock_min = origin_arr - half
        stock_max = origin_arr + half

    return stock_min.astype(float), stock_max.astype(float)


def compute_stock_origin_from_bounds(
    stock_min: np.ndarray | List[float],
    stock_max: np.ndarray | List[float],
    origin_mode: str = "top_center",
) -> np.ndarray:
    """stock min/max에서 origin_mode에 맞는 원점 좌표를 계산합니다."""

    origin_mode = normalize_stock_origin_mode(origin_mode)
    stock_min_arr = np.asarray(stock_min, dtype=float)
    stock_max_arr = np.asarray(stock_max, dtype=float)

    if stock_min_arr.shape != (3,) or stock_max_arr.shape != (3,):
        raise ValueError("stock_min과 stock_max는 [X, Y, Z] 3개 값이어야 합니다.")

    center_xy = (stock_min_arr[:2] + stock_max_arr[:2]) / 2.0
    center_xyz = (stock_min_arr + stock_max_arr) / 2.0

    if origin_mode == "top_center":
        return np.array([center_xy[0], center_xy[1], stock_max_arr[2]], dtype=float)
    if origin_mode == "top_min_corner":
        return np.array([stock_min_arr[0], stock_min_arr[1], stock_max_arr[2]], dtype=float)
    if origin_mode == "bottom_center":
        return np.array([center_xy[0], center_xy[1], stock_min_arr[2]], dtype=float)
    if origin_mode == "bottom_min_corner":
        return stock_min_arr.astype(float)
    return center_xyz.astype(float)


@dataclass
class ProjectConfig:
    """
    프로젝트 설정 데이터 클래스

    NC 파일, 기계/공구 설정, 소재 범위와 시뮬레이션 옵션을 함께 관리합니다.
    """

    nc_file_path: str
    machine_config: MachineDef
    tools: List[Tool]
    stock_min: np.ndarray
    stock_max: np.ndarray
    simulation_options: Dict = field(default_factory=dict)
    project_name: str = "새 프로젝트"
    version: str = "1.0"
    project_file_path: str = ""
    tool_library_file: str = ""
    stock_resolution: float = 2.0
    stock_origin_mode: str = "top_center"
    stock_origin: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 0.0], dtype=float))

    def __post_init__(self):
        self.stock_min = np.asarray(self.stock_min, dtype=float)
        self.stock_max = np.asarray(self.stock_max, dtype=float)
        self.stock_resolution = float(self.stock_resolution)
        self.stock_origin_mode = normalize_stock_origin_mode(self.stock_origin_mode)

        stock_origin_arr = np.asarray(self.stock_origin, dtype=float)
        if stock_origin_arr.shape != (3,):
            stock_origin_arr = compute_stock_origin_from_bounds(
                self.stock_min,
                self.stock_max,
                self.stock_origin_mode,
            )
        self.stock_origin = stock_origin_arr.astype(float)

    def get_tool_by_number(self, tool_number: int) -> Optional[Tool]:
        """공구 번호로 공구를 조회합니다."""

        for tool in self.tools:
            if tool.tool_number == tool_number:
                return tool
        return None

    def get_tools_dict(self) -> Dict[int, Tool]:
        """공구 번호를 키로 하는 사전을 반환합니다."""

        return {tool.tool_number: tool for tool in self.tools}

    def get_stock_size(self) -> np.ndarray:
        """소재 크기 [X, Y, Z]를 반환합니다."""

        return self.stock_max - self.stock_min

    def set_stock_bounds(
        self,
        stock_min: np.ndarray | List[float],
        stock_max: np.ndarray | List[float],
        origin_mode: Optional[str] = None,
    ):
        """stock min/max를 직접 지정하고 원점 좌표를 다시 계산합니다."""

        self.stock_min = np.asarray(stock_min, dtype=float)
        self.stock_max = np.asarray(stock_max, dtype=float)
        if origin_mode is not None:
            self.stock_origin_mode = normalize_stock_origin_mode(origin_mode)
        self.stock_origin = compute_stock_origin_from_bounds(
            self.stock_min,
            self.stock_max,
            self.stock_origin_mode,
        )

    def set_stock_from_origin(
        self,
        origin: np.ndarray | List[float],
        size: np.ndarray | List[float],
        origin_mode: Optional[str] = None,
    ):
        """원점 좌표와 소재 크기로 stock 범위를 다시 계산합니다."""

        if origin_mode is not None:
            self.stock_origin_mode = normalize_stock_origin_mode(origin_mode)
        self.stock_origin = np.asarray(origin, dtype=float)
        self.stock_min, self.stock_max = compute_stock_bounds_from_origin(
            self.stock_origin,
            size,
            self.stock_origin_mode,
        )

    def to_dict(self) -> dict:
        """ProjectConfig를 YAML 저장용 딕셔너리로 변환합니다."""

        return {
            "project_name": self.project_name,
            "version": self.version,
            "nc_file": self.nc_file_path,
            "machine": self.machine_config.to_dict(),
            "tool_library_file": self.tool_library_file,
            "tools": [tool.to_dict() for tool in self.tools],
            "stock": {
                "min": self.stock_min.tolist(),
                "max": self.stock_max.tolist(),
                "origin": self.stock_origin.tolist(),
                "size": self.get_stock_size().tolist(),
                "origin_mode": self.stock_origin_mode,
                "resolution": self.stock_resolution,
            },
            "simulation_options": self.simulation_options,
        }

    @classmethod
    def create_default(cls, nc_file_path: str = "") -> "ProjectConfig":
        """기본값으로 ProjectConfig를 생성합니다."""

        from app.models.tool import ToolType

        default_tools = [
            Tool(
                tool_number=1,
                name="플랫 엔드밀 Ø10",
                tool_type=ToolType.END_MILL,
                diameter=10.0,
                length=75.0,
                flute_length=25.0,
                corner_radius=0.0,
            ),
            Tool(
                tool_number=2,
                name="볼 엔드밀 Ø8",
                tool_type=ToolType.BALL_END,
                diameter=8.0,
                length=70.0,
                flute_length=20.0,
                corner_radius=4.0,
            ),
        ]

        stock_origin = np.array([0.0, 0.0, 0.0], dtype=float)
        stock_size = np.array([120.0, 120.0, 30.0], dtype=float)
        stock_origin_mode = "top_center"
        stock_min, stock_max = compute_stock_bounds_from_origin(
            stock_origin,
            stock_size,
            stock_origin_mode,
        )

        return cls(
            nc_file_path=nc_file_path,
            machine_config=create_default_machine(),
            tools=default_tools,
            tool_library_file="configs/default_tools.yaml",
            stock_min=stock_min,
            stock_max=stock_max,
            stock_resolution=2.0,
            stock_origin_mode=stock_origin_mode,
            stock_origin=stock_origin,
            simulation_options={
                "playback_speed": 1.0,
                "show_stock": True,
                "check_collisions": True,
            },
        )
