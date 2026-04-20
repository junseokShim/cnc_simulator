"""
공구(Tool) 데이터 모델 모듈

사용자 입력용 공구 라이브러리 정보와
가공 모델에서 사용하는 공구 메타데이터를 함께 정의합니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional


class ToolType(Enum):
    """
    공구 형상/가공 방식 기준 분류

    `tool_category`가 현장 약어(REM/EM/DR 등)라면,
    `tool_type`은 시뮬레이터 내부의 형상/거동 분류입니다.
    """

    END_MILL = "END_MILL"
    ROUGHING_END_MILL = "ROUGHING_END_MILL"
    BALL_END = "BALL_END"
    DRILL = "DRILL"
    FACE_MILL = "FACE_MILL"
    TAP = "TAP"
    CUSTOM = "CUSTOM"


_TOOL_TYPE_ALIASES: Dict[str, ToolType] = {
    "END_MILL": ToolType.END_MILL,
    "ENDMILL": ToolType.END_MILL,
    "FLAT_END_MILL": ToolType.END_MILL,
    "EM": ToolType.END_MILL,
    "ROUGHING_END_MILL": ToolType.ROUGHING_END_MILL,
    "ROUGHING": ToolType.ROUGHING_END_MILL,
    "ROUGHER": ToolType.ROUGHING_END_MILL,
    "REM": ToolType.ROUGHING_END_MILL,
    "BALL_END": ToolType.BALL_END,
    "BALL": ToolType.BALL_END,
    "BALL_END_MILL": ToolType.BALL_END,
    "DRILL": ToolType.DRILL,
    "DR": ToolType.DRILL,
    "FACE_MILL": ToolType.FACE_MILL,
    "FACE": ToolType.FACE_MILL,
    "TAP": ToolType.TAP,
    "CUSTOM": ToolType.CUSTOM,
}

_TOOL_CATEGORY_ALIASES: Dict[str, str] = {
    "EM": "EM",
    "END_MILL": "EM",
    "ENDMILL": "EM",
    "FLAT_END_MILL": "EM",
    "REM": "REM",
    "ROUGHING_END_MILL": "REM",
    "ROUGHING": "REM",
    "ROUGHER": "REM",
    "BALL": "BALL",
    "BALL_END": "BALL",
    "BALL_END_MILL": "BALL",
    "DR": "DR",
    "DRILL": "DR",
    "FACE": "FACE",
    "FACE_MILL": "FACE",
    "TAP": "TAP",
}

_CATEGORY_DISPLAY_NAMES: Dict[str, str] = {
    "EM": "엔드밀",
    "REM": "러핑 엔드밀",
    "BALL": "볼 엔드밀",
    "DR": "드릴",
    "FACE": "페이스밀",
    "TAP": "탭",
    "CUSTOM": "사용자 정의",
}

_CATEGORY_MODEL_DEFAULTS: Dict[str, dict] = {
    "EM": {
        "tool_type": ToolType.END_MILL,
        "default_flute_count": 4,
        "force_factor": 1.00,
        "tangential_force_factor": 1.00,
        "radial_force_factor": 1.00,
        "axial_force_factor": 1.00,
        "engagement_factor": 1.00,
        "chatter_factor": 1.00,
        "rapid_shock_factor": 1.00,
        "stability_factor": 1.00,
    },
    "REM": {
        "tool_type": ToolType.ROUGHING_END_MILL,
        "default_flute_count": 4,
        "force_factor": 0.92,
        "tangential_force_factor": 0.94,
        "radial_force_factor": 0.86,
        "axial_force_factor": 1.02,
        "engagement_factor": 0.90,
        "chatter_factor": 0.90,
        "rapid_shock_factor": 1.05,
        "stability_factor": 1.08,
    },
    "BALL": {
        "tool_type": ToolType.BALL_END,
        "default_flute_count": 2,
        "force_factor": 1.06,
        "tangential_force_factor": 1.02,
        "radial_force_factor": 0.95,
        "axial_force_factor": 1.10,
        "engagement_factor": 0.85,
        "chatter_factor": 1.05,
        "rapid_shock_factor": 1.00,
        "stability_factor": 0.95,
    },
    "DR": {
        "tool_type": ToolType.DRILL,
        "default_flute_count": 2,
        "force_factor": 0.98,
        "tangential_force_factor": 0.45,
        "radial_force_factor": 0.35,
        "axial_force_factor": 1.75,
        "engagement_factor": 0.95,
        "chatter_factor": 0.55,
        "rapid_shock_factor": 1.12,
        "stability_factor": 1.18,
    },
    "FACE": {
        "tool_type": ToolType.FACE_MILL,
        "default_flute_count": 5,
        "force_factor": 1.10,
        "tangential_force_factor": 1.08,
        "radial_force_factor": 0.92,
        "axial_force_factor": 1.00,
        "engagement_factor": 1.12,
        "chatter_factor": 0.88,
        "rapid_shock_factor": 0.96,
        "stability_factor": 1.12,
    },
    "TAP": {
        "tool_type": ToolType.TAP,
        "default_flute_count": 2,
        "force_factor": 1.12,
        "tangential_force_factor": 0.25,
        "radial_force_factor": 0.20,
        "axial_force_factor": 1.30,
        "engagement_factor": 0.75,
        "chatter_factor": 0.42,
        "rapid_shock_factor": 1.08,
        "stability_factor": 1.20,
    },
    "CUSTOM": {
        "tool_type": ToolType.CUSTOM,
        "default_flute_count": 4,
        "force_factor": 1.00,
        "tangential_force_factor": 1.00,
        "radial_force_factor": 1.00,
        "axial_force_factor": 1.00,
        "engagement_factor": 1.00,
        "chatter_factor": 1.00,
        "rapid_shock_factor": 1.00,
        "stability_factor": 1.00,
    },
}


def normalize_tool_category(value: Optional[str]) -> str:
    """현장 약어/열거형 값을 공통 카테고리 코드로 정규화합니다."""

    if not value:
        return "EM"

    normalized = str(value).strip().upper().replace("-", "_")
    return _TOOL_CATEGORY_ALIASES.get(normalized, normalized)


def normalize_tool_type(value: Optional[str | ToolType]) -> ToolType:
    """문자열 또는 열거형을 `ToolType`으로 정규화합니다."""

    if isinstance(value, ToolType):
        return value

    if value is None:
        return ToolType.END_MILL

    normalized = str(value).strip().upper().replace("-", "_")
    return _TOOL_TYPE_ALIASES.get(normalized, ToolType.CUSTOM)


def infer_tool_type_from_category(category_code: str) -> ToolType:
    """카테고리 코드로 기본 `ToolType`을 유추합니다."""

    category = normalize_tool_category(category_code)
    defaults = _CATEGORY_MODEL_DEFAULTS.get(category, _CATEGORY_MODEL_DEFAULTS["CUSTOM"])
    return defaults["tool_type"]


@dataclass
class Tool:
    """
    공구 정보 데이터 클래스

    기본 형상 외에도 오버행, 강성 보정, 절삭 계수 보정 등
    시뮬레이터 모델이 직접 사용할 수 있는 메타데이터를 포함합니다.
    """

    tool_number: int
    name: str
    tool_type: ToolType
    diameter: float
    length: float
    flute_length: float
    corner_radius: float = 0.0
    material: str = "카바이드"
    flute_count: int = 0
    tool_id: str = ""
    tool_category: str = "EM"
    overhang_mm: float = 0.0
    rigidity_factor: float = 1.0
    holder_rigidity_factor: float = 1.0
    cutting_coefficient_factor: float = 1.0
    material_coefficient_overrides: Dict[str, float] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self):
        self.tool_type = normalize_tool_type(self.tool_type)
        self.tool_category = normalize_tool_category(self.tool_category or self.tool_type.value)
        if self.tool_type == ToolType.CUSTOM:
            self.tool_type = infer_tool_type_from_category(self.tool_category)

        if not self.tool_id:
            self.tool_id = f"T{int(self.tool_number)}"

        defaults = self.get_model_defaults()
        if self.flute_count <= 0:
            self.flute_count = int(defaults["default_flute_count"])

        self.diameter = float(max(self.diameter, 0.1))
        self.length = float(max(self.length, self.diameter))
        self.flute_length = float(max(self.flute_length, min(self.length, self.diameter * 0.5)))
        self.corner_radius = float(max(self.corner_radius, 0.0))
        self.overhang_mm = float(max(self.overhang_mm, 0.0))
        self.rigidity_factor = float(max(self.rigidity_factor, 0.15))
        self.holder_rigidity_factor = float(max(self.holder_rigidity_factor, 0.15))
        self.cutting_coefficient_factor = float(max(self.cutting_coefficient_factor, 0.15))

    @property
    def diameter_mm(self) -> float:
        """사용자가 입력하는 공구 직경(mm)"""

        return float(self.diameter)

    @property
    def radius_mm(self) -> float:
        """내부 계산에 사용하는 공구 반경(mm = 직경 / 2)"""

        return self.diameter_mm / 2.0

    @property
    def radius(self) -> float:
        """기존 코드와의 호환을 위한 공구 반경(mm)"""

        return self.radius_mm

    @property
    def is_ball_end(self) -> bool:
        """볼 엔드밀 여부를 반환합니다."""

        return self.tool_type == ToolType.BALL_END

    @property
    def is_drill(self) -> bool:
        """드릴 계열 여부를 반환합니다."""

        return self.tool_type == ToolType.DRILL or self.tool_category == "DR"

    @property
    def effective_overhang_mm(self) -> float:
        """
        모델에서 사용할 오버행 길이(mm)

        사용자가 직접 지정하지 않으면 공구 길이와 날길이로 안전한 추정값을 만듭니다.
        """

        if self.overhang_mm > 0.0:
            return self.overhang_mm

        inferred = max(self.flute_length * 1.25, self.diameter * 4.0)
        return min(self.length, inferred)

    @property
    def overhang_ratio(self) -> float:
        """직경 대비 오버행 비율(L/D)을 반환합니다."""

        return self.effective_overhang_mm / max(self.diameter, 0.1)

    @property
    def effective_rigidity_factor(self) -> float:
        """홀더/공구 강성 보정을 합친 유효 강성 계수입니다."""

        defaults = self.get_model_defaults()
        profile_scale = float(defaults.get("stability_factor", 1.0))
        return max(0.15, self.rigidity_factor * self.holder_rigidity_factor * profile_scale)

    @property
    def display_category_name(self) -> str:
        """카테고리 표시명을 반환합니다."""

        return _CATEGORY_DISPLAY_NAMES.get(self.tool_category, self.tool_category)

    def get_model_defaults(self) -> dict:
        """카테고리별 모델 기본 계수를 반환합니다."""

        return dict(_CATEGORY_MODEL_DEFAULTS.get(self.tool_category, _CATEGORY_MODEL_DEFAULTS["CUSTOM"]))

    def get_force_distribution(self) -> dict:
        """절삭력 방향 분포 계수를 반환합니다."""

        defaults = self.get_model_defaults()
        return {
            "force_factor": float(defaults.get("force_factor", 1.0)) * self.cutting_coefficient_factor,
            "tangential_force_factor": float(defaults.get("tangential_force_factor", 1.0)),
            "radial_force_factor": float(defaults.get("radial_force_factor", 1.0)),
            "axial_force_factor": float(defaults.get("axial_force_factor", 1.0)),
        }

    def get_engagement_factor(self, machining_state: Optional[str] = None) -> float:
        """
        공구 형상별 맞물림 보정 계수를 반환합니다.

        드릴은 측면 절삭을 보수적으로 제한하고,
        러핑 엔드밀은 평균 유효 맞물림을 약간 낮게 잡습니다.
        """

        defaults = self.get_model_defaults()
        factor = float(defaults.get("engagement_factor", 1.0))

        if self.tool_category == "DR":
            if machining_state == "PLUNGE":
                return max(0.8, factor)
            return 0.35

        return factor

    def get_chatter_sensitivity_factor(self) -> float:
        """공구 형상별 채터 민감도 계수를 반환합니다."""

        defaults = self.get_model_defaults()
        return float(defaults.get("chatter_factor", 1.0))

    def get_rapid_shock_factor(self) -> float:
        """급속 이송 충격 민감도 계수를 반환합니다."""

        defaults = self.get_model_defaults()
        return float(defaults.get("rapid_shock_factor", 1.0))

    def get_display_name(self) -> str:
        """UI 표시용 공구 이름을 반환합니다."""

        return (
            f"T{self.tool_number}: {self.name} "
            f"(D{self.diameter_mm:.1f} / R{self.radius_mm:.1f} {self.display_category_name})"
        )

    @classmethod
    def from_dict(cls, data: dict) -> "Tool":
        """
        딕셔너리에서 Tool 인스턴스를 생성합니다.

        구버전 키(`diameter`, `length`)와
        신규 키(`diameter_mm`, `length_mm`)를 모두 지원합니다.
        """

        raw_type = data.get("tool_type") or data.get("type") or data.get("tool_category") or "END_MILL"
        tool_category = normalize_tool_category(data.get("tool_category") or raw_type)
        tool_type = normalize_tool_type(raw_type)
        if tool_type == ToolType.CUSTOM:
            tool_type = infer_tool_type_from_category(tool_category)

        diameter = float(data.get("diameter_mm", data.get("diameter", 10.0)))
        length = float(data.get("length_mm", data.get("length", max(diameter * 5.0, 50.0))))
        flute_length = float(
            data.get(
                "flute_length_mm",
                data.get("flute_length", max(diameter * 2.5, min(length, diameter * 3.0))),
            )
        )

        name = str(
            data.get("name")
            or data.get("tool_name")
            or f"{_CATEGORY_DISPLAY_NAMES.get(tool_category, tool_category)} φ{diameter:g}"
        )

        flute_count = int(data.get("flute_count", 0) or 0)
        defaults = _CATEGORY_MODEL_DEFAULTS.get(tool_category, _CATEGORY_MODEL_DEFAULTS["CUSTOM"])
        if flute_count <= 0:
            flute_count = int(defaults.get("default_flute_count", 4))

        overrides = data.get("material_coefficient_overrides", {}) or {}

        return cls(
            tool_number=int(data.get("tool_number", data.get("tool_no", 0))),
            name=name,
            tool_type=tool_type,
            diameter=diameter,
            length=length,
            flute_length=flute_length,
            corner_radius=float(data.get("corner_radius_mm", data.get("corner_radius", 0.0))),
            material=str(data.get("material", "카바이드")),
            flute_count=flute_count,
            tool_id=str(data.get("tool_id", "")),
            tool_category=tool_category,
            overhang_mm=float(data.get("overhang_mm", data.get("overhang", 0.0))),
            rigidity_factor=float(data.get("rigidity_factor", 1.0)),
            holder_rigidity_factor=float(data.get("holder_rigidity_factor", 1.0)),
            cutting_coefficient_factor=float(data.get("cutting_coefficient_factor", 1.0)),
            material_coefficient_overrides={
                str(key): float(value)
                for key, value in dict(overrides).items()
            },
            notes=str(data.get("notes", "")),
        )

    def to_dict(self) -> dict:
        """YAML/프로젝트 저장용 딕셔너리로 변환합니다."""

        return {
            "tool_id": self.tool_id,
            "tool_number": self.tool_number,
            "name": self.name,
            "tool_type": self.tool_type.value,
            "tool_category": self.tool_category,
            "diameter_mm": self.diameter_mm,
            "length_mm": self.length,
            "flute_length_mm": self.flute_length,
            "corner_radius_mm": self.corner_radius,
            "material": self.material,
            "flute_count": self.flute_count,
            "overhang_mm": self.overhang_mm,
            "rigidity_factor": self.rigidity_factor,
            "holder_rigidity_factor": self.holder_rigidity_factor,
            "cutting_coefficient_factor": self.cutting_coefficient_factor,
            "material_coefficient_overrides": dict(self.material_coefficient_overrides),
            "notes": self.notes,
        }
