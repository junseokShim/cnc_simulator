"""
가공 해석 결과(Machining Result) 데이터 모델 모듈

각 NC 블록(세그먼트)에 대한 수치 가공 해석 결과를 저장합니다.
스핀들 부하 추정, 진동/채터 위험도 추정, 절삭 조건 등을 포함합니다.

[중요 고지]
이 모델은 연구/개발/교육 목적의 공학적 근사 모델입니다.
실제 산업용 시뮬레이터와 동일한 정확도를 보장하지 않습니다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import numpy as np


class ChatterRiskLevel(Enum):
    """채터(공진/진동) 위험 수준 열거형"""
    NONE = "없음"       # 절삭 없음 (급속 이동)
    LOW = "낮음"        # 안정적 절삭 가능
    MEDIUM = "중간"     # 주의 필요, 조건 조정 권장
    HIGH = "높음"       # 불안정 가능성 높음, 즉각 조치 권장
    CRITICAL = "위험"   # 채터 발생 가능성 매우 높음


@dataclass
class SegmentMachiningResult:
    """
    단일 세그먼트의 가공 해석 결과 데이터 클래스

    수치 모델에 의해 계산된 절삭 조건, 부하, 위험도를 저장합니다.
    """
    # 세그먼트 식별자
    segment_id: int

    # ---- 입력 절삭 조건 ----
    spindle_speed: float        # 주축 회전수 (RPM)
    feedrate: float             # 이송 속도 (mm/min)
    tool_diameter: float        # 공구 직경 (mm)
    flute_count: int            # 날 수

    # ---- 유도된 절삭 조건 ----
    cutting_speed: float        # 절삭 속도 Vc (m/min): π*D*n/1000
    feed_per_tooth: float       # 날당 이송량 fz (mm/tooth): F/(n*z)
    axial_depth_ap: float       # 축방향 절입 깊이 ap (mm) - 추정값
    radial_depth_ae: float      # 반경방향 맞물림 ae (mm) - 추정값
    radial_ratio: float         # 반경 방향 맞물림 비율 ae/D (0.0~1.0)

    # ---- 재료 제거 및 힘 추정 ----
    material_removal_rate: float    # 재료 제거율 MRR (mm³/min): ae*ap*F
    estimated_cutting_force: float  # 추정 접선 절삭력 Fc (N) - Kienzle 모델
    estimated_spindle_power: float  # 추정 스핀들 소비 전력 P (W)
    spindle_load_pct: float         # 정규화된 스핀들 부하 (0~100%)

    # ---- 채터/진동 위험도 ----
    chatter_risk_score: float       # 채터 위험 점수 (0.0~1.0)
    chatter_risk_level: ChatterRiskLevel  # 위험 수준 분류

    # ---- 이동 특성 분석 ----
    direction_change_angle: float   # 이전 세그먼트 대비 방향 변화각 (도)
    is_plunge: bool                 # Z방향 절입 여부 (하강 이동)
    is_ramp: bool                   # 경사 절입 여부 (XYZ 동시 이동)
    is_cutting: bool                # 절삭 이동 여부 (급속 이동 제외)

    # ---- 개별 위험 요인 점수 (디버깅/분석용) ----
    risk_factors: dict = field(default_factory=dict)

    @property
    def is_high_risk(self) -> bool:
        """높은 위험 수준 여부"""
        return self.chatter_risk_level in (ChatterRiskLevel.HIGH, ChatterRiskLevel.CRITICAL)

    @property
    def chatter_risk_pct(self) -> float:
        """채터 위험 점수를 백분율로 반환 (0~100)"""
        return self.chatter_risk_score * 100.0


@dataclass
class MachiningAnalysis:
    """
    전체 공구경로의 가공 해석 결과 컨테이너

    모든 세그먼트의 가공 해석 결과와 통계 요약을 포함합니다.
    """
    # 세그먼트별 해석 결과 목록
    results: List[SegmentMachiningResult] = field(default_factory=list)

    # ---- 집계 통계 ----
    max_spindle_load_pct: float = 0.0       # 최대 스핀들 부하 (%)
    avg_spindle_load_pct: float = 0.0       # 평균 스핀들 부하 (%)
    max_chatter_risk: float = 0.0           # 최대 채터 위험도 (0~1)
    avg_chatter_risk: float = 0.0           # 평균 채터 위험도 (0~1)
    max_cutting_force: float = 0.0          # 최대 절삭력 (N)
    total_mrr: float = 0.0                  # 총 재료 제거량 근사값 (mm³)

    # ---- 위험 구간 통계 ----
    high_risk_segment_count: int = 0        # 높은 위험 세그먼트 수
    high_risk_pct: float = 0.0             # 전체 중 높은 위험 비율 (%)

    # ---- 사용된 모델 파라미터 ----
    model_params: dict = field(default_factory=dict)

    def get_spindle_load_array(self) -> np.ndarray:
        """전체 세그먼트의 스핀들 부하 배열을 반환합니다."""
        return np.array([r.spindle_load_pct for r in self.results])

    def get_chatter_risk_array(self) -> np.ndarray:
        """전체 세그먼트의 채터 위험도 배열을 반환합니다."""
        return np.array([r.chatter_risk_score * 100.0 for r in self.results])

    def get_cutting_force_array(self) -> np.ndarray:
        """전체 세그먼트의 절삭력 배열을 반환합니다."""
        return np.array([r.estimated_cutting_force for r in self.results])

    def compute_statistics(self):
        """통계를 계산하여 필드를 업데이트합니다."""
        if not self.results:
            return

        cutting = [r for r in self.results if r.is_cutting]
        if not cutting:
            return

        loads = [r.spindle_load_pct for r in cutting]
        risks = [r.chatter_risk_score for r in cutting]
        forces = [r.estimated_cutting_force for r in cutting]

        self.max_spindle_load_pct = max(loads) if loads else 0.0
        self.avg_spindle_load_pct = float(np.mean(loads)) if loads else 0.0
        self.max_chatter_risk = max(risks) if risks else 0.0
        self.avg_chatter_risk = float(np.mean(risks)) if risks else 0.0
        self.max_cutting_force = max(forces) if forces else 0.0

        # 높은 위험 세그먼트 집계
        high_risk = [r for r in cutting
                     if r.chatter_risk_level in (ChatterRiskLevel.HIGH, ChatterRiskLevel.CRITICAL)]
        self.high_risk_segment_count = len(high_risk)
        self.high_risk_pct = len(high_risk) / len(cutting) * 100 if cutting else 0.0
