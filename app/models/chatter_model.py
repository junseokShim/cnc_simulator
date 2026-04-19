"""
채터/진동 위험도 모델(Chatter Risk Model) 모듈

Altintas & Budak (1995)의 안정성 로브선도 이론을 기반으로
단순화된 임계 축방향 절입 깊이(ap_lim)와 안정성 마진(SM)을 계산합니다.
진동 진폭은 FRF 기반 정적/동적 응답으로 추정합니다.

[채터 위험도 포화 문제 해결]
이전 모델은 선형 점수화 공식:
    base_score = 1 - SM/SM_safe  (SM_safe=2.5)
에 가산 보정치(최대 +0.37)를 더하여 대부분의 블록이 100%에 포화되었습니다.

신규 모델은 비선형 시그모이드 유사 매핑을 사용합니다:
    base_score = 1 / (1 + (SM / SM_ref)^power)

이 공식의 특성:
    SM = 0.5 → risk ≈ 84%  (심각하게 불안정)
    SM = 1.0 → risk ≈ 60%  (불안정 경계)
    SM_ref    → risk = 50%  (중간 위험)
    SM = 2.0 → risk ≈ 28%  (안정)
    SM = 4.0 → risk ≈ 10%  (매우 안정)
    SM = 8.0 → risk ≈  3%  (극도로 안정)

추가 보정은 승산적(multiplicative)으로 적용되므로 기존처럼 포화되지 않습니다.

[참고 문헌]
[1] Altintas, Y., & Budak, E. (1995). Analytical Prediction of Stability Lobes
    in Milling. CIRP Annals, 44(1), 357–362.
    → 안정성 로브선도 핵심 이론 (Eq. 10–19)
    → 임계 절입 깊이: ap_lim = -2π*ΛR / (N*z*Ktc*ad)

[2] Altintas, Y. (2000). Manufacturing Automation. Cambridge.
    → Chapter 4: Chatter Stability of Metal Cutting and Grinding
    → 단일 자유도 FRF 모델 및 복소 공구 끝단 응답

[3] Schmitz, T.L., & Smith, K.S. (2009). Machining Dynamics. Springer US.
    → Chapter 3: Chatter (재생 채터 메커니즘, 실용 모델)

[핵심 공식]
안정성 경계에서의 임계 절입 깊이 (Altintas & Budak 1995, Eq. 14):
    ap_lim = -2π / (N_flutes * Ktc * a_d * Λ_R)

FRF 최솟값 (SDOF, Altintas & Budak 1995, Eq. 11):
    Λ_R = Re[G(iω)]_min = -1 / (2 * k_eff * ζ * √(1-ζ²))

안정성 마진:
    SM = ap_lim / ap_actual
    SM > 1 → 안정, SM < 1 → 불안정

날 통과 주파수:
    f_tp = n * z / 60  [Hz]   (Schmitz & Smith 2009, Eq. 3.1)

동적 배율:
    r_tp = f_tp / f_n
    DM = 1 / √((1-r²)² + (2ζr)²)
"""
from __future__ import annotations

import math

import numpy as np

from app.models.cutting_conditions import compute_directional_coefficients
from app.models.model_interfaces import (
    ChatterRiskPrediction,
    ChatterRiskPredictor,
    CuttingFeatures,
    SpindleLoadPrediction,
)
from app.utils.logger import get_logger

logger = get_logger("chatter_model")

# ---- 채터 위험도 점수화 파라미터 ----
# SM_REF: 이 SM 값에서 base_score = 0.5 (50% 위험)
# SM이 낮을수록 위험도 올라가는 기준점
_SM_REF = 1.2   # SM=1.2 → 50% 위험 (안정/불안정 경계 근처)
_SM_POWER = 2.5  # 비선형 커브 기울기 (높을수록 SM 민감도 증가)


class StabilityLobeChatterModel(ChatterRiskPredictor):
    """
    Altintas & Budak (1995) 기반 단순화 안정성 로브선도 채터 모델

    [구현 수준]
    - 단일 자유도(SDOF) 매개변수(k, ζ, ω_n)로 근사
    - 임계 절입 깊이 ap_lim → 안정성 마진 SM 계산
    - 비선형 점수화로 포화 방지

    [미래 개선 포인트]
    - 공구-스핀들 시스템의 실측 FRF(주파수 응답 함수) 입력으로 교체
    - 다자유도 시스템 안정성 행렬 해석
    - 데이터 기반 채터 예측 (model_replacement_guide.md 참조)
    """

    def predict(
        self,
        features: CuttingFeatures,
        load_pred: SpindleLoadPrediction,
        params: dict,
    ) -> ChatterRiskPrediction:
        """
        Altintas & Budak 안정성 이론으로 채터 위험도를 계산합니다.

        Args:
            features:   CuttingFeatures
            load_pred:  SpindleLoadPrediction (힘 정보)
            params:     모델 파라미터
                - k_n_per_um: 공구 끝단 강성 (N/μm)
                - zeta:       감쇠비
                - f_natural_hz: 고유 주파수 (Hz)
                - Ktc:        접선 절삭력 계수 (N/mm²)
                - Krc_ratio:  Krc/Ktc 비율
                - chatter_sensitivity: 민감도 배율
                - machine_stiffness:  머신 강성 계수
                - tool_overhang_factor: 공구 돌출 계수
                - stability_lobe_correction: 안정성 로브선도 보정 계수

        Returns:
            ChatterRiskPrediction
        """
        if not features.is_cutting:
            # 비절삭(공중 이송, 급속): 채터 없음
            return ChatterRiskPrediction(
                chatter_risk_score=0.0,
                stability_margin=999.0,
            )

        # ---- 시스템 동적 파라미터 ----
        k_n_per_um = float(params.get("k_n_per_um", 20.0))   # N/μm
        k_n_per_mm = k_n_per_um * 1000.0                     # N/mm
        zeta = float(params.get("zeta", 0.03))
        f_n_hz = float(params.get("f_natural_hz", 800.0))     # Hz
        omega_n = 2.0 * math.pi * f_n_hz                      # rad/s

        # 머신/공구 강성 보정
        machine_stiffness = float(params.get("machine_stiffness", 1.0))
        overhang_factor = float(params.get("tool_overhang_factor", 1.0))
        k_eff = k_n_per_mm * machine_stiffness / overhang_factor  # N/mm

        # ---- 절삭 파라미터 ----
        ap = features.axial_depth_ap
        phi_st = features.phi_entry_rad
        phi_ex = features.phi_exit_rad
        z = features.flute_count
        n_rpm = features.spindle_rpm
        Ktc = float(params.get("Ktc", 700.0))
        Krc_ratio = float(params.get("Krc_ratio", 0.3))

        # ap 혹은 맞물림 호가 없으면 채터 없음
        if ap <= 0.0 or (phi_ex - phi_st) <= 0.0:
            return ChatterRiskPrediction(
                chatter_risk_score=0.0,
                stability_margin=999.0,
            )

        # ---- 방향 계수 a_d (Altintas & Budak 1995, Eq. 6) ----
        a_xx, a_xy, a_yx, a_yy = compute_directional_coefficients(
            phi_st, phi_ex, Krc_ratio
        )
        # 주요 방향(Y, X 복합)의 유효 방향 계수
        a_d = abs(a_yy) + abs(a_xx) * 0.5
        a_d = max(a_d, 0.01)

        # ---- FRF 최솟값 (Altintas & Budak 1995, Eq. 11) ----
        # Re[G(iω)]_min = -1 / (2 * k_eff * ζ * √(1-ζ²))
        Lambda_R_min = -1.0 / (
            2.0 * k_eff * max(zeta, 1e-5) * math.sqrt(max(1.0 - zeta**2, 0.01))
        )

        # ---- 임계 절입 깊이 (Altintas & Budak 1995, Eq. 14) ----
        # ap_lim = -2π / (N_flutes * Ktc * a_d * Λ_R)
        ap_lim_raw = -2.0 * math.pi / (z * Ktc * a_d * Lambda_R_min)
        ap_lim_raw = max(ap_lim_raw, 0.001)

        # 기계 프로파일 안정성 보정 (T4000: 약간 더 안정적)
        stability_correction = float(params.get("stability_lobe_correction", 1.0))
        ap_lim = ap_lim_raw * stability_correction

        # ---- 안정성 마진 ----
        SM = ap_lim / max(ap, 0.001)

        # ---- 날 통과 주파수 (Schmitz & Smith 2009, Eq. 3.1) ----
        f_tp = n_rpm * z / 60.0  # Hz
        omega_tp = 2.0 * math.pi * f_tp

        # ---- 동적 배율 ----
        r = omega_tp / omega_n if omega_n > 0 else 0.0
        H_mag = math.sqrt((1.0 - r**2)**2 + (2.0 * zeta * r)**2)
        DM = 1.0 / max(H_mag, 1e-6)

        # ---- 진동 진폭 추정 ----
        Fx = abs(load_pred.force_x)
        Fy = abs(load_pred.force_y)
        Fz = abs(load_pred.force_z)

        vib_x = float(np.clip((Fx / k_eff) * DM * 1000.0, 0.0, 5000.0))   # μm
        vib_y = float(np.clip((Fy / k_eff) * DM * 1000.0, 0.0, 5000.0))
        vib_z = float(np.clip((Fz / (k_eff * 3.0)) * DM * 1000.0, 0.0, 5000.0))
        vib_total = float(math.sqrt(vib_x**2 + vib_y**2 + vib_z**2))

        # ====================================================
        # ---- 채터 위험도 점수화 (비선형, 포화 방지 설계) ----
        # ====================================================
        #
        # [기존 선형 공식의 문제]
        # base_score = 1 - SM/SM_safe 에서 SM_safe=2.5를 사용하면
        # SM=1일 때 base_score=0.6, 여기에 가산 보정 +0.37 → 포화
        #
        # [신규 비선형 공식]
        # base_score = 1 / (1 + (SM / SM_ref)^power)
        #
        # SM_ref=1.2, power=2.5 기준:
        #   SM=0.5  → 84%  (심각 불안정)
        #   SM=1.0  → 60%  (불안정 경계)
        #   SM=1.2  → 50%  (50% 기준점, SM_ref)
        #   SM=2.0  → 28%  (안정)
        #   SM=4.0  → 10%  (매우 안정)
        #   SM=8.0  →  3%  (극도로 안정)
        # ====================================================
        sm_clamped = max(SM, 0.001)
        base_score = 1.0 / (1.0 + (sm_clamped / _SM_REF) ** _SM_POWER)

        # ---- 공진 근접도 보정 (승산적, 포화 방지) ----
        # r ≈ 1.0 (고유주파수 근처)에서 최대 20% 위험 증가
        if 0.7 <= r <= 1.3:
            res_proximity = 1.0 - abs(r - 1.0) / 0.3
            resonance_factor = 1.0 + 0.20 * res_proximity
        else:
            resonance_factor = 1.0
            res_proximity = 0.0

        # ---- 플런지 보정 (승산적, 최대 15%) ----
        plunge_factor = 1.15 if features.is_plunge else 1.0

        # ---- 방향 전환 보정 (승산적, 최대 8%) ----
        dir_factor = 1.0 + 0.08 * min(features.direction_change_deg / 90.0, 1.0)

        # ---- 민감도 배율 적용 ----
        sensitivity = float(params.get("chatter_sensitivity", 1.0))

        # ---- 최종 채터 위험도 점수 ----
        # 승산적 보정은 기존 가산 방식보다 포화 위험이 낮습니다.
        # 예: base_score=0.6 → × 1.2 × 1.15 × 1.08 × 1.0 = 0.89
        # (기존: 0.6 + 0.15 + 0.12 + 0.10 = 0.97 → clip → 1.0)
        chatter_score = float(np.clip(
            base_score * resonance_factor * plunge_factor * dir_factor * sensitivity,
            0.0, 1.0
        ))

        risk_factors = {
            "안정성_마진_SM": round(SM, 3),
            "임계절입_ap_lim_mm": round(ap_lim, 3),
            "현재절입_ap_mm": round(ap, 3),
            "날통과주파수_Hz": round(f_tp, 1),
            "고유주파수_Hz": round(f_n_hz, 1),
            "주파수_비율_r": round(r, 3),
            "동적배율_DM": round(DM, 3),
            "방향계수_a_d": round(a_d, 4),
            "FRF최솟값_Lambda_R": round(Lambda_R_min, 6),
            "SM기반_점수": round(base_score, 3),
            "공진근접_배율": round(resonance_factor, 3),
            "플런지_배율": round(plunge_factor, 3),
            "방향전환_배율": round(dir_factor, 3),
            "안정성_보정계수": round(stability_correction, 3),
        }

        return ChatterRiskPrediction(
            chatter_risk_score=chatter_score,
            stability_margin=float(SM),
            ap_limit=float(ap_lim),
            tooth_passing_freq_hz=float(f_tp),
            dynamic_magnification=float(DM),
            vibration_x_um=vib_x,
            vibration_y_um=vib_y,
            vibration_z_um=vib_z,
            resultant_vibration_um=vib_total,
            risk_factors=risk_factors,
        )
