"""
프로젝트(Project Service) 관리 모듈

YAML 프로젝트 파일을 로드/저장하고,
소재 설정은 min/max 방식과 origin/size 방식 모두 지원합니다.
"""
from __future__ import annotations

import os
from typing import Any, Dict

import numpy as np
import yaml

from app.models.machine import MachineDef, create_default_machine
from app.models.project import (
    ProjectConfig,
    compute_stock_bounds_from_origin,
    compute_stock_origin_from_bounds,
    normalize_stock_origin_mode,
)
from app.models.tool import Tool
from app.services.tool_library_service import ToolLibraryService
from app.utils.logger import get_logger

logger = get_logger("project_service")


class ProjectService:
    """프로젝트 파일 로드/저장을 담당하는 서비스 클래스"""

    def __init__(self):
        self._tool_library_service = ToolLibraryService()

    def load_project(self, filepath: str) -> ProjectConfig:
        """YAML 프로젝트 파일을 로드하여 ProjectConfig를 반환합니다."""

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"프로젝트 파일을 찾을 수 없습니다: {filepath}")

        logger.info("프로젝트 파일 로드: %s", filepath)

        config_data = self.load_yaml_config(filepath)
        project_dir = os.path.dirname(os.path.abspath(filepath))

        nc_file = config_data.get("nc_file", "")
        if nc_file and not os.path.isabs(nc_file):
            nc_file = os.path.join(project_dir, nc_file)

        machine_data = config_data.get("machine", {})
        if machine_data:
            machine = MachineDef.from_dict(machine_data)
        else:
            machine = create_default_machine()
            logger.warning("머신 설정이 없어 기본값을 사용합니다.")

        tools = self._load_project_tools(config_data, project_dir)

        stock_min, stock_max, stock_origin, stock_origin_mode, stock_resolution = (
            self._load_stock_config(config_data.get("stock", {}))
        )

        sim_options = config_data.get("simulation_options", {})

        config = ProjectConfig(
            nc_file_path=nc_file,
            machine_config=machine,
            tools=tools,
            stock_min=stock_min,
            stock_max=stock_max,
            stock_resolution=stock_resolution,
            stock_origin=stock_origin,
            stock_origin_mode=stock_origin_mode,
            simulation_options=sim_options,
            project_name=config_data.get("project_name", "로드된 프로젝트"),
            version=str(config_data.get("version", "1.0")),
            project_file_path=filepath,
            tool_library_file=str(config_data.get("tool_library_file", "")),
        )

        logger.info(
            "프로젝트 로드 완료: %s, 공구 %d개, NC 파일=%s",
            config.project_name,
            len(tools),
            nc_file,
        )
        return config

    def save_project(self, config: ProjectConfig, filepath: str):
        """ProjectConfig를 YAML 파일로 저장합니다."""

        logger.info("프로젝트 저장: %s", filepath)

        save_dir = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(save_dir, exist_ok=True)

        data = config.to_dict()

        with open(filepath, "w", encoding="utf-8") as file:
            yaml.dump(
                data,
                file,
                default_flow_style=False,
                allow_unicode=True,
                indent=2,
                sort_keys=False,
            )

        logger.info("프로젝트 저장 완료: %s", filepath)

    def load_yaml_config(self, filepath: str) -> Dict[str, Any]:
        """YAML 파일을 로드하여 딕셔너리로 반환합니다."""

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {filepath}")

        with open(filepath, "r", encoding="utf-8") as file:
            data = yaml.safe_load(file)

        return data if data else {}

    def load_machine_config(self, filepath: str) -> MachineDef:
        """머신 설정 YAML 파일을 로드합니다."""

        data = self.load_yaml_config(filepath)
        return MachineDef.from_dict(data)

    def load_tools_config(self, filepath: str) -> Dict[int, Tool]:
        """공구 라이브러리 YAML 파일을 로드합니다."""
        return self._tool_library_service.load_file(filepath)

    def load_default_configs(self, configs_dir: str = "configs") -> tuple:
        """기본 머신/공구/시뮬레이션 옵션을 로드합니다."""

        machine = create_default_machine()
        tools: Dict[int, Tool] = {}
        sim_options: Dict[str, Any] = {}

        machine_file = os.path.join(configs_dir, "default_machine.yaml")
        if os.path.exists(machine_file):
            try:
                machine = self.load_machine_config(machine_file)
                logger.info("기본 머신 설정 로드: %s", machine.name)
            except Exception as exc:
                logger.warning("기본 머신 설정 로드 실패: %s", exc)

        tools_file = os.path.join(configs_dir, "default_tools.yaml")
        if os.path.exists(tools_file):
            try:
                tools = self.load_tools_config(tools_file)
            except Exception as exc:
                logger.warning("기본 공구 설정 로드 실패: %s", exc)

        sim_file = os.path.join(configs_dir, "simulation_options.yaml")
        if os.path.exists(sim_file):
            try:
                sim_options = self.load_yaml_config(sim_file)
            except Exception as exc:
                logger.warning("시뮬레이션 옵션 로드 실패: %s", exc)

        return machine, tools, sim_options

    def _load_project_tools(
        self,
        config_data: Dict[str, Any],
        project_dir: str,
    ) -> list[Tool]:
        """프로젝트 외부 공구 라이브러리와 인라인 정의를 병합합니다."""

        libraries: list[Dict[int, Tool]] = []

        tool_library_file = config_data.get("tool_library_file")
        if tool_library_file:
            resolved = str(tool_library_file)
            if not os.path.isabs(resolved):
                resolved = os.path.normpath(os.path.join(project_dir, resolved))
            try:
                libraries.append(self._tool_library_service.load_file(resolved))
            except Exception as exc:
                logger.warning("프로젝트 공구 라이브러리 로드 실패: %s", exc)

        tool_library_payload = config_data.get("tool_library")
        if isinstance(tool_library_payload, dict):
            try:
                libraries.append(
                    self._tool_library_service.load_payload(
                        tool_library_payload,
                        base_dir=project_dir,
                        source="<project.tool_library>",
                    )
                )
            except Exception as exc:
                logger.warning("프로젝트 tool_library 파싱 실패: %s", exc)

        inline_tools = config_data.get("tools", [])
        if isinstance(inline_tools, list) and inline_tools:
            libraries.append(
                self._tool_library_service.load_entries(
                    inline_tools,
                    source="<project.tools>",
                )
            )

        merged = ToolLibraryService.merge_tools(*libraries)
        return list(merged.values())

    def _load_stock_config(
        self,
        stock_data: Dict[str, Any],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, str, float]:
        """
        stock 설정을 다양한 형식에서 읽어 공통 포맷으로 정규화합니다.

        지원 형식:
        1. min/max/resolution
        2. origin/size/origin_mode/resolution
        """

        stock_resolution = float(stock_data.get("resolution", 2.0))
        origin_mode = normalize_stock_origin_mode(stock_data.get("origin_mode", "top_center"))

        if "origin" in stock_data and "size" in stock_data:
            stock_origin = np.asarray(stock_data.get("origin"), dtype=float)
            stock_size = np.asarray(stock_data.get("size"), dtype=float)
            stock_min, stock_max = compute_stock_bounds_from_origin(
                stock_origin,
                stock_size,
                origin_mode,
            )
        else:
            stock_min = np.asarray(stock_data.get("min", [-60.0, -60.0, -30.0]), dtype=float)
            stock_max = np.asarray(stock_data.get("max", [60.0, 60.0, 0.0]), dtype=float)
            stock_origin = compute_stock_origin_from_bounds(stock_min, stock_max, origin_mode)

        return stock_min, stock_max, stock_origin, origin_mode, stock_resolution
