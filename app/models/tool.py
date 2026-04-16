"""
공구(Tool) 데이터 모델 모듈
CNC 가공에 사용되는 공구의 형상과 속성을 정의합니다.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ToolType(Enum):
    """
    공구 종류 열거형
    CNC 가공에서 사용되는 주요 공구 유형을 정의합니다.
    """
    END_MILL = "END_MILL"       # 플랫 엔드밀: 평면 가공, 측면 가공
    BALL_END = "BALL_END"       # 볼 엔드밀: 곡면 가공, 3D 가공
    DRILL = "DRILL"             # 드릴: 구멍 가공
    FACE_MILL = "FACE_MILL"     # 페이스밀: 대형 평면 가공
    TAP = "TAP"                 # 탭: 나사 가공


@dataclass
class Tool:
    """
    공구 정보 데이터 클래스
    단일 공구의 형상 및 속성 정보를 저장합니다.
    """
    # 공구 번호 (T1, T2 등 NC 코드에서 사용)
    tool_number: int

    # 공구 이름 (예: "플랫 엔드밀 φ10")
    name: str

    # 공구 종류
    tool_type: ToolType

    # 공구 직경 (mm)
    diameter: float

    # 공구 전체 길이 (mm)
    length: float

    # 절삭날 길이 (mm) - 실제 가공이 가능한 부분
    flute_length: float

    # 코너 반경 (mm) - 볼 엔드밀의 경우 diameter/2, 플랫 엔드밀은 0
    corner_radius: float = 0.0

    # 공구 재질 (예: HSS, 카바이드 등)
    material: str = "카바이드"

    # 날 수 (공구 성능 계산에 사용)
    flute_count: int = 4

    @property
    def radius(self) -> float:
        """공구 반경 (직경의 절반)"""
        return self.diameter / 2.0

    @property
    def is_ball_end(self) -> bool:
        """볼 엔드밀 여부 확인"""
        return self.tool_type == ToolType.BALL_END

    def get_display_name(self) -> str:
        """UI 표시용 공구 이름을 반환합니다."""
        type_names = {
            ToolType.END_MILL: "엔드밀",
            ToolType.BALL_END: "볼엔드밀",
            ToolType.DRILL: "드릴",
            ToolType.FACE_MILL: "페이스밀",
            ToolType.TAP: "탭",
        }
        type_str = type_names.get(self.tool_type, str(self.tool_type.value))
        return f"T{self.tool_number}: {self.name} (φ{self.diameter:.1f} {type_str})"

    @classmethod
    def from_dict(cls, data: dict) -> 'Tool':
        """
        딕셔너리에서 Tool 인스턴스를 생성합니다.
        YAML 설정 파일 로딩에 사용됩니다.
        """
        # tool_type 문자열을 열거형으로 변환
        tool_type_str = data.get("tool_type", "END_MILL")
        try:
            tool_type = ToolType[tool_type_str]
        except KeyError:
            tool_type = ToolType.END_MILL

        return cls(
            tool_number=int(data.get("tool_number", 0)),
            name=str(data.get("name", "알 수 없는 공구")),
            tool_type=tool_type,
            diameter=float(data.get("diameter", 10.0)),
            length=float(data.get("length", 75.0)),
            flute_length=float(data.get("flute_length", 25.0)),
            corner_radius=float(data.get("corner_radius", 0.0)),
            material=str(data.get("material", "카바이드")),
            flute_count=int(data.get("flute_count", 4)),
        )

    def to_dict(self) -> dict:
        """Tool 인스턴스를 딕셔너리로 변환합니다. YAML 저장에 사용됩니다."""
        return {
            "tool_number": self.tool_number,
            "name": self.name,
            "tool_type": self.tool_type.value,
            "diameter": self.diameter,
            "length": self.length,
            "flute_length": self.flute_length,
            "corner_radius": self.corner_radius,
            "material": self.material,
            "flute_count": self.flute_count,
        }
