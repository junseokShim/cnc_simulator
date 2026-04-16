"""
3축 가공 수치 모델(Machining Model) 모듈

3축 CNC 밀링 가공에 대한 공학적 근사 수치 모델을 구현합니다.

[구현된 모델]
1. 절삭 조건 계산: 절삭 속도, 날당 이송량, 맞물림 깊이 추정
2. Kienzle 단순화 절삭력 모델: 접선 절삭력 추정
3. 스핀들 부하 추정: 절삭력 → 소비 전력 → 정규화 부하
4. 채터/진동 위험도 휴리스틱 모델: 복합 위험 인자 가중 합산

[주요 가정 및 한계]
- 축방향 절입 깊이(ap): Z방향 이동에서 추정, 없으면 직전 절입값 사용
- 반경방향 맞물림(ae): 공구 직경 비율로 근사 (실제 재료 경계 계산 미적용)
- Kienzle 모델 계수: 알루미늄 기준 기본값, 설정으로 조정 가능
- 안정성 해석: 전체 안정성 로브선도 미적용, 휴리스틱 위험도 근사
- 5축 확장 미지원: 현재 3축(XYZ) 이동만 처리

향후 개선 방향:
- 재료별 Kc, mc 계수 데이터베이스 추가
- 공구별 동적 특성 계수 추가
- Z-맵 기반 맞물림 실제 계산
- 안정성 로브선도 기반 채터 예측
"""
from __future__ import annotations
import math
import logging
from typing import List, Dict, Optional, Tuple
import numpy as np

from app.models.toolpath import Toolpath, MotionSegment, MotionType
from app.models.tool import Tool, ToolType
from app.models.machining_result import (
    SegmentMachiningResult, MachiningAnalysis, ChatterRiskLevel
)
from app.utils.logger import get_logger

logger = get_logger("machining_model")


# ============================================================
# 기본 재료 절삭 계수 (Kienzle 모델)
# ============================================================
# 재료별 절삭 계수 사전
# Kc1: 날당이송 1mm 시 비절삭저항 (N/mm²)
# mc:  날당이송 지수 (무차원)
# 출처: 공구 카탈로그 및 기계가공 공학 교재 참고값
MATERIAL_COEFFICIENTS = {
    "aluminum":      {"Kc1": 700.0,  "mc": 0.25, "name": "알루미늄 합금"},
    "steel_mild":    {"Kc1": 1800.0, "mc": 0.26, "name": "저탄소강"},
    "steel_hard":    {"Kc1": 2500.0, "mc": 0.28, "name": "경화강"},
    "stainless":     {"Kc1": 2200.0, "mc": 0.27, "name": "스테인리스강"},
    "titanium":      {"Kc1": 2000.0, "mc": 0.30, "name": "티타늄 합금"},
    "cast_iron":     {"Kc1": 1100.0, "mc": 0.23, "name": "주철"},
    "default":       {"Kc1": 1500.0, "mc": 0.26, "name": "일반 금속 (기본값)"},
}


class MachiningModelConfig:
    """
    가공 수치 모델의 설정 파라미터 클래스

    모델의 계수와 가정값을 설정합니다.
    모든 파라미터는 설정 파일(simulation_options.yaml)에서 읽어올 수 있습니다.
    """

    def __init__(self, config_dict: Optional[dict] = None):
        cfg = config_dict or {}

        # ---- 재료 설정 ----
        # 가공 재료 (MATERIAL_COEFFICIENTS 키 중 하나)
        self.material: str = cfg.get("material", "aluminum")

        # ---- 머신/공구 특성 계수 ----
        # 머신 강성 계수 (1.0 = 표준, 낮을수록 채터 위험 증가)
        self.machine_stiffness: float = float(cfg.get("machine_stiffness", 1.0))
        # 공구 돌출 계수 (1.0 = 표준 L/D < 3, 높을수록 채터 위험 증가)
        self.tool_overhang_factor: float = float(cfg.get("tool_overhang_factor", 1.0))
        # 스핀들 정격 출력 (W) - 부하 백분율 계산 기준
        self.spindle_rated_power_w: float = float(cfg.get("spindle_rated_power_w", 7500.0))

        # ---- 기본 절삭 조건 가정값 ----
        # 기본 반경방향 맞물림 비율 (ae/D), 평면 절삭 기준
        self.default_ae_ratio: float = float(cfg.get("default_ae_ratio", 0.5))
        # 기본 축방향 절입 깊이 (mm), Z변화가 없을 때 사용
        self.default_ap_mm: float = float(cfg.get("default_ap_mm", 2.0))
        # 기본 날 수 (공구 정의 없을 때 사용)
        self.default_flute_count: int = int(cfg.get("default_flute_count", 4))

        # ---- 채터 위험도 모델 파라미터 ----
        # 채터 민감도 배율 (1.0 = 표준)
        self.chatter_sensitivity: float = float(cfg.get("chatter_sensitivity", 1.0))
        # 방향 변화 위험도 가중치
        self.w_direction_change: float = float(cfg.get("w_direction_change", 0.20))
        # 맞물림 깊이 위험도 가중치
        self.w_engagement: float = float(cfg.get("w_engagement", 0.35))
        # 절삭 속도 위험도 가중치
        self.w_speed: float = float(cfg.get("w_speed", 0.20))
        # 절입 위험도 가중치
        self.w_plunge: float = float(cfg.get("w_plunge", 0.25))

        # ---- 지수 평활화 (EMA) ----
        # 스핀들 부하 평활화 계수 (0~1, 클수록 덜 평활화)
        self.load_smoothing_alpha: float = float(cfg.get("load_smoothing_alpha", 0.3))

    def get_material_coeff(self) -> dict:
        """현재 재료의 Kienzle 계수를 반환합니다."""
        return MATERIAL_COEFFICIENTS.get(self.material, MATERIAL_COEFFICIENTS["default"])


class MachiningModel:
    """
    3축 CNC 밀링 가공 수치 모델 클래스

    각 NC 블록에 대해 절삭 조건, 스핀들 부하, 채터 위험도를 계산합니다.

    [알고리즘 개요]
    1. 각 세그먼트에 대해 절삭 조건을 추정합니다:
       - 절삭 속도: Vc = π*D*n/1000 (m/min)
       - 날당 이송량: fz = F/(n*z) (mm/tooth)
       - 축방향 절입: Z방향 이동에서 추정
       - 반경방향 맞물림: 공구 직경 비율로 근사

    2. Kienzle 단순화 모델로 절삭력을 추정합니다:
       - 단일 날 접선력: Fc_tooth = Kc1 * ap * fz^(1-mc) (N)
       - 총 접선력: Fc = Fc_tooth * ae/D * z (맞물림 보정)

    3. 스핀들 소비 전력에서 부하를 계산합니다:
       - 소비 전력: P = Fc * Vc / 60000 (kW)
       - 부하 비율: load% = P / P_rated * 100

    4. 복합 위험 인자로 채터 위험도를 계산합니다:
       - 맞물림 위험도, 속도 위험도, 방향 변화 위험도, 절입 위험도
    """

    def __init__(self, config: Optional[MachiningModelConfig] = None):
        self.config = config or MachiningModelConfig()
        # 이전 세그먼트의 스무딩된 부하값 (EMA)
        self._smoothed_load: float = 0.0
        # 직전 절입 깊이 추적 (Z 변화 없는 구간에서 사용)
        self._last_ap: float = self.config.default_ap_mm
        # 이전 세그먼트 이동 방향 벡터 (방향 변화 계산용)
        self._prev_direction: Optional[np.ndarray] = None
        # 이전 부하값 (부하 변동 계산용)
        self._prev_load: float = 0.0

    def analyze_toolpath(
        self,
        toolpath: Toolpath,
        tools: Dict[int, Tool],
    ) -> MachiningAnalysis:
        """
        전체 공구경로에 대해 가공 해석을 수행합니다.

        Args:
            toolpath: 해석할 공구경로
            tools: 공구 번호 → Tool 딕셔너리

        Returns:
            MachiningAnalysis: 세그먼트별 해석 결과 및 통계
        """
        logger.info(f"가공 수치 모델 해석 시작: {len(toolpath.segments)}개 세그먼트")

        # 상태 초기화
        self._smoothed_load = 0.0
        self._last_ap = self.config.default_ap_mm
        self._prev_direction = None
        self._prev_load = 0.0

        results: List[SegmentMachiningResult] = []
        material_coeff = self.config.get_material_coeff()

        for i, seg in enumerate(toolpath.segments):
            # 현재 세그먼트에 사용되는 공구 조회
            tool = tools.get(seg.tool_number)

            result = self._analyze_segment(seg, tool, material_coeff, i)
            results.append(result)

            # 다음 반복을 위한 상태 업데이트
            if seg.is_cutting_move:
                self._prev_load = result.spindle_load_pct

        # 분석 결과 컨테이너 생성 및 통계 계산
        analysis = MachiningAnalysis(
            results=results,
            model_params={
                "material": self.config.material,
                "Kc1": material_coeff["Kc1"],
                "mc": material_coeff["mc"],
                "spindle_rated_power_w": self.config.spindle_rated_power_w,
                "default_ae_ratio": self.config.default_ae_ratio,
                "default_ap_mm": self.config.default_ap_mm,
                "machine_stiffness": self.config.machine_stiffness,
                "tool_overhang_factor": self.config.tool_overhang_factor,
            }
        )
        analysis.compute_statistics()

        # 총 재료 제거량 근사값 계산
        dt_min = 1.0 / 60.0  # 임의 시간 기준
        analysis.total_mrr = sum(
            r.material_removal_rate * (seg.get_distance() / max(seg.feedrate, 1.0))
            for r, seg in zip(results, toolpath.segments)
            if r.is_cutting and seg.feedrate > 0
        )

        logger.info(
            f"가공 해석 완료: 최대 부하={analysis.max_spindle_load_pct:.1f}%, "
            f"최대 채터위험={analysis.max_chatter_risk*100:.1f}%, "
            f"고위험 구간={analysis.high_risk_segment_count}개"
        )
        return analysis

    def _analyze_segment(
        self,
        seg: MotionSegment,
        tool: Optional[Tool],
        material_coeff: dict,
        segment_index: int,
    ) -> SegmentMachiningResult:
        """
        단일 세그먼트에 대해 가공 해석을 수행합니다.

        급속 이동(RAPID)의 경우 절삭 없음으로 처리합니다.
        """
        is_cutting = seg.is_cutting_move

        # 공구 파라미터 추출
        if tool is not None:
            D = tool.diameter
            z = tool.flute_count
        else:
            D = 10.0  # 기본 공구 직경 (mm)
            z = self.config.default_flute_count

        n = seg.spindle_speed   # RPM
        F = seg.feedrate        # mm/min

        # ---- 기본 절삭 조건 계산 ----
        # 절삭 속도 Vc (m/min)
        Vc = math.pi * D * n / 1000.0 if n > 0 else 0.0

        # 날당 이송량 fz (mm/tooth)
        fz = F / (n * z) if n > 0 and z > 0 else 0.0

        # ---- 절입 깊이 추정 ----
        delta_z = seg.end_pos[2] - seg.start_pos[2]
        is_plunge = delta_z < -0.01 and is_cutting  # Z 하강 절삭
        is_ramp = (abs(delta_z) > 0.01 and
                   np.linalg.norm(seg.end_pos[:2] - seg.start_pos[:2]) > 0.01 and
                   is_cutting)

        # 축방향 절입 깊이 ap 추정
        if is_plunge:
            ap = abs(delta_z)
            self._last_ap = ap  # 다음 수평 절삭에서 재사용
        elif is_ramp:
            ap = abs(delta_z) * 0.7  # 경사 절입: Z 성분의 70%
            self._last_ap = max(ap, self.config.default_ap_mm)
        elif is_cutting:
            ap = self._last_ap  # 수평 절삭: 직전 절입 깊이 유지
        else:
            ap = 0.0

        # ---- 반경방향 맞물림 추정 ----
        # 현재 단순화 근사: 공구 직경의 기본 비율 사용
        # 향후 Z-맵 기반 실제 계산으로 교체 가능
        ae_ratio = self.config.default_ae_ratio if is_cutting else 0.0
        ae = D * ae_ratio

        # ---- 재료 제거율 (MRR) ----
        # MRR = ae * ap * F (mm³/min)
        MRR = ae * ap * F if is_cutting else 0.0

        # ---- Kienzle 단순화 절삭력 모델 ----
        # 단일 날 접선 절삭력: Fc_tooth = Kc1 * ap * fz^(1-mc)
        # 총 절삭력: 맞물린 날 수 보정 (ae/πD * z)
        Fc = 0.0
        if is_cutting and ap > 0 and fz > 0 and Vc > 0:
            Kc1 = material_coeff["Kc1"]
            mc = material_coeff["mc"]
            # 단일 날 절삭력
            Fc_tooth = Kc1 * ap * (fz ** (1.0 - mc))
            # 평균 맞물린 날 수 근사 (원호 접촉 적분의 근사)
            # 슬로팅(ae=D)에서는 z/2, 측면가공(ae=D/2)에서는 z/4 수준
            avg_flutes_in_cut = z * (ae / (math.pi * D))
            avg_flutes_in_cut = max(0.1, avg_flutes_in_cut)  # 최소값 보장
            Fc = Fc_tooth * avg_flutes_in_cut
        else:
            Fc = 0.0

        # ---- 스핀들 소비 전력 추정 ----
        # P = Fc * Vc / 60000 (kW) → W로 변환
        P_kw = Fc * Vc / 60000.0 if Vc > 0 else 0.0
        P_w = P_kw * 1000.0

        # 스핀들 기계 효율 보정 (일반적 효율 약 70~85%)
        P_w_actual = P_w / 0.80

        # ---- 스핀들 부하 백분율 ----
        P_rated = self.config.spindle_rated_power_w
        raw_load = min(100.0, (P_w_actual / P_rated) * 100.0) if P_rated > 0 else 0.0

        # 지수 이동 평균 적용 (급격한 변동 완화)
        alpha = self.config.load_smoothing_alpha
        if is_cutting:
            self._smoothed_load = alpha * raw_load + (1.0 - alpha) * self._smoothed_load
        else:
            # 급속 이동 시 부하 감소
            self._smoothed_load *= 0.5
        spindle_load_pct = self._smoothed_load

        # ---- 이동 방향 변화 계산 ----
        seg_vec = seg.end_pos - seg.start_pos
        seg_len = np.linalg.norm(seg_vec)
        direction_change_angle = 0.0

        if seg_len > 0.001:
            current_dir = seg_vec / seg_len
            if self._prev_direction is not None:
                cos_a = float(np.clip(np.dot(current_dir, self._prev_direction), -1.0, 1.0))
                direction_change_angle = math.degrees(math.acos(cos_a))
            self._prev_direction = current_dir
        else:
            self._prev_direction = None

        # ---- 채터 위험도 계산 ----
        chatter_score, risk_factors = self._compute_chatter_risk(
            Vc=Vc, fz=fz, ap=ap, ae=ae, D=D,
            direction_change_angle=direction_change_angle,
            is_plunge=is_plunge,
            is_cutting=is_cutting,
            load_change=abs(spindle_load_pct - self._prev_load),
            tool=tool,
        )

        # 채터 위험 수준 분류
        if not is_cutting:
            risk_level = ChatterRiskLevel.NONE
        elif chatter_score < 0.25:
            risk_level = ChatterRiskLevel.LOW
        elif chatter_score < 0.50:
            risk_level = ChatterRiskLevel.MEDIUM
        elif chatter_score < 0.75:
            risk_level = ChatterRiskLevel.HIGH
        else:
            risk_level = ChatterRiskLevel.CRITICAL

        return SegmentMachiningResult(
            segment_id=seg.segment_id,
            spindle_speed=n,
            feedrate=F,
            tool_diameter=D,
            flute_count=z,
            cutting_speed=Vc,
            feed_per_tooth=fz,
            axial_depth_ap=ap,
            radial_depth_ae=ae,
            radial_ratio=ae_ratio,
            material_removal_rate=MRR,
            estimated_cutting_force=Fc,
            estimated_spindle_power=P_w_actual,
            spindle_load_pct=spindle_load_pct,
            chatter_risk_score=chatter_score,
            chatter_risk_level=risk_level,
            direction_change_angle=direction_change_angle,
            is_plunge=is_plunge,
            is_ramp=is_ramp,
            is_cutting=is_cutting,
            risk_factors=risk_factors,
        )

    def _compute_chatter_risk(
        self,
        Vc: float,
        fz: float,
        ap: float,
        ae: float,
        D: float,
        direction_change_angle: float,
        is_plunge: bool,
        is_cutting: bool,
        load_change: float,
        tool: Optional[Tool],
    ) -> Tuple[float, dict]:
        """
        복합 위험 인자로 채터 위험도를 계산합니다.

        [모델 설명]
        전체 안정성 로브선도(SLD) 해석 대신 공학적 경험칙(heuristic)에
        기반한 위험 인자 가중 합산 방식을 사용합니다.

        각 위험 인자는 0.0~1.0 범위로 정규화됩니다:
        - risk_engagement: 맞물림 비율 기반 (높은 ae/D, ap/D → 높은 위험)
        - risk_speed: 절삭 속도 기반 (낮은 Vc → 불안정, 특정 공진 구간 주의)
        - risk_direction: 방향 전환 기반 (급격한 방향 변화 → 충격 하중)
        - risk_plunge: 축방향 절입 기반 (직하강 → 축방향 채터 위험)
        - risk_overhang: 공구 돌출 계수 (길이/직경 비율 클수록 위험)

        Returns:
            (chatter_score, risk_factors_dict)
        """
        if not is_cutting:
            return 0.0, {}

        # ---- 1. 맞물림 위험도 ----
        # 높은 ae/D, ap/D 비율 → 절삭 안정성 저하
        ae_ratio = ae / D if D > 0 else 0.5
        ap_ratio = ap / D if D > 0 else 0.2
        risk_engagement = min(1.0, (ae_ratio ** 0.6) * (ap_ratio ** 0.3) * 2.0)

        # ---- 2. 절삭 속도 위험도 ----
        # 매우 낮은 절삭 속도: 구성날끝(BUE) 및 절삭 불안정 위험
        # 낮은 Vc (<50 m/min): 높은 위험
        # 중간 Vc (50~200 m/min): 낮은 위험
        # 높은 Vc (>200 m/min): 중간 위험 (공구 진동 증가 가능)
        if Vc <= 0:
            risk_speed = 0.0
        elif Vc < 30:
            risk_speed = 0.9  # 매우 낮은 절삭 속도: 불안정 구간
        elif Vc < 80:
            risk_speed = 0.5  # 낮은 절삭 속도: 주의 필요
        elif Vc < 200:
            risk_speed = 0.15  # 적정 절삭 속도: 안정 구간
        elif Vc < 400:
            risk_speed = 0.25  # 고속: 공구 진동 증가 가능
        else:
            risk_speed = 0.40  # 초고속: 베어링 진동 등 주의

        # ---- 3. 방향 전환 위험도 ----
        # 90도 이상의 급격한 방향 전환: 충격 하중 → 채터 유발 가능
        if direction_change_angle > 0:
            # 0도 → 0.0, 90도 → 0.5, 180도 → 1.0
            risk_direction = min(1.0, direction_change_angle / 180.0)
            # 45도 미만의 완만한 방향 전환은 위험도 감소
            if direction_change_angle < 45:
                risk_direction *= 0.3
        else:
            risk_direction = 0.0

        # ---- 4. 절입 위험도 ----
        # 직하강 절입(플런지): 축방향 절삭력 최대 → 채터 위험
        # 경사 절입(램프): 중간 위험
        risk_plunge = 0.85 if is_plunge else 0.0

        # ---- 5. 공구 돌출/머신 강성 보정 ----
        # 공구 돌출이 길수록, 머신 강성이 낮을수록 위험 증가
        overhang_penalty = self.config.tool_overhang_factor
        stiffness_bonus = 1.0 / max(0.5, self.config.machine_stiffness)

        # ---- 가중 합산 ----
        w = self.config
        base_risk = (
            w.w_engagement * risk_engagement +
            w.w_speed * risk_speed +
            w.w_direction_change * risk_direction +
            w.w_plunge * risk_plunge
        )

        # 머신/공구 보정 적용
        chatter_score = base_risk * overhang_penalty * stiffness_bonus
        chatter_score = min(1.0, chatter_score * self.config.chatter_sensitivity)

        risk_factors = {
            "맞물림_위험도": round(risk_engagement, 3),
            "절삭속도_위험도": round(risk_speed, 3),
            "방향변화_위험도": round(risk_direction, 3),
            "절입_위험도": round(risk_plunge, 3),
            "공구돌출_계수": round(overhang_penalty, 3),
            "머신강성_계수": round(stiffness_bonus, 3),
        }

        return float(np.clip(chatter_score, 0.0, 1.0)), risk_factors


def create_machining_model_from_config(config_dict: dict) -> MachiningModel:
    """
    설정 딕셔너리에서 MachiningModel을 생성합니다.

    Args:
        config_dict: simulation_options.yaml의 machining 섹션

    Returns:
        설정이 적용된 MachiningModel 인스턴스
    """
    model_config = MachiningModelConfig(config_dict)
    return MachiningModel(model_config)
