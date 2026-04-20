"""
가공 해석 모델 인터페이스 정의 모듈

스핀들 부하 모델과 진동/채터 모델이 공유하는
입출력 스키마를 정의합니다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class CuttingFeatures:
    """
    가공 모델 입력 피처 묶음

    단순 절삭 조건뿐 아니라 공구 메타데이터와
    급속/공중이송의 운동 상태까지 함께 담습니다.
    """

    cutting_speed_vc: float = 0.0
    feed_per_tooth_fz: float = 0.0
    axial_depth_ap: float = 0.0
    radial_depth_ae: float = 0.0
    radial_ratio: float = 0.0

    tool_diameter: float = 10.0
    flute_count: int = 4
    spindle_rpm: float = 0.0
    feedrate: float = 0.0
    effective_feedrate: float = 0.0
    motion_distance_mm: float = 0.0
    speed_ratio: float = 0.0
    speed_change_ratio: float = 0.0
    acceleration_proxy: float = 0.0
    jerk_proxy: float = 0.0
    axis_ratio_x: float = 0.0
    axis_ratio_y: float = 0.0
    axis_ratio_z: float = 0.0

    phi_entry_rad: float = 0.0
    phi_exit_rad: float = 0.0
    phi_entry_deg: float = 0.0
    phi_exit_deg: float = 0.0
    engagement_arc_deg: float = 0.0

    direction_change_deg: float = 0.0
    is_plunge: bool = False
    is_ramp: bool = False
    is_cutting: bool = False

    mrr_mm3_per_min: float = 0.0
    machining_state: str = "UNKNOWN"
    contact_ratio: float = 0.0

    tool_type: str = "END_MILL"
    tool_category: str = "EM"
    tool_overhang_mm: float = 0.0
    tool_rigidity_factor: float = 1.0
    tool_cutting_coefficient_factor: float = 1.0
    tool_engagement_factor: float = 1.0
    tool_chatter_factor: float = 1.0
    tool_tangential_force_factor: float = 1.0
    tool_radial_force_factor: float = 1.0
    tool_axial_force_factor: float = 1.0
    tool_rapid_shock_factor: float = 1.0
    tool_material_overrides: Dict[str, float] = field(default_factory=dict)

    @property
    def tool_diameter_mm(self) -> float:
        """공구 직경(mm)을 명시적으로 반환합니다."""

        return float(self.tool_diameter)

    def to_dict(self) -> Dict[str, Any]:
        """모델 디버깅/ML 입력용 딕셔너리 변환"""

        return dict(self.__dict__)


@dataclass
class SpindleLoadPrediction:
    """스핀들 부하 예측 결과"""

    spindle_load_pct: float = 0.0
    cutting_force_ft: float = 0.0
    cutting_force_fr: float = 0.0
    cutting_force_fa: float = 0.0
    force_x: float = 0.0
    force_y: float = 0.0
    force_z: float = 0.0
    torque_nm: float = 0.0
    power_w: float = 0.0
    mrr: float = 0.0
    aggressiveness: float = 0.0

    baseline_load_pct: float = 0.0
    axis_motion_load_pct: float = 0.0
    cutting_load_pct: float = 0.0
    debug_components: dict = field(default_factory=dict)


@dataclass
class ChatterRiskPrediction:
    """진동/채터 예측 결과"""

    chatter_risk_score: float = 0.0
    chatter_raw_score: float = 0.0
    motion_risk_score: float = 0.0
    stability_margin: float = 999.0
    ap_limit: float = 0.0
    tooth_passing_freq_hz: float = 0.0
    dynamic_magnification: float = 1.0
    vibration_x_um: float = 0.0
    vibration_y_um: float = 0.0
    vibration_z_um: float = 0.0
    resultant_vibration_um: float = 0.0
    motion_vibration_um: float = 0.0
    cutting_vibration_um: float = 0.0
    risk_factors: dict = field(default_factory=dict)


class SpindleLoadPredictor(ABC):
    """스핀들 부하 예측기 인터페이스"""

    @abstractmethod
    def predict(self, features: CuttingFeatures, params: dict) -> SpindleLoadPrediction:
        """입력 피처로부터 부하/절삭력/전력을 예측합니다."""


class ChatterRiskPredictor(ABC):
    """진동/채터 예측기 인터페이스"""

    @abstractmethod
    def predict(
        self,
        features: CuttingFeatures,
        load_pred: SpindleLoadPrediction,
        params: dict,
    ) -> ChatterRiskPrediction:
        """입력 피처와 절삭력 결과를 이용해 진동/채터를 예측합니다."""
