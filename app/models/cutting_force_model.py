"""
기계론적 절삭력 / 스핀들 부하 모델

Altintas 계열 평균 절삭력 식을 기반으로 하되,
공구 카테고리(REM/EM/DR), 공구 계수 오버라이드,
급속/공중이송의 축 구동 부하를 함께 반영합니다.
"""
from __future__ import annotations

import math
from typing import Dict

import numpy as np

from app.models.cutting_conditions import (
    STATE_AIR_FEED,
    STATE_ENTRY_CUT,
    STATE_EXIT_CUT,
    STATE_PLUNGE,
    STATE_RAPID,
)
from app.models.cutting_conditions import compute_directional_coefficients
from app.models.model_interfaces import (
    CuttingFeatures,
    SpindleLoadPrediction,
    SpindleLoadPredictor,
)
from app.utils.logger import get_logger

logger = get_logger("cutting_force_model")


MATERIAL_FORCE_COEFFICIENTS: Dict[str, dict] = {
    "aluminum": {
        "name": "알루미늄 합금 (Al 6061/7075)",
        "Ktc": 700.0,
        "Krc": 210.0,
        "Kac": 84.0,
        "Kte": 22.0,
        "Kre": 8.0,
        "Kae": 2.0,
        "Krc_ratio": 0.30,
    },
    "steel_mild": {
        "name": "저탄소강 (S45C, 1045)",
        "Ktc": 1800.0,
        "Krc": 630.0,
        "Kac": 180.0,
        "Kte": 42.0,
        "Kre": 18.0,
        "Kae": 5.0,
        "Krc_ratio": 0.35,
    },
    "steel_hard": {
        "name": "경화강 (HRC 45 이상)",
        "Ktc": 2500.0,
        "Krc": 1000.0,
        "Kac": 300.0,
        "Kte": 60.0,
        "Kre": 28.0,
        "Kae": 8.0,
        "Krc_ratio": 0.40,
    },
    "stainless": {
        "name": "스테인리스강 (SUS304)",
        "Ktc": 2200.0,
        "Krc": 770.0,
        "Kac": 220.0,
        "Kte": 52.0,
        "Kre": 22.0,
        "Kae": 6.0,
        "Krc_ratio": 0.35,
    },
    "titanium": {
        "name": "티타늄 합금 (Ti-6Al-4V)",
        "Ktc": 2000.0,
        "Krc": 800.0,
        "Kac": 240.0,
        "Kte": 48.0,
        "Kre": 20.0,
        "Kae": 6.0,
        "Krc_ratio": 0.40,
    },
    "cast_iron": {
        "name": "주철 (GC250)",
        "Ktc": 1100.0,
        "Krc": 330.0,
        "Kac": 110.0,
        "Kte": 30.0,
        "Kre": 12.0,
        "Kae": 4.0,
        "Krc_ratio": 0.30,
    },
    "default": {
        "name": "일반 금속",
        "Ktc": 1500.0,
        "Krc": 510.0,
        "Kac": 150.0,
        "Kte": 36.0,
        "Kre": 15.0,
        "Kae": 4.0,
        "Krc_ratio": 0.34,
    },
}


class MechanisticCuttingForceModel(SpindleLoadPredictor):
    """공구 메타와 가공 상태를 반영한 평균 절삭력 / 스핀들 부하 모델"""

    def predict(
        self,
        features: CuttingFeatures,
        params: dict,
    ) -> SpindleLoadPrediction:
        """피처로부터 스핀들 부하와 절삭력 분해 결과를 계산합니다."""

        P_rated = float(params.get("spindle_rated_power_w", 7500.0))
        eta = float(max(params.get("machine_efficiency", 0.85), 0.1))
        baseline_ratio = float(params.get("baseline_power_ratio", 0.07))
        axis_ratio = float(params.get("axis_motion_power_ratio", 0.04))
        rapid_traverse = float(max(params.get("rapid_traverse_mm_min", 36000.0), 1.0))

        speed_ratio = float(np.clip(features.effective_feedrate / rapid_traverse, 0.0, 1.0))
        motion_state_factor = self._motion_state_axis_factor(features.machining_state)

        P_baseline = baseline_ratio * P_rated if features.spindle_rpm > 0.0 else 0.0
        P_axis = axis_ratio * P_rated * speed_ratio * motion_state_factor

        if not features.is_cutting:
            total_power = P_baseline + P_axis
            baseline_load = P_baseline / P_rated * 100.0
            axis_load = P_axis / P_rated * 100.0

            return SpindleLoadPrediction(
                spindle_load_pct=float(np.clip(total_power / P_rated * 100.0, 0.0, 35.0)),
                baseline_load_pct=baseline_load,
                axis_motion_load_pct=axis_load,
                cutting_load_pct=0.0,
                power_w=total_power,
                mrr=0.0,
                aggressiveness=0.0,
                debug_components={
                    "motion_state": features.machining_state,
                    "speed_ratio": round(speed_ratio, 3),
                    "motion_state_factor": round(motion_state_factor, 3),
                    "baseline_power_w": round(P_baseline, 2),
                    "axis_power_w": round(P_axis, 2),
                    "cutting_power_w": 0.0,
                    "tool_category": features.tool_category,
                },
            )

        coeff = self._resolve_material_coefficients(features, params)
        phi_st = features.phi_entry_rad
        phi_ex = features.phi_exit_rad
        delta_phi = phi_ex - phi_st
        ap = float(max(features.axial_depth_ap, 0.0))
        fz = float(max(features.feed_per_tooth_fz, 0.0))
        z = int(max(features.flute_count, 1))
        D = float(max(features.tool_diameter_mm, 0.1))
        Vc = float(max(features.cutting_speed_vc, 0.0))

        if delta_phi <= 0.0 or ap <= 0.0 or fz <= 0.0:
            total_power = P_baseline + P_axis
            return SpindleLoadPrediction(
                spindle_load_pct=float(np.clip(total_power / P_rated * 100.0, 0.0, 35.0)),
                baseline_load_pct=P_baseline / P_rated * 100.0,
                axis_motion_load_pct=P_axis / P_rated * 100.0,
                cutting_load_pct=0.0,
                power_w=total_power,
                debug_components={
                    "motion_state": features.machining_state,
                    "speed_ratio": round(speed_ratio, 3),
                    "coefficients": coeff,
                    "note": "유효 절삭 조건 부족으로 절삭 성분 0 처리",
                },
            )

        Ft = (z * ap / (2.0 * math.pi)) * (
            coeff["Ktc"] * fz * (math.cos(phi_st) - math.cos(phi_ex))
            + coeff["Kte"] * delta_phi
        )
        Fr = (z * ap / (2.0 * math.pi)) * (
            coeff["Krc"] * fz * (math.cos(phi_st) - math.cos(phi_ex))
            + coeff["Kre"] * delta_phi
        )
        Fa = (z * ap / (2.0 * math.pi)) * (
            coeff["Kac"] * fz * (math.cos(phi_st) - math.cos(phi_ex))
            + coeff["Kae"] * delta_phi
        )

        state_force_factor = self._state_force_factor(features)
        category_factor = self._category_force_factor(features)
        contact_factor = self._contact_force_factor(features)
        total_force_factor = state_force_factor * contact_factor

        Ft *= total_force_factor * category_factor["ft"]
        Fr *= total_force_factor * category_factor["fr"]
        Fa *= total_force_factor * category_factor["fa"]

        if features.tool_category == "DR":
            if features.is_plunge or features.machining_state == STATE_PLUNGE:
                Fa *= 1.20
            else:
                Ft *= 0.55
                Fr *= 0.45

        Ft = max(0.0, Ft)
        Fr = max(0.0, Fr)
        Fa = max(0.0, Fa)

        Krc_ratio = coeff["Krc"] / max(coeff["Ktc"], 1e-6)
        a_xx, a_xy, a_yx, a_yy = compute_directional_coefficients(phi_st, phi_ex, Krc_ratio)
        phi_mid = (phi_st + phi_ex) / 2.0
        b_xx = -math.cos(phi_mid) * delta_phi
        b_xy = math.sin(phi_mid) * delta_phi

        Fx = (z * ap * fz / (4.0 * math.pi)) * (coeff["Ktc"] * a_xx + coeff["Krc"] * a_xy)
        Fx += (z * ap / (2.0 * math.pi)) * (coeff["Kte"] * b_xx + coeff["Kre"] * b_xy)
        Fy = (z * ap * fz / (4.0 * math.pi)) * (coeff["Ktc"] * a_yx + coeff["Krc"] * a_yy)
        Fy += (z * ap / (2.0 * math.pi)) * (coeff["Kte"] * (-b_xy) + coeff["Kre"] * b_xx)
        Fz = Fa

        Fx *= total_force_factor * category_factor["fx"]
        Fy *= total_force_factor * category_factor["fy"]
        Fz *= total_force_factor * category_factor["fz"]

        T_nm = Ft * (D / 2.0) / 1000.0
        tangential_power = Ft * Vc / 60.0
        axial_power = abs(Fz) * (features.effective_feedrate / 60000.0)
        P_cutting = max(tangential_power, axial_power) / eta

        total_power = P_baseline + P_axis + P_cutting
        baseline_load = P_baseline / P_rated * 100.0
        axis_load = P_axis / P_rated * 100.0
        cutting_load = P_cutting / P_rated * 100.0
        total_load = float(np.clip(total_power / P_rated * 100.0, 0.0, 150.0))

        MRR = float(max(features.mrr_mm3_per_min, 0.0))
        mrr_ref = float(max(params.get("mrr_reference_mm3min", 50000.0), 1.0))
        aggressiveness = float(np.clip(MRR / mrr_ref, 0.0, 1.0))

        return SpindleLoadPrediction(
            spindle_load_pct=total_load,
            cutting_force_ft=Ft,
            cutting_force_fr=Fr,
            cutting_force_fa=Fa,
            force_x=Fx,
            force_y=Fy,
            force_z=Fz,
            torque_nm=T_nm,
            power_w=total_power,
            mrr=MRR,
            aggressiveness=aggressiveness,
            baseline_load_pct=baseline_load,
            axis_motion_load_pct=axis_load,
            cutting_load_pct=float(np.clip(cutting_load, 0.0, 150.0)),
            debug_components={
                "motion_state": features.machining_state,
                "speed_ratio": round(speed_ratio, 3),
                "motion_state_factor": round(motion_state_factor, 3),
                "tool_category": features.tool_category,
                "state_force_factor": round(state_force_factor, 3),
                "contact_force_factor": round(contact_factor, 3),
                "coefficients": {
                    key: round(float(value), 3)
                    if isinstance(value, (int, float, np.floating))
                    else value
                    for key, value in coeff.items()
                },
                "baseline_power_w": round(P_baseline, 2),
                "axis_power_w": round(P_axis, 2),
                "cutting_power_w": round(P_cutting, 2),
                "force_factor_ft": round(category_factor["ft"], 3),
                "force_factor_fr": round(category_factor["fr"], 3),
                "force_factor_fa": round(category_factor["fa"], 3),
            },
        )

    def _resolve_material_coefficients(self, features: CuttingFeatures, params: dict) -> dict:
        """재질 계수와 공구 계수 오버라이드를 병합합니다."""

        material_key = str(params.get("material", "default"))
        coeff = dict(MATERIAL_FORCE_COEFFICIENTS.get(material_key, MATERIAL_FORCE_COEFFICIENTS["default"]))

        if features.tool_material_overrides:
            for key, value in features.tool_material_overrides.items():
                coeff[str(key)] = float(value)

        force_factor = float(max(features.tool_cutting_coefficient_factor, 0.15))
        tangential_factor = float(max(features.tool_tangential_force_factor, 0.15))
        radial_factor = float(max(features.tool_radial_force_factor, 0.15))
        axial_factor = float(max(features.tool_axial_force_factor, 0.15))

        coeff["Ktc"] = float(params.get("Ktc_override", coeff["Ktc"])) * force_factor * tangential_factor
        coeff["Krc"] = float(params.get("Krc_override", coeff["Krc"])) * force_factor * radial_factor
        coeff["Kac"] = float(params.get("Kac_override", coeff["Kac"])) * force_factor * axial_factor
        coeff["Kte"] = float(params.get("Kte_override", coeff["Kte"])) * tangential_factor
        coeff["Kre"] = float(params.get("Kre_override", coeff["Kre"])) * radial_factor
        coeff["Kae"] = float(params.get("Kae_override", coeff["Kae"])) * axial_factor

        return coeff

    @staticmethod
    def _motion_state_axis_factor(machining_state: str) -> float:
        """가공 상태별 축 구동 부하 배율"""

        if machining_state == STATE_RAPID:
            return 1.15
        if machining_state == STATE_AIR_FEED:
            return 0.55
        if machining_state == STATE_PLUNGE:
            return 0.75
        return 1.0

    @staticmethod
    def _state_force_factor(features: CuttingFeatures) -> float:
        """진입/정삭/이탈 상태에 따른 평균 힘 배율"""

        if features.machining_state == STATE_ENTRY_CUT:
            return 0.88
        if features.machining_state == STATE_EXIT_CUT:
            return 0.78
        if features.machining_state == STATE_PLUNGE:
            return 0.72
        return 1.0

    @staticmethod
    def _contact_force_factor(features: CuttingFeatures) -> float:
        """실제 접촉 비율 기반 평균 힘 배율"""

        if features.contact_ratio <= 0.0:
            return 1.0
        return float(np.clip(0.55 + 0.45 * features.contact_ratio, 0.35, 1.05))

    @staticmethod
    def _category_force_factor(features: CuttingFeatures) -> dict:
        """공구 카테고리별 힘 방향 분배 배율"""

        if features.tool_category == "REM":
            return {"ft": 0.96, "fr": 0.88, "fa": 1.02, "fx": 0.90, "fy": 0.90, "fz": 1.04}
        if features.tool_category == "BALL":
            return {"ft": 1.02, "fr": 0.95, "fa": 1.08, "fx": 0.96, "fy": 0.96, "fz": 1.08}
        if features.tool_category == "DR":
            return {"ft": 0.42, "fr": 0.32, "fa": 1.60, "fx": 0.35, "fy": 0.35, "fz": 1.45}
        if features.tool_category == "FACE":
            return {"ft": 1.05, "fr": 0.92, "fa": 0.92, "fx": 1.02, "fy": 1.02, "fz": 0.94}
        if features.tool_category == "TAP":
            return {"ft": 0.28, "fr": 0.22, "fa": 1.30, "fx": 0.24, "fy": 0.24, "fz": 1.25}
        return {"ft": 1.0, "fr": 1.0, "fa": 1.0, "fx": 1.0, "fy": 1.0, "fz": 1.0}
