"""
프로젝트(Project) 데이터 모델 모듈
CNC 시뮬레이션 프로젝트의 전체 설정을 관리하는 데이터 구조를 정의합니다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import numpy as np

from app.models.tool import Tool
from app.models.machine import MachineDef, create_default_machine


@dataclass
class ProjectConfig:
    """
    프로젝트 설정 데이터 클래스
    NC 파일, 머신 설정, 공구 목록, 소재 정보 등 프로젝트의 모든 설정을 저장합니다.
    """
    # NC 파일 경로 (절대 경로 또는 프로젝트 파일 기준 상대 경로)
    nc_file_path: str

    # 머신 정의 (MachineDef 인스턴스)
    machine_config: MachineDef

    # 공구 목록
    tools: List[Tool]

    # 소재(스톡) 최소 모서리 [X, Y, Z] (mm)
    stock_min: np.ndarray

    # 소재(스톡) 최대 모서리 [X, Y, Z] (mm)
    stock_max: np.ndarray

    # 시뮬레이션 옵션 딕셔너리
    simulation_options: Dict = field(default_factory=dict)

    # 프로젝트 이름
    project_name: str = "새 프로젝트"

    # 프로젝트 버전
    version: str = "1.0"

    # 프로젝트 파일 경로 (저장된 경우)
    project_file_path: str = ""

    # Z-맵 해상도 (mm/셀)
    stock_resolution: float = 2.0

    def get_tool_by_number(self, tool_number: int) -> Optional[Tool]:
        """
        공구 번호로 공구 정보를 조회합니다.

        Args:
            tool_number: 조회할 공구 번호

        Returns:
            해당 번호의 Tool 인스턴스 또는 None
        """
        for tool in self.tools:
            if tool.tool_number == tool_number:
                return tool
        return None

    def get_tools_dict(self) -> Dict[int, Tool]:
        """공구 번호를 키로 하는 딕셔너리를 반환합니다."""
        return {tool.tool_number: tool for tool in self.tools}

    def get_stock_size(self) -> np.ndarray:
        """소재 크기 [가로, 세로, 높이]를 반환합니다."""
        return self.stock_max - self.stock_min

    def to_dict(self) -> dict:
        """ProjectConfig를 딕셔너리로 변환합니다. YAML 저장에 사용됩니다."""
        return {
            "project_name": self.project_name,
            "version": self.version,
            "nc_file": self.nc_file_path,
            "machine": self.machine_config.to_dict(),
            "tools": [tool.to_dict() for tool in self.tools],
            "stock": {
                "min": self.stock_min.tolist(),
                "max": self.stock_max.tolist(),
                "resolution": self.stock_resolution,
            },
            "simulation_options": self.simulation_options,
        }

    @classmethod
    def create_default(cls, nc_file_path: str = "") -> 'ProjectConfig':
        """
        기본값으로 ProjectConfig를 생성합니다.
        새 프로젝트 시작 시 사용됩니다.
        """
        from app.models.tool import ToolType

        # 기본 공구 목록
        default_tools = [
            Tool(
                tool_number=1,
                name="플랫 엔드밀 φ10",
                tool_type=ToolType.END_MILL,
                diameter=10.0,
                length=75.0,
                flute_length=25.0,
                corner_radius=0.0
            ),
            Tool(
                tool_number=2,
                name="볼 엔드밀 φ8",
                tool_type=ToolType.BALL_END,
                diameter=8.0,
                length=70.0,
                flute_length=20.0,
                corner_radius=4.0
            ),
        ]

        return cls(
            nc_file_path=nc_file_path,
            machine_config=create_default_machine(),
            tools=default_tools,
            stock_min=np.array([-60.0, -60.0, -30.0]),
            stock_max=np.array([60.0, 60.0, 0.0]),
            stock_resolution=2.0,
            simulation_options={
                "playback_speed": 1.0,
                "show_stock": True,
                "check_collisions": True,
            }
        )
