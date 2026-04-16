"""
프로젝트 서비스(Project Service) 모듈
CNC 시뮬레이터 프로젝트 파일의 로드/저장을 담당합니다.
YAML 형식의 프로젝트 파일을 지원합니다.
"""
from __future__ import annotations
import os
from typing import Dict, Any, Optional
import yaml
import numpy as np

from app.models.project import ProjectConfig
from app.models.machine import MachineDef, MachineAxis, create_default_machine
from app.models.tool import Tool, ToolType
from app.utils.logger import get_logger

logger = get_logger("project_service")


class ProjectService:
    """
    프로젝트 파일 관리 서비스 클래스

    YAML 형식의 프로젝트 파일을 읽고 쓰는 기능을 제공합니다.
    머신 설정, 공구 라이브러리, 소재 정보를 관리합니다.
    """

    def load_project(self, filepath: str) -> ProjectConfig:
        """
        YAML 프로젝트 파일을 로드하여 ProjectConfig를 반환합니다.

        Args:
            filepath: 프로젝트 파일 경로 (.yaml)

        Returns:
            로드된 ProjectConfig 인스턴스

        Raises:
            FileNotFoundError: 파일이 없을 때
            yaml.YAMLError: YAML 형식 오류
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"프로젝트 파일을 찾을 수 없습니다: {filepath}")

        logger.info(f"프로젝트 파일 로드: {filepath}")

        config_data = self.load_yaml_config(filepath)
        project_dir = os.path.dirname(os.path.abspath(filepath))

        # NC 파일 경로 처리 (상대/절대 경로 모두 지원)
        nc_file = config_data.get("nc_file", "")
        if nc_file and not os.path.isabs(nc_file):
            nc_file = os.path.join(project_dir, nc_file)

        # 머신 설정 로드
        machine_data = config_data.get("machine", {})
        if machine_data:
            machine = MachineDef.from_dict(machine_data)
        else:
            # 기본 머신 설정 사용
            machine = create_default_machine()
            logger.warning("머신 설정이 없어 기본값을 사용합니다")

        # 공구 목록 로드
        tools = []
        for tool_data in config_data.get("tools", []):
            try:
                tool = Tool.from_dict(tool_data)
                tools.append(tool)
            except Exception as e:
                logger.warning(f"공구 로드 실패: {e}")

        # 소재 설정 로드
        stock_data = config_data.get("stock", {})
        stock_min_list = stock_data.get("min", [-60.0, -60.0, -30.0])
        stock_max_list = stock_data.get("max", [60.0, 60.0, 0.0])
        stock_resolution = float(stock_data.get("resolution", 2.0))

        stock_min = np.array(stock_min_list, dtype=float)
        stock_max = np.array(stock_max_list, dtype=float)

        # 시뮬레이션 옵션 로드
        sim_options = config_data.get("simulation_options", {})

        config = ProjectConfig(
            nc_file_path=nc_file,
            machine_config=machine,
            tools=tools,
            stock_min=stock_min,
            stock_max=stock_max,
            stock_resolution=stock_resolution,
            simulation_options=sim_options,
            project_name=config_data.get("project_name", "로드된 프로젝트"),
            version=str(config_data.get("version", "1.0")),
            project_file_path=filepath
        )

        logger.info(f"프로젝트 로드 완료: {config.project_name}, "
                    f"공구 {len(tools)}개, NC파일: {nc_file}")

        return config

    def save_project(self, config: ProjectConfig, filepath: str):
        """
        ProjectConfig를 YAML 파일로 저장합니다.

        Args:
            config: 저장할 ProjectConfig
            filepath: 저장할 파일 경로

        Raises:
            IOError: 파일 쓰기 실패 시
        """
        logger.info(f"프로젝트 저장: {filepath}")

        # 저장 디렉토리 생성
        save_dir = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(save_dir, exist_ok=True)

        # 데이터 변환
        data = config.to_dict()

        # YAML 저장
        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False,
                     allow_unicode=True, indent=2,
                     sort_keys=False)

        logger.info(f"프로젝트 저장 완료: {filepath}")

    def load_yaml_config(self, filepath: str) -> Dict[str, Any]:
        """
        YAML 파일을 로드하여 딕셔너리로 반환합니다.

        Args:
            filepath: YAML 파일 경로

        Returns:
            파싱된 딕셔너리

        Raises:
            FileNotFoundError: 파일이 없을 때
            yaml.YAMLError: YAML 형식 오류
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        return data if data else {}

    def load_machine_config(self, filepath: str) -> MachineDef:
        """
        머신 설정 YAML 파일을 로드합니다.

        Args:
            filepath: 머신 설정 파일 경로

        Returns:
            MachineDef 인스턴스
        """
        data = self.load_yaml_config(filepath)
        return MachineDef.from_dict(data)

    def load_tools_config(self, filepath: str) -> Dict[int, Tool]:
        """
        공구 라이브러리 YAML 파일을 로드합니다.

        Args:
            filepath: 공구 설정 파일 경로

        Returns:
            공구 번호 → Tool 매핑 딕셔너리
        """
        data = self.load_yaml_config(filepath)
        tools = {}

        for tool_data in data.get("tools", []):
            try:
                tool = Tool.from_dict(tool_data)
                tools[tool.tool_number] = tool
            except Exception as e:
                logger.warning(f"공구 로드 실패: {e}")

        logger.info(f"공구 {len(tools)}개 로드 완료")
        return tools

    def load_default_configs(self, configs_dir: str = "configs") -> tuple:
        """
        기본 설정 파일들을 로드합니다.
        configs 디렉토리의 기본 설정 파일을 사용합니다.

        Args:
            configs_dir: 설정 파일 디렉토리 경로

        Returns:
            (MachineDef, Dict[int, Tool], dict) 튜플
        """
        machine = create_default_machine()
        tools = {}
        sim_options = {}

        machine_file = os.path.join(configs_dir, "default_machine.yaml")
        if os.path.exists(machine_file):
            try:
                machine = self.load_machine_config(machine_file)
                logger.info(f"기본 머신 설정 로드: {machine.name}")
            except Exception as e:
                logger.warning(f"기본 머신 설정 로드 실패: {e}")

        tools_file = os.path.join(configs_dir, "default_tools.yaml")
        if os.path.exists(tools_file):
            try:
                tools = self.load_tools_config(tools_file)
            except Exception as e:
                logger.warning(f"기본 공구 설정 로드 실패: {e}")

        sim_file = os.path.join(configs_dir, "simulation_options.yaml")
        if os.path.exists(sim_file):
            try:
                sim_options = self.load_yaml_config(sim_file)
            except Exception as e:
                logger.warning(f"시뮬레이션 옵션 로드 실패: {e}")

        return machine, tools, sim_options
