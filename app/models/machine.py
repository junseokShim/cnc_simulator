"""
머신(Machine) 데이터 모델 모듈
CNC 공작기계의 사양과 축 이동 범위를 정의합니다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class MachineAxis:
    """
    머신 축 데이터 클래스
    단일 축의 이름과 이동 범위를 저장합니다.
    """
    # 축 이름 (X, Y, Z, A, B, C 등)
    name: str

    # 최소 이동 한계 (mm 또는 도)
    min_travel: float

    # 최대 이동 한계 (mm 또는 도)
    max_travel: float

    @property
    def travel_range(self) -> float:
        """축의 전체 이동 범위를 반환합니다."""
        return self.max_travel - self.min_travel

    def is_within_limits(self, position: float) -> bool:
        """
        주어진 위치가 축 이동 범위 내에 있는지 확인합니다.

        Args:
            position: 확인할 위치값

        Returns:
            범위 내에 있으면 True
        """
        return self.min_travel <= position <= self.max_travel


@dataclass
class MachineDef:
    """
    머신 정의 데이터 클래스
    CNC 공작기계의 전체 사양을 저장합니다.
    """
    # 머신 이름 (예: "3축 수직 머시닝 센터")
    name: str

    # 축 정의 딕셔너리 (축 이름 → MachineAxis)
    axes: Dict[str, MachineAxis]

    # 주축 최대 회전수 (RPM)
    max_spindle_rpm: float

    # 최대 이송 속도 (mm/min)
    max_feedrate: float

    # 급속 이동 속도 (mm/min, G0 이동 시 사용)
    rapid_feedrate: float

    # 머신 제조사 (선택적)
    manufacturer: str = ""

    # 머신 모델명 (선택적)
    model: str = ""

    def check_position(self, x: float, y: float, z: float) -> list:
        """
        주어진 위치가 머신 이동 범위 내에 있는지 확인합니다.

        Args:
            x, y, z: 확인할 위치 좌표

        Returns:
            범위를 벗어난 축 이름 목록 (빈 리스트면 정상)
        """
        out_of_bounds = []
        positions = {'X': x, 'Y': y, 'Z': z}

        for axis_name, pos in positions.items():
            if axis_name in self.axes:
                axis = self.axes[axis_name]
                if not axis.is_within_limits(pos):
                    out_of_bounds.append(axis_name)

        return out_of_bounds

    def get_axis(self, name: str) -> Optional[MachineAxis]:
        """이름으로 축 정보를 반환합니다."""
        return self.axes.get(name.upper())

    @classmethod
    def from_dict(cls, data: dict) -> 'MachineDef':
        """
        딕셔너리에서 MachineDef 인스턴스를 생성합니다.
        YAML 설정 파일 로딩에 사용됩니다.
        """
        # 축 정보 파싱
        axes = {}
        for axis_name, axis_data in data.get("axes", {}).items():
            axes[axis_name] = MachineAxis(
                name=axis_name,
                min_travel=float(axis_data.get("min_travel", -500.0)),
                max_travel=float(axis_data.get("max_travel", 500.0))
            )

        return cls(
            name=str(data.get("name", "알 수 없는 머신")),
            axes=axes,
            max_spindle_rpm=float(data.get("max_spindle_rpm", 10000.0)),
            max_feedrate=float(data.get("max_feedrate", 10000.0)),
            rapid_feedrate=float(data.get("rapid_feedrate", 15000.0)),
            manufacturer=str(data.get("manufacturer", "")),
            model=str(data.get("model", "")),
        )

    def to_dict(self) -> dict:
        """MachineDef 인스턴스를 딕셔너리로 변환합니다."""
        axes_dict = {}
        for name, axis in self.axes.items():
            axes_dict[name] = {
                "min_travel": axis.min_travel,
                "max_travel": axis.max_travel
            }

        return {
            "name": self.name,
            "axes": axes_dict,
            "max_spindle_rpm": self.max_spindle_rpm,
            "max_feedrate": self.max_feedrate,
            "rapid_feedrate": self.rapid_feedrate,
            "manufacturer": self.manufacturer,
            "model": self.model,
        }


def create_default_machine() -> MachineDef:
    """
    기본 3축 수직 머시닝 센터 설정을 반환합니다.
    설정 파일이 없을 때 사용됩니다.
    """
    return MachineDef(
        name="3축 수직 머시닝 센터 (기본값)",
        axes={
            'X': MachineAxis('X', -500.0, 500.0),
            'Y': MachineAxis('Y', -400.0, 400.0),
            'Z': MachineAxis('Z', -300.0, 100.0),
        },
        max_spindle_rpm=12000.0,
        max_feedrate=10000.0,
        rapid_feedrate=15000.0,
    )
