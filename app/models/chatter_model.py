"""
진동 / 채터 위험도 모델

절삭 채터와 급속/공중이송의 모션 유발 진동을 분리해서 계산합니다.
"""
from __future__ import annotations

import math

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
    ChatterRiskPrediction,
    ChatterRiskPredictor,
    CuttingFeatures,
    SpindleLoadPrediction,
)
from app.utils.logger import get_logger

logger = get_logger("chatter_model")

_SM_REF = 1.0
_SM_POWER = 2.8


def _sigmoid(value: float) -> float:
    """0~1 로지스틱 정규화"""

    return 1.0 / (1.0 + math.exp(-value))


class StabilityLobeChatterModel(ChatterRiskPredictor):
    """상태 분리형 채터 / 진동 모델"""

    def predict(
        self,
        features: CuttingFeatures,
        load_pred: SpindleLoadPrediction,
        params: dict,
    ) -> ChatterRiskPrediction:
        """절삭 상태와 운동 상태를 함께 반영해 진동/채터를 계산합니다."""

        motion_axes, motion_total, motion_score, motion_debug = self._predict_motion_vibration(
            features,
            params,
        )

        if not features.is_cutting:
            return ChatterRiskPrediction(
                chatter_risk_score=0.0,
                chatter_raw_score=0.0,
                motion_risk_score=motion_score,
                stability_margin=999.0,
                vibration_x_um=motion_axes[0],
                vibration_y_um=motion_axes[1],
                vibration_z_um=motion_axes[2],
                resultant_vibration_um=motion_total,
                motion_vibration_um=motion_total,
                cutting_vibration_um=0.0,
                risk_factors={
                    "machining_state": features.machining_state,
                    "tool_category": features.tool_category,
                    "motion_risk_score": round(motion_score, 3),
                    "motion_vibration_um": round(motion_total, 3),
                    **motion_debug,
                },
            )

        k_n_per_um = float(max(params.get("k_n_per_um", 20.0), 0.5))
        k_n_per_mm = k_n_per_um * 1000.0
        zeta = float(np.clip(params.get("zeta", 0.03), 0.005, 0.25))
        f_n_hz = float(max(params.get("f_natural_hz", 800.0), 10.0))
        omega_n = 2.0 * math.pi * f_n_hz

        machine_stiffness = float(max(params.get("machine_stiffness", 1.0), 0.2))
        holder_factor = float(max(params.get("tool_overhang_factor", 1.0), 0.2))
        rigidity_factor = float(max(features.tool_rigidity_factor, 0.2))
        slenderness_ratio = features.tool_overhang_mm / max(features.tool_diameter_mm, 0.1)
        overhang_factor = 1.0 + max(0.0, slenderness_ratio - 3.0) * 0.22
        k_eff = k_n_per_mm * machine_stiffness * rigidity_factor / max(holder_factor * overhang_factor, 1e-6)

        ap = float(max(features.axial_depth_ap, 0.0))
        phi_st = features.phi_entry_rad
        phi_ex = features.phi_exit_rad
        z = int(max(features.flute_count, 1))
        n_rpm = float(max(features.spindle_rpm, 0.0))
        D = float(max(features.tool_diameter_mm, 0.1))
        Ktc = float(max(params.get("Ktc", 700.0), 1.0)) * float(max(features.tool_cutting_coefficient_factor, 0.15))
        Krc_ratio = float(max(params.get("Krc_ratio", 0.3), 0.05))
        Krc_ratio *= float(max(features.tool_radial_force_factor, 0.2)) / float(
            max(features.tool_tangential_force_factor, 0.2)
        )
        Krc_ratio = float(np.clip(Krc_ratio, 0.05, 1.2))

        if ap <= 0.0 or (phi_ex - phi_st) <= 0.0:
            return ChatterRiskPrediction(
                chatter_risk_score=0.0,
                chatter_raw_score=0.0,
                motion_risk_score=motion_score,
                stability_margin=999.0,
                vibration_x_um=motion_axes[0],
                vibration_y_um=motion_axes[1],
                vibration_z_um=motion_axes[2],
                resultant_vibration_um=motion_total,
                motion_vibration_um=motion_total,
                cutting_vibration_um=0.0,
                risk_factors={
                    "machining_state": features.machining_state,
                    "tool_category": features.tool_category,
                    "motion_risk_score": round(motion_score, 3),
                    "motion_vibration_um": round(motion_total, 3),
                    "note": "유효 절입이 없어 절삭 채터 계산 생략",
                    **motion_debug,
                },
            )

        a_xx, a_xy, a_yx, a_yy = compute_directional_coefficients(phi_st, phi_ex, Krc_ratio)
        a_d = max(abs(a_yy) + abs(a_xx) * 0.5, 0.01)

        lambda_r_min = -1.0 / (
            2.0 * k_eff * zeta * math.sqrt(max(1.0 - zeta**2, 0.01))
        )
        ap_lim_raw = -2.0 * math.pi / (z * Ktc * a_d * lambda_r_min)
        stability_correction = float(max(params.get("stability_lobe_correction", 1.0), 0.3))
        ap_lim = max(ap_lim_raw * stability_correction, 0.001)
        stability_margin = ap_lim / max(ap, 0.001)

        tooth_passing_freq = n_rpm * z / 60.0
        r = tooth_passing_freq / f_n_hz if f_n_hz > 0.0 else 0.0
        H_mag = math.sqrt((1.0 - r**2) ** 2 + (2.0 * zeta * r) ** 2)
        dynamic_magnification = 1.0 / max(H_mag, 1e-6)

        cutting_axes = self._predict_cutting_vibration(load_pred, k_eff, dynamic_magnification)
        cutting_total = float(np.linalg.norm(cutting_axes))
        combined_axes = np.sqrt(np.square(cutting_axes) + np.square(motion_axes))
        combined_total = float(np.linalg.norm(combined_axes))

        stability_component = 1.0 / (1.0 + (max(stability_margin, 1e-3) / _SM_REF) ** _SM_POWER)
        engagement_component = float(
            np.clip(
                0.50 * features.radial_ratio
                + 0.25 * min(ap / max(D, 0.1), 1.0)
                + 0.25 * features.contact_ratio,
                0.0,
                1.0,
            )
        )
        dynamic_component = float(np.clip((dynamic_magnification - 1.0) / 2.0, 0.0, 1.0))
        transition_component = float(
            np.clip(
                0.55 * min(features.direction_change_deg / 90.0, 1.0)
                + 0.45 * features.jerk_proxy,
                0.0,
                1.0,
            )
        )
        load_component = float(np.clip(load_pred.cutting_load_pct / 55.0, 0.0, 1.0))
        slenderness_component = float(np.clip((slenderness_ratio - 3.0) / 5.0, 0.0, 1.0))

        raw_score = (
            0.38 * stability_component
            + 0.16 * engagement_component
            + 0.12 * dynamic_component
            + 0.12 * transition_component
            + 0.12 * slenderness_component
            + 0.10 * load_component
        )

        cutting_gate = 0.30 + 0.70 * float(np.clip(load_pred.cutting_load_pct / 10.0, 0.0, 1.0))
        sensitivity = float(max(params.get("chatter_sensitivity", 1.0), 0.2))
        tool_factor = float(max(features.tool_chatter_factor, 0.2))
        state_factor = self._state_chatter_factor(features.machining_state)

        chatter_raw_score = float(
            np.clip(raw_score * cutting_gate * sensitivity * tool_factor * state_factor, 0.0, 1.2)
        )
        chatter_probability = float(np.clip(_sigmoid(4.4 * (chatter_raw_score - 0.48)), 0.0, 0.98))

        if features.tool_category == "DR":
            chatter_probability *= 0.65 if features.is_plunge else 0.75
            chatter_raw_score *= 0.70

        risk_factors = {
            "machining_state": features.machining_state,
            "tool_category": features.tool_category,
            "tool_overhang_mm": round(features.tool_overhang_mm, 3),
            "slenderness_ratio": round(slenderness_ratio, 3),
            "effective_stiffness_n_per_mm": round(k_eff, 3),
            "stability_margin": round(stability_margin, 3),
            "ap_limit_mm": round(ap_lim, 3),
            "cutting_ap_mm": round(ap, 3),
            "tooth_passing_freq_hz": round(tooth_passing_freq, 3),
            "natural_frequency_hz": round(f_n_hz, 3),
            "frequency_ratio": round(r, 3),
            "dynamic_magnification": round(dynamic_magnification, 3),
            "directional_coefficient": round(a_d, 4),
            "stability_component": round(stability_component, 3),
            "engagement_component": round(engagement_component, 3),
            "dynamic_component": round(dynamic_component, 3),
            "transition_component": round(transition_component, 3),
            "slenderness_component": round(slenderness_component, 3),
            "load_component": round(load_component, 3),
            "cutting_gate": round(cutting_gate, 3),
            "state_factor": round(state_factor, 3),
            "motion_risk_score": round(motion_score, 3),
            "motion_vibration_um": round(motion_total, 3),
            "cutting_vibration_um": round(cutting_total, 3),
            "chatter_raw_score": round(chatter_raw_score, 3),
            "chatter_probability": round(chatter_probability, 3),
            **motion_debug,
        }

        return ChatterRiskPrediction(
            chatter_risk_score=chatter_probability,
            chatter_raw_score=chatter_raw_score,
            motion_risk_score=motion_score,
            stability_margin=float(stability_margin),
            ap_limit=float(ap_lim),
            tooth_passing_freq_hz=float(tooth_passing_freq),
            dynamic_magnification=float(dynamic_magnification),
            vibration_x_um=float(combined_axes[0]),
            vibration_y_um=float(combined_axes[1]),
            vibration_z_um=float(combined_axes[2]),
            resultant_vibration_um=combined_total,
            motion_vibration_um=motion_total,
            cutting_vibration_um=cutting_total,
            risk_factors=risk_factors,
        )

    def _predict_motion_vibration(
        self,
        features: CuttingFeatures,
        params: dict,
    ) -> tuple[np.ndarray, float, float, dict]:
        """급속/공중이송 및 과도 상태의 모션 유발 진동을 계산합니다."""

        machine_stiffness = float(max(params.get("machine_stiffness", 1.0), 0.2))
        zeta = float(np.clip(params.get("zeta", 0.03), 0.005, 0.25))
        rapid_sensitivity = float(max(params.get("rapid_vibration_sensitivity", 1.0), 0.2))
        jerk_sensitivity = float(max(params.get("servo_jerk_sensitivity", 1.0), 0.2))

        state_scale = {
            STATE_RAPID: 1.00,
            STATE_AIR_FEED: 0.34,
            STATE_PLUNGE: 0.48,
            STATE_ENTRY_CUT: 0.42,
            STATE_EXIT_CUT: 0.38,
        }.get(features.machining_state, 0.30)

        corner_factor = math.sin(math.radians(min(features.direction_change_deg, 180.0)) * 0.5)
        slenderness_ratio = features.tool_overhang_mm / max(features.tool_diameter_mm, 0.1)
        overhang_factor = 1.0 + max(0.0, slenderness_ratio - 3.0) * 0.15
        rigidity_factor = float(max(features.tool_rigidity_factor, 0.2))
        shock_factor = float(max(features.tool_rapid_shock_factor, 0.2))

        base_motion = 0.20 + 1.60 * (features.speed_ratio ** 1.4)
        accel_motion = 4.80 * features.acceleration_proxy * rapid_sensitivity
        jerk_motion = 3.80 * features.jerk_proxy * jerk_sensitivity
        corner_motion = 2.60 * corner_factor * features.speed_ratio

        total_motion = (base_motion + accel_motion + jerk_motion + corner_motion)
        total_motion *= state_scale * shock_factor
        total_motion *= (1.0 / math.sqrt(machine_stiffness * rigidity_factor))
        total_motion *= 1.0 / max(0.60 + 9.0 * zeta, 0.20)
        total_motion *= overhang_factor
        total_motion = float(np.clip(total_motion, 0.0, 45.0))

        axis_weights = np.array(
            [
                0.22 + 0.78 * features.axis_ratio_x,
                0.22 + 0.78 * features.axis_ratio_y,
                0.18 + 0.82 * features.axis_ratio_z + 0.10 * features.acceleration_proxy,
            ],
            dtype=float,
        )
        axis_norm = float(np.linalg.norm(axis_weights))
        if axis_norm <= 1e-9:
            axis_weights = np.array([1.0, 0.0, 0.0], dtype=float)
            axis_norm = 1.0
        axis_scales = axis_weights / axis_norm
        axes = total_motion * axis_scales

        motion_score_base = (
            0.42 * features.speed_ratio
            + 0.30 * features.acceleration_proxy
            + 0.18 * features.jerk_proxy
            + 0.10 * min(features.direction_change_deg / 90.0, 1.0)
        )
        motion_score = float(np.clip(_sigmoid(4.6 * (motion_score_base - 0.42)), 0.0, 1.0))

        return axes, float(np.linalg.norm(axes)), motion_score, {
            "speed_ratio": round(features.speed_ratio, 3),
            "speed_change_ratio": round(features.speed_change_ratio, 3),
            "acceleration_proxy": round(features.acceleration_proxy, 3),
            "jerk_proxy": round(features.jerk_proxy, 3),
            "corner_factor": round(corner_factor, 3),
        }

    @staticmethod
    def _predict_cutting_vibration(
        load_pred: SpindleLoadPrediction,
        k_eff: float,
        dynamic_magnification: float,
    ) -> np.ndarray:
        """절삭력 기반 축별 진동을 계산합니다."""

        vib_x = float(np.clip((abs(load_pred.force_x) / k_eff) * dynamic_magnification * 1000.0, 0.0, 5000.0))
        vib_y = float(np.clip((abs(load_pred.force_y) / k_eff) * dynamic_magnification * 1000.0, 0.0, 5000.0))
        vib_z = float(np.clip((abs(load_pred.force_z) / (k_eff * 2.8)) * dynamic_magnification * 1000.0, 0.0, 5000.0))
        return np.array([vib_x, vib_y, vib_z], dtype=float)

    @staticmethod
    def _state_chatter_factor(machining_state: str) -> float:
        """가공 상태별 채터 가중치"""

        if machining_state == STATE_PLUNGE:
            return 0.72
        if machining_state == STATE_ENTRY_CUT:
            return 1.08
        if machining_state == STATE_EXIT_CUT:
            return 0.80
        return 1.0
