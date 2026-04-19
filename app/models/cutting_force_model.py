"""
기계론적 절삭력 모델(Mechanistic Cutting Force Model) 모듈

Altintas의 기계론적 밀링 절삭력 모델을 구현합니다.
접선/반경/축방향 절삭력 계수(Ktc, Krc, Kac)와
날끝 절삭력 계수(Kte, Kre, Kae)를 사용하여
주축 1회전 평균 절삭력 및 토크/전력을 계산합니다.

[스핀들 부하 분해 구조]
비현실적 모델의 핵심 원인 중 하나는 공중 이송(G1 air-cut)에서도
절삭 수준의 스핀들 부하가 계산되던 것이었습니다.
이를 해결하기 위해 스핀들 부하를 다음 세 성분으로 분해합니다:

  total_load = baseline_component + axis_motion_component + cutting_component

  baseline_component:
    스핀들이 회전만 해도 발생하는 무부하 손실
    (베어링 마찰, 냉각팬, 윤활 펌프 등)
    → 비절삭(공중 이송) 시에도 발생
    → 공기 절삭 G1: ~7% (T4000 기준)

  axis_motion_component:
    이송 축 구동에 의한 추가 전력 소비
    이송 속도 / 최대 급속 이송 비율로 추정
    → 공기 절삭 G1 (F3000): ~1-2% 추가

  cutting_component:
    Altintas 기계론적 절삭력 → 토크 → 전력 변환
    is_cutting=True 이고 실제 소재 접촉 시에만 발생
    → 공중 이송 시 0

결과:
  - 공중 G1 이송: ~8~10% (baseline + 소량 axis)
  - 실제 절삭: 20~80% (재료, 조건에 따라)
  → 공중 이송이 절삭보다 높은 부하를 보이는 현상 해결됨

[참고 문헌]
[1] Altintas, Y. (2000). Manufacturing Automation. Cambridge University Press.
    → Chapter 2: Mechanics of Metal Cutting (평균 절삭력 공식, Eq. 2.1–2.28)
[2] Altintas, Y., & Budak, E. (1995). Analytical Prediction of Stability Lobes.
    CIRP Annals, 44(1), 357–362.
[3] Kao, Y.-C. et al. (2015). A prediction method of cutting force coefficients.
    International Journal of Advanced Manufacturing Technology, 77, 1–11.
[4] Merchant, M.E. (1945). Mechanics of the Metal Cutting Process.
    Journal of Applied Physics, 16(5), 267–275.

[핵심 공식]
단일 날의 미소 접선·반경·축방향 절삭력:
    dFt(φ) = Ktc * h(φ) * db + Kte * db
    h(φ) = fz * sin(φ)  [mm]  순간 칩 두께 (Altintas 2000, Eq. 2.1)
    db    = ap           [mm]  미소 날 높이

z개 날 1회전(2π) 평균:
    Ft_avg = z/(2π) * ap * [Ktc*fz*(cos(φ_st)-cos(φ_ex)) + Kte*(φ_ex-φ_st)]
"""
from __future__ import annotations

import math
from typing import Dict

import numpy as np

from app.models.cutting_conditions import compute_directional_coefficients
from app.models.model_interfaces import (
    CuttingFeatures,
    SpindleLoadPrediction,
    SpindleLoadPredictor,
)
from app.utils.logger import get_logger

logger = get_logger("cutting_force_model")


# ============================================================
# 재료별 절삭력 계수 데이터베이스
# ============================================================
# 출처: Altintas (2000) Table 2.1, 제조사 카탈로그 측정 평균값
# 단위: Ktc, Krc, Kac [N/mm²],  Kte, Kre, Kae [N/mm]
MATERIAL_FORCE_COEFFICIENTS: Dict[str, dict] = {
    "aluminum": {
        "name": "알루미늄 합금 (Al 6061/7075)",
        "Ktc": 700.0,   # 접선 절삭력 계수 (N/mm²)
        "Krc": 210.0,   # 반경 절삭력 계수 (N/mm²), ≈ 0.3 * Ktc
        "Kac": 84.0,    # 축방향 절삭력 계수 (N/mm²), ≈ 0.12 * Ktc
        "Kte": 22.0,    # 접선 날끝 계수 (N/mm)
        "Kre": 8.0,     # 반경 날끝 계수 (N/mm)
        "Kae": 2.0,     # 축방향 날끝 계수 (N/mm)
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
        "name": "회주철 (GC250)",
        "Ktc": 1100.0,
        "Krc": 330.0,
        "Kac": 110.0,
        "Kte": 30.0,
        "Kre": 12.0,
        "Kae": 4.0,
        "Krc_ratio": 0.30,
    },
    "default": {
        "name": "일반 금속 (기본값)",
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
    """
    Altintas 기계론적 밀링 절삭력 모델

    [부하 분해 설계]
    is_cutting=False (공중 이송 포함):
        → baseline_load + axis_motion_load (절삭 성분 없음)
        → 공중 이송 G1: 대략 8~12% (T4000 기준)
        → G0 급속이지만 스핀들 ON: 7% 기저 + 소량 axis

    is_cutting=True (실제 소재 접촉):
        → baseline_load + axis_motion_load + cutting_load
        → 알루미늄 전형 절삭: 15~60%
        → 스틸 전형 절삭: 30~80%

    이 분해 구조가 "공중 이송이 절삭보다 높은 부하"를 방지합니다.

    [구현된 공식]
    Altintas (2000) Chapter 2, Eq. 2.15–2.26:

    주축 1회전 평균 접선 절삭력:
        <Ft> = z*ap/(2π) * [Ktc*fz*(cos(φ_st)-cos(φ_ex)) + Kte*(φ_ex-φ_st)]

    토크:  T = <Ft> * D/2    [N·mm → N·m]
    전력:  P = <Ft> * Vc / 60  [W]  (Vc in m/min)
    """

    def predict(
        self,
        features: CuttingFeatures,
        params: dict,
    ) -> SpindleLoadPrediction:
        """
        CuttingFeatures로부터 SpindleLoadPrediction을 계산합니다.

        Args:
            features: CuttingFeatures (절삭 조건)
            params:   모델 파라미터 딕셔너리
                      - material: 재료 키
                      - spindle_rated_power_w: 정격 출력 (W)
                      - machine_efficiency: 기계 효율 (0~1)
                      - baseline_power_ratio: 무부하 기저 전력비
                      - axis_motion_power_ratio: 축 이송 전력비
                      - rapid_traverse_mm_min: 최대 급속 이송 (mm/min)

        Returns:
            SpindleLoadPrediction (분해된 부하 성분 포함)
        """
        P_rated = float(params.get("spindle_rated_power_w", 7500.0))
        eta = float(params.get("machine_efficiency", 0.85))
        baseline_ratio = float(params.get("baseline_power_ratio", 0.07))
        axis_ratio = float(params.get("axis_motion_power_ratio", 0.04))
        rapid_traverse = float(params.get("rapid_traverse_mm_min", 36000.0))

        # ---- 기저(무부하) 전력 ----
        # 스핀들이 회전하기만 해도 발생 (베어링, 냉각팬, 윤활 등)
        P_baseline = 0.0
        if features.spindle_rpm > 0:
            P_baseline = baseline_ratio * P_rated  # 예: 7% × 7500W = 525W

        # ---- 축 이송 전력 ----
        # 이송 속도 / 최대 급속 이송 비율로 추정
        feedrate_ratio = min(features.feedrate / max(rapid_traverse, 1.0), 1.0)
        P_axis = axis_ratio * P_rated * feedrate_ratio  # 예: 4% × ratio × 7500W

        # ---- 비절삭 (공중 이송 or 급속) ----
        if not features.is_cutting:
            # 절삭 성분 없음, baseline + axis만
            P_total = (P_baseline + P_axis) / eta
            total_load = float(np.clip(P_total / P_rated * 100.0, 0.0, 25.0))

            baseline_load = P_baseline / P_rated * 100.0
            axis_load = P_axis / P_rated * 100.0

            return SpindleLoadPrediction(
                spindle_load_pct=total_load,
                baseline_load_pct=baseline_load,
                axis_motion_load_pct=axis_load,
                cutting_load_pct=0.0,
                # 절삭력 성분 모두 0
                cutting_force_ft=0.0,
                cutting_force_fr=0.0,
                cutting_force_fa=0.0,
                force_x=0.0,
                force_y=0.0,
                force_z=0.0,
                torque_nm=0.0,
                power_w=P_total,
                mrr=0.0,
                aggressiveness=0.0,
            )

        # ---- 절삭 중 ----
        # 재료 계수 로드
        mat = params.get("material", "default")
        coeff = MATERIAL_FORCE_COEFFICIENTS.get(mat, MATERIAL_FORCE_COEFFICIENTS["default"])

        Ktc = float(params.get("Ktc_override", coeff["Ktc"]))
        Krc = float(params.get("Krc_override", coeff["Krc"]))
        Kac = float(params.get("Kac_override", coeff["Kac"]))
        Kte = float(params.get("Kte_override", coeff["Kte"]))
        Kre = float(params.get("Kre_override", coeff["Kre"]))
        Kae = float(params.get("Kae_override", coeff["Kae"]))
        Krc_ratio = Krc / Ktc if Ktc > 0 else 0.3

        phi_st = features.phi_entry_rad
        phi_ex = features.phi_exit_rad
        delta_phi = phi_ex - phi_st
        cos_diff = math.cos(phi_st) - math.cos(phi_ex)

        ap = features.axial_depth_ap
        fz = features.feed_per_tooth_fz
        z = features.flute_count
        D = features.tool_diameter
        Vc = features.cutting_speed_vc  # m/min

        # 맞물림 호 없으면 절삭 없음 (방어 코드)
        if delta_phi <= 0.0 or ap <= 0.0 or fz <= 0.0:
            P_total = (P_baseline + P_axis) / eta
            total_load = float(np.clip(P_total / P_rated * 100.0, 0.0, 25.0))
            return SpindleLoadPrediction(
                spindle_load_pct=total_load,
                baseline_load_pct=P_baseline / P_rated * 100.0,
                axis_motion_load_pct=P_axis / P_rated * 100.0,
                cutting_load_pct=0.0,
                power_w=P_total,
            )

        # ---- 주축 1회전 평균 접선 절삭력 (Altintas 2000, Eq. 2.15) ----
        Ft = (z * ap / (2 * math.pi)) * (Ktc * fz * cos_diff + Kte * delta_phi)
        Fr = (z * ap / (2 * math.pi)) * (Krc * fz * cos_diff + Kre * delta_phi)
        Fa = (z * ap / (2 * math.pi)) * (Kac * fz * cos_diff + Kae * delta_phi)

        # 플런지 보정: Z방향 절삭이 주력
        if features.is_plunge:
            Fa_plunge = (z * ap / (2 * math.pi)) * (Kac * fz * math.pi + Kae * math.pi)
            Ft = Ft * 0.4
            Fr = Fr * 0.4
            Fa = Fa_plunge

        # 음수 방지
        Ft = max(0.0, Ft)
        Fr = max(0.0, Fr)
        Fa = max(0.0, Fa)

        # ---- X/Y/Z 방향 합력 (방향 계수 이용, Altintas 2000, Eq. 2.23) ----
        a_xx, a_xy, a_yx, a_yy = compute_directional_coefficients(phi_st, phi_ex, Krc_ratio)
        phi_mid = (phi_st + phi_ex) / 2.0

        b_xx = -math.cos(phi_mid) * delta_phi
        b_xy = math.sin(phi_mid) * delta_phi

        Fx = (z * ap * fz / (4 * math.pi)) * (Ktc * a_xx + Krc * a_xy)
        Fx += (z * ap / (2 * math.pi)) * (Kte * b_xx + Kre * b_xy)
        Fy = (z * ap * fz / (4 * math.pi)) * (Ktc * a_yx + Krc * a_yy)
        Fy += (z * ap / (2 * math.pi)) * (Kte * (-b_xy) + Kre * b_xx)
        Fz = Fa

        # ---- 토크 및 절삭 전력 (Altintas 2000, Eq. 2.17) ----
        T_nmm = Ft * (D / 2.0)
        T_nm = T_nmm / 1000.0  # N·m
        P_cutting_raw = Ft * Vc / 60.0  # W (Ft[N] × Vc[m/min] / 60)
        P_cutting = P_cutting_raw / eta  # 효율 보정

        # ---- 총 스핀들 전력 및 부하 분해 ----
        P_total = P_baseline + P_axis + P_cutting

        baseline_load = P_baseline / P_rated * 100.0
        axis_load = P_axis / P_rated * 100.0
        cutting_load = P_cutting / P_rated * 100.0

        # 총 부하 (과부하 150%까지 허용)
        total_load = float(np.clip(P_total / P_rated * 100.0, 0.0, 150.0))

        # ---- 절삭 공격성 점수 (MRR 기반) ----
        MRR = features.mrr_mm3_per_min
        mrr_ref = float(params.get("mrr_reference_mm3min", 50000.0))
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
            power_w=P_total,
            mrr=MRR,
            aggressiveness=aggressiveness,
            baseline_load_pct=baseline_load,
            axis_motion_load_pct=axis_load,
            cutting_load_pct=float(np.clip(cutting_load, 0.0, 150.0)),
        )
