"""
가공 해석 결과(Machining Result) 데이터 모델 모듈

각 NC 블록(세그먼트)에 대해 계산한 가공 해석 결과를 저장합니다.
AE/AP, 스핀들 부하, 절삭력, 채터 위험도뿐 아니라
X/Y/Z 축별 예상 진동 정보를 함께 관리합니다.

[중요]
- 본 모델은 연구/개발/교육 목적의 공학적 근사 모델입니다.
- 실제 가공 현상의 모든 동역학을 완전하게 재현하지는 않습니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

import numpy as np


class ChatterRiskLevel(Enum):
    """채터(공진/진동) 위험 수준 구분"""

    NONE = "없음"
    LOW = "낮음"
    MEDIUM = "중간"
    HIGH = "높음"
    CRITICAL = "위험"


@dataclass
class SegmentMachiningResult:
    """
    단일 세그먼트 가공 해석 결과 데이터 클래스

    해석 모델을 통해 계산한 절삭 조건, 부하, 축력, 진동, 위험도를 저장합니다.
    """

    # 세그먼트 식별자
    segment_id: int

    # ---- 입력 가공 조건 ----
    spindle_speed: float
    feedrate: float
    tool_diameter: float
    flute_count: int

    # ---- 유도된 가공 조건 ----
    cutting_speed: float
    feed_per_tooth: float
    axial_depth_ap: float
    radial_depth_ae: float
    radial_ratio: float
    engagement_ratio: float

    # ---- 재료 제거 및 부하 추정 ----
    material_removal_rate: float
    estimated_cutting_force: float
    estimated_spindle_power: float
    spindle_load_pct: float
    aggressiveness_score: float

    # ---- 축별 힘/진동 근사 ----
    estimated_force_x: float
    estimated_force_y: float
    estimated_force_z: float
    vibration_x_um: float
    vibration_y_um: float
    vibration_z_um: float
    resultant_vibration_um: float

    # ---- 채터/진동 위험도 ----
    chatter_risk_score: float
    chatter_risk_level: ChatterRiskLevel

    # ---- 이동 특성 ----
    direction_change_angle: float
    is_plunge: bool
    is_ramp: bool
    is_cutting: bool

    # ---- 상세 분석 ----
    risk_factors: dict = field(default_factory=dict)
    warning_messages: List[str] = field(default_factory=list)

    @property
    def is_high_risk(self) -> bool:
        """고위험 세그먼트 여부"""

        return self.chatter_risk_level in (ChatterRiskLevel.HIGH, ChatterRiskLevel.CRITICAL)

    @property
    def is_aggressive_cut(self) -> bool:
        """공격적인 절삭 조건 여부"""

        return self.aggressiveness_score >= 0.60

    @property
    def chatter_risk_pct(self) -> float:
        """채터 위험 점수를 백분율로 반환"""

        return self.chatter_risk_score * 100.0

    @property
    def max_axis_vibration_um(self) -> float:
        """X/Y/Z 축 중 최대 진동 크기"""

        return max(self.vibration_x_um, self.vibration_y_um, self.vibration_z_um)


@dataclass
class MachiningAnalysis:
    """
    전체 공구경로 가공 해석 결과 컨테이너

    세그먼트별 결과와 전체 통계를 함께 관리합니다.
    """

    results: List[SegmentMachiningResult] = field(default_factory=list)

    # ---- 기본 통계 ----
    max_spindle_load_pct: float = 0.0
    avg_spindle_load_pct: float = 0.0
    max_chatter_risk: float = 0.0
    avg_chatter_risk: float = 0.0
    max_cutting_force: float = 0.0
    total_mrr: float = 0.0
    max_axial_depth_ap: float = 0.0
    avg_axial_depth_ap: float = 0.0
    max_radial_depth_ae: float = 0.0
    avg_radial_depth_ae: float = 0.0

    # ---- 축별 진동 통계 ----
    max_vibration_x_um: float = 0.0
    avg_vibration_x_um: float = 0.0
    max_vibration_y_um: float = 0.0
    avg_vibration_y_um: float = 0.0
    max_vibration_z_um: float = 0.0
    avg_vibration_z_um: float = 0.0
    max_resultant_vibration_um: float = 0.0
    avg_resultant_vibration_um: float = 0.0

    # ---- 위험 구간 통계 ----
    high_risk_segment_count: int = 0
    high_risk_pct: float = 0.0
    aggressive_segment_count: int = 0
    aggressive_segment_pct: float = 0.0

    # ---- 모델 파라미터 ----
    model_params: dict = field(default_factory=dict)

    def get_spindle_load_array(self) -> np.ndarray:
        """전체 세그먼트의 스핀들 부하 배열"""

        return np.array([r.spindle_load_pct for r in self.results], dtype=float)

    def get_chatter_risk_array(self) -> np.ndarray:
        """전체 세그먼트의 채터 위험도 배열(%)"""

        return np.array([r.chatter_risk_pct for r in self.results], dtype=float)

    def get_cutting_force_array(self) -> np.ndarray:
        """전체 세그먼트의 절삭력 배열"""

        return np.array([r.estimated_cutting_force for r in self.results], dtype=float)

    def get_vibration_array(self, axis: str = "resultant") -> np.ndarray:
        """
        전체 세그먼트의 축별 예상 진동 배열을 반환합니다.

        Args:
            axis: "x", "y", "z", "resultant" 중 하나
        """

        axis_key = axis.lower()
        if axis_key == "x":
            return np.array([r.vibration_x_um for r in self.results], dtype=float)
        if axis_key == "y":
            return np.array([r.vibration_y_um for r in self.results], dtype=float)
        if axis_key == "z":
            return np.array([r.vibration_z_um for r in self.results], dtype=float)
        return np.array([r.resultant_vibration_um for r in self.results], dtype=float)

    def compute_statistics(self):
        """절삭 세그먼트를 기준으로 전체 통계를 계산합니다."""

        if not self.results:
            return

        cutting = [r for r in self.results if r.is_cutting]
        if not cutting:
            return

        loads = [r.spindle_load_pct for r in cutting]
        risks = [r.chatter_risk_score for r in cutting]
        forces = [r.estimated_cutting_force for r in cutting]
        aps = [r.axial_depth_ap for r in cutting]
        aes = [r.radial_depth_ae for r in cutting]

        vib_x = [r.vibration_x_um for r in cutting]
        vib_y = [r.vibration_y_um for r in cutting]
        vib_z = [r.vibration_z_um for r in cutting]
        vib_resultant = [r.resultant_vibration_um for r in cutting]

        self.max_spindle_load_pct = max(loads) if loads else 0.0
        self.avg_spindle_load_pct = float(np.mean(loads)) if loads else 0.0
        self.max_chatter_risk = max(risks) if risks else 0.0
        self.avg_chatter_risk = float(np.mean(risks)) if risks else 0.0
        self.max_cutting_force = max(forces) if forces else 0.0
        self.max_axial_depth_ap = max(aps) if aps else 0.0
        self.avg_axial_depth_ap = float(np.mean(aps)) if aps else 0.0
        self.max_radial_depth_ae = max(aes) if aes else 0.0
        self.avg_radial_depth_ae = float(np.mean(aes)) if aes else 0.0

        self.max_vibration_x_um = max(vib_x) if vib_x else 0.0
        self.avg_vibration_x_um = float(np.mean(vib_x)) if vib_x else 0.0
        self.max_vibration_y_um = max(vib_y) if vib_y else 0.0
        self.avg_vibration_y_um = float(np.mean(vib_y)) if vib_y else 0.0
        self.max_vibration_z_um = max(vib_z) if vib_z else 0.0
        self.avg_vibration_z_um = float(np.mean(vib_z)) if vib_z else 0.0
        self.max_resultant_vibration_um = max(vib_resultant) if vib_resultant else 0.0
        self.avg_resultant_vibration_um = (
            float(np.mean(vib_resultant)) if vib_resultant else 0.0
        )

        high_risk = [
            r for r in cutting
            if r.chatter_risk_level in (ChatterRiskLevel.HIGH, ChatterRiskLevel.CRITICAL)
        ]
        self.high_risk_segment_count = len(high_risk)
        self.high_risk_pct = len(high_risk) / len(cutting) * 100.0 if cutting else 0.0

        aggressive = [r for r in cutting if r.is_aggressive_cut]
        self.aggressive_segment_count = len(aggressive)
        self.aggressive_segment_pct = len(aggressive) / len(cutting) * 100.0 if cutting else 0.0
