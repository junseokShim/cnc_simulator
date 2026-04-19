"""
가공 수치 모델 인터페이스 정의 모듈

이 모듈은 스핀들 부하 예측기와 채터 위험도 예측기의 추상 인터페이스를 정의합니다.
미래에 수학적 모델을 데이터 기반 모델(ML)로 교체할 때 이 인터페이스를 구현하면
나머지 시뮬레이션/UI 파이프라인은 수정 없이 그대로 사용할 수 있습니다.

[교체 지점 안내]
수학적 모델 → 데이터 기반 모델 교체 시:
  1. SpindleLoadPredictor를 구현하는 새 클래스 작성
     (예: MLSpindleLoadPredictor)
  2. ChatterRiskPredictor를 구현하는 새 클래스 작성
     (예: MLChatterRiskPredictor)
  3. app/simulation/machining_model.py의 MachiningModel.__init__에서
     예측기 인스턴스를 교체
  → UI, 보고서, 검증 모듈은 변경 불필요

[입력 피처 스키마]
SpindleLoadPredictor.predict() 및 ChatterRiskPredictor.predict()의 입력:
  - cutting_speed_vc: float    절삭 속도 Vc (m/min)
  - feed_per_tooth_fz: float   날당 이송량 fz (mm/tooth)
  - axial_depth_ap: float      축방향 절입 깊이 (mm)
  - radial_depth_ae: float     반경방향 맞물림 (mm)
  - tool_diameter: float       공구 직경 (mm)
  - flute_count: int           날 수
  - spindle_rpm: float         주축 회전수 (RPM)
  - feedrate: float            이송 속도 (mm/min)
  - phi_entry_deg: float       절입각 (도)
  - phi_exit_deg: float        이탈각 (도)
  - direction_change_deg: float 방향 변화각 (도)
  - is_plunge: bool            플런지 여부
  - is_cutting: bool           절삭 이동 여부

[출력 스키마]
SpindleLoadPredictor.predict() 출력:
  - spindle_load_pct: float    스핀들 부하 백분율 (0~100%)

ChatterRiskPredictor.predict() 출력:
  - chatter_risk_score: float  채터 위험도 점수 (0.0~1.0)
  - stability_margin: float    안정성 마진 (>1 = 안정, <1 = 불안정)
  - vibration_x_um: float      X축 예상 진동 (μm)
  - vibration_y_um: float      Y축 예상 진동 (μm)
  - vibration_z_um: float      Z축 예상 진동 (μm)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class CuttingFeatures:
    """
    가공 모델 입력 피처 컨테이너

    수학적 모델과 미래 ML 모델 모두에서 동일하게 사용하는
    정규화된 입력 특징 집합입니다.
    """
    # ---- 기본 절삭 조건 ----
    cutting_speed_vc: float = 0.0       # 절삭 속도 Vc (m/min)
    feed_per_tooth_fz: float = 0.0      # 날당 이송량 fz (mm/tooth)
    axial_depth_ap: float = 0.0         # 축방향 절입 깊이 ap (mm)
    radial_depth_ae: float = 0.0        # 반경방향 맞물림 ae (mm)
    radial_ratio: float = 0.0           # ae/D 비율 (0.0~1.0)

    # ---- 공구 파라미터 ----
    tool_diameter: float = 10.0         # 공구 직경 D (mm)
    flute_count: int = 4                # 날 수 z
    spindle_rpm: float = 0.0            # 주축 회전수 n (RPM)
    feedrate: float = 0.0              # 이송 속도 F (mm/min)

    # ---- 절입각 (Altintas 모델 핵심) ----
    phi_entry_rad: float = 0.0          # 절입각 φ_st (rad)
    phi_exit_rad: float = 0.0           # 이탈각 φ_ex (rad)
    phi_entry_deg: float = 0.0          # 절입각 (도)
    phi_exit_deg: float = 0.0           # 이탈각 (도)
    engagement_arc_deg: float = 0.0     # 맞물림 호 각도 (도)

    # ---- 이동 특성 ----
    direction_change_deg: float = 0.0   # 방향 변화각 (도)
    is_plunge: bool = False             # Z방향 플런지 여부
    is_ramp: bool = False               # 경사 절입 여부
    is_cutting: bool = False            # 절삭 이동 여부

    # ---- 재료 제거율 ----
    mrr_mm3_per_min: float = 0.0       # 재료 제거율 (mm³/min)

    # ---- 가공 상태 (공중이송/절삭/플런지 구분) ----
    machining_state: str = "UNKNOWN"   # RAPID/AIR_FEED/PLUNGE/CUTTING/EXIT
    contact_ratio: float = 0.0         # 소재 접촉 비율 (0=비접촉, 1=완전 접촉)

    def to_dict(self) -> Dict[str, Any]:
        """ML 모델 입력용 딕셔너리 변환"""
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class SpindleLoadPrediction:
    """스핀들 부하 예측 결과 (분해된 성분 포함)"""
    spindle_load_pct: float = 0.0           # 스핀들 총 부하 (%)
    cutting_force_ft: float = 0.0           # 평균 접선 절삭력 (N)
    cutting_force_fr: float = 0.0           # 평균 반경 절삭력 (N)
    cutting_force_fa: float = 0.0           # 평균 축방향 절삭력 (N)
    force_x: float = 0.0                    # X방향 합력 (N)
    force_y: float = 0.0                    # Y방향 합력 (N)
    force_z: float = 0.0                    # Z방향 합력 (N)
    torque_nm: float = 0.0                  # 스핀들 토크 (N·m)
    power_w: float = 0.0                    # 스핀들 총 소비 전력 (W)
    mrr: float = 0.0                        # 재료 제거율 (mm³/min)
    aggressiveness: float = 0.0             # 절삭 공격성 점수 (0~1)

    # ---- 부하 성분 분해 (공중이송과 절삭을 구분하는 핵심 필드) ----
    # total = baseline + axis_motion + cutting
    baseline_load_pct: float = 0.0          # 스핀들 무부하 기저 부하 (%)
    axis_motion_load_pct: float = 0.0       # 축 이송 소비 부하 (%)
    cutting_load_pct: float = 0.0           # 실제 절삭 기여 부하 (%)


@dataclass
class ChatterRiskPrediction:
    """채터/진동 위험도 예측 결과"""
    chatter_risk_score: float = 0.0         # 채터 위험 점수 (0.0~1.0)
    stability_margin: float = 999.0         # 안정성 마진 (>1 = 안정)
    ap_limit: float = 0.0                   # 임계 축방향 절입 깊이 (mm)
    tooth_passing_freq_hz: float = 0.0      # 날 통과 주파수 (Hz)
    dynamic_magnification: float = 1.0      # 동적 배율 (FRF 기반)
    vibration_x_um: float = 0.0             # X축 예상 진동 진폭 (μm)
    vibration_y_um: float = 0.0             # Y축 예상 진동 진폭 (μm)
    vibration_z_um: float = 0.0             # Z축 예상 진동 진폭 (μm)
    resultant_vibration_um: float = 0.0     # 합성 진동 진폭 (μm)
    risk_factors: dict = field(default_factory=dict)  # 개별 위험 인자


class SpindleLoadPredictor(ABC):
    """
    스핀들 부하 예측기 추상 기저 클래스

    이 인터페이스를 구현하여 수학적 모델 또는 ML 모델을 삽입합니다.

    [현재 구현]
    app/models/spindle_load_model.py :: MechanisticSpindleLoadModel

    [ML 교체 방법]
    1. 이 클래스를 상속받는 MLSpindleLoadPredictor 작성
    2. predict()에서 학습된 모델 추론 실행
    3. app/simulation/machining_model.py에서 교체
    """

    @abstractmethod
    def predict(self, features: CuttingFeatures, params: dict) -> SpindleLoadPrediction:
        """
        절삭 피처로부터 스핀들 부하를 예측합니다.

        Args:
            features: CuttingFeatures 인스턴스 (표준화된 입력)
            params: 모델 파라미터 딕셔너리 (Ktc, Krc 등)

        Returns:
            SpindleLoadPrediction
        """
        ...


class ChatterRiskPredictor(ABC):
    """
    채터/진동 위험도 예측기 추상 기저 클래스

    이 인터페이스를 구현하여 수학적 모델 또는 ML 모델을 삽입합니다.

    [현재 구현]
    app/models/chatter_model.py :: StabilityLobeChatterModel

    [ML 교체 방법]
    1. 이 클래스를 상속받는 MLChatterRiskPredictor 작성
    2. predict()에서 학습된 모델 추론 실행
    3. app/simulation/machining_model.py에서 교체
    """

    @abstractmethod
    def predict(
        self,
        features: CuttingFeatures,
        load_pred: SpindleLoadPrediction,
        params: dict,
    ) -> ChatterRiskPrediction:
        """
        절삭 피처로부터 채터 위험도를 예측합니다.

        Args:
            features: CuttingFeatures 인스턴스
            load_pred: SpindleLoadPrediction (힘/전력 정보)
            params: 모델 파라미터 딕셔너리 (k, zeta, omega_n 등)

        Returns:
            ChatterRiskPrediction
        """
        ...
