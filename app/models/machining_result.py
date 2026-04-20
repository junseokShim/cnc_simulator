"""
가공 해석 결과 데이터 모델

절삭 부하, 채터, 급속 이송 진동, 상태별 디버그 정보를 함께 저장합니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

import numpy as np


class ChatterRiskLevel(Enum):
    """채터(절삭 불안정) 위험 수준"""

    NONE = "없음"
    LOW = "낮음"
    MEDIUM = "중간"
    HIGH = "높음"
    CRITICAL = "위험"


@dataclass
class SegmentMachiningResult:
    """단일 세그먼트 해석 결과"""

    segment_id: int

    spindle_speed: float
    feedrate: float
    tool_diameter: float
    flute_count: int
    tool_category: str
    tool_overhang_mm: float

    cutting_speed: float
    feed_per_tooth: float
    axial_depth_ap: float
    radial_depth_ae: float
    radial_ratio: float
    engagement_ratio: float

    material_removal_rate: float
    estimated_cutting_force: float
    estimated_spindle_power: float
    spindle_load_pct: float
    aggressiveness_score: float

    estimated_force_x: float
    estimated_force_y: float
    estimated_force_z: float
    vibration_x_um: float
    vibration_y_um: float
    vibration_z_um: float
    resultant_vibration_um: float
    motion_vibration_um: float
    cutting_vibration_um: float

    chatter_risk_score: float
    motion_risk_score: float
    chatter_risk_level: ChatterRiskLevel

    direction_change_angle: float
    is_plunge: bool
    is_ramp: bool
    is_cutting: bool

    machining_state: str = "UNKNOWN"
    contact_ratio: float = 0.0

    baseline_load_pct: float = 0.0
    axis_motion_load_pct: float = 0.0
    cutting_load_pct: float = 0.0

    risk_factors: dict = field(default_factory=dict)
    warning_messages: List[str] = field(default_factory=list)

    @property
    def is_high_risk(self) -> bool:
        """채터 고위험 세그먼트 여부"""

        return self.chatter_risk_level in (ChatterRiskLevel.HIGH, ChatterRiskLevel.CRITICAL)

    @property
    def is_aggressive_cut(self) -> bool:
        """공격적인 절삭 조건 여부"""

        return self.aggressiveness_score >= 0.60

    @property
    def chatter_risk_pct(self) -> float:
        """채터 위험도를 %로 반환"""

        return self.chatter_risk_score * 100.0

    @property
    def max_axis_vibration_um(self) -> float:
        """X/Y/Z 중 최대 진동"""

        return max(self.vibration_x_um, self.vibration_y_um, self.vibration_z_um)


@dataclass
class MachiningAnalysis:
    """전체 공구경로 가공 해석 결과 컨테이너"""

    results: List[SegmentMachiningResult] = field(default_factory=list)

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

    max_vibration_x_um: float = 0.0
    avg_vibration_x_um: float = 0.0
    max_vibration_y_um: float = 0.0
    avg_vibration_y_um: float = 0.0
    max_vibration_z_um: float = 0.0
    avg_vibration_z_um: float = 0.0
    max_resultant_vibration_um: float = 0.0
    avg_resultant_vibration_um: float = 0.0
    max_motion_vibration_um: float = 0.0
    avg_motion_vibration_um: float = 0.0
    max_cutting_vibration_um: float = 0.0
    avg_cutting_vibration_um: float = 0.0
    max_motion_risk_score: float = 0.0

    high_risk_segment_count: int = 0
    high_risk_pct: float = 0.0
    aggressive_segment_count: int = 0
    aggressive_segment_pct: float = 0.0

    model_params: dict = field(default_factory=dict)
    machine_profile_name: str = "Unknown"
    machine_profile_id: str = "unknown"

    def get_spindle_load_array(self) -> np.ndarray:
        """전체 세그먼트 스핀들 부하 배열"""

        return np.array([r.spindle_load_pct for r in self.results], dtype=float)

    def get_chatter_risk_array(self) -> np.ndarray:
        """전체 세그먼트 채터 위험도 배열(%)"""

        return np.array([r.chatter_risk_pct for r in self.results], dtype=float)

    def get_cutting_force_array(self) -> np.ndarray:
        """전체 세그먼트 절삭력 배열"""

        return np.array([r.estimated_cutting_force for r in self.results], dtype=float)

    def get_vibration_array(self, axis: str = "resultant") -> np.ndarray:
        """전체 세그먼트 진동 배열"""

        axis_key = axis.lower()
        if axis_key == "x":
            return np.array([r.vibration_x_um for r in self.results], dtype=float)
        if axis_key == "y":
            return np.array([r.vibration_y_um for r in self.results], dtype=float)
        if axis_key == "z":
            return np.array([r.vibration_z_um for r in self.results], dtype=float)
        if axis_key == "motion":
            return np.array([r.motion_vibration_um for r in self.results], dtype=float)
        if axis_key == "cutting":
            return np.array([r.cutting_vibration_um for r in self.results], dtype=float)
        return np.array([r.resultant_vibration_um for r in self.results], dtype=float)

    def compute_statistics(self):
        """전체 및 절삭 세그먼트 통계를 계산합니다."""

        if not self.results:
            return

        all_results = list(self.results)
        cutting = [result for result in self.results if result.is_cutting]

        loads = [r.spindle_load_pct for r in cutting] if cutting else [0.0]
        risks = [r.chatter_risk_score for r in cutting] if cutting else [0.0]
        forces = [r.estimated_cutting_force for r in cutting] if cutting else [0.0]
        aps = [r.axial_depth_ap for r in cutting] if cutting else [0.0]
        aes = [r.radial_depth_ae for r in cutting] if cutting else [0.0]

        vib_x = [r.vibration_x_um for r in all_results]
        vib_y = [r.vibration_y_um for r in all_results]
        vib_z = [r.vibration_z_um for r in all_results]
        vib_resultant = [r.resultant_vibration_um for r in all_results]
        vib_motion = [r.motion_vibration_um for r in all_results]
        vib_cutting = [r.cutting_vibration_um for r in all_results]
        motion_risk = [r.motion_risk_score for r in all_results]

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
        self.avg_resultant_vibration_um = float(np.mean(vib_resultant)) if vib_resultant else 0.0
        self.max_motion_vibration_um = max(vib_motion) if vib_motion else 0.0
        self.avg_motion_vibration_um = float(np.mean(vib_motion)) if vib_motion else 0.0
        self.max_cutting_vibration_um = max(vib_cutting) if vib_cutting else 0.0
        self.avg_cutting_vibration_um = float(np.mean(vib_cutting)) if vib_cutting else 0.0
        self.max_motion_risk_score = max(motion_risk) if motion_risk else 0.0

        high_risk = [
            r for r in cutting
            if r.chatter_risk_level in (ChatterRiskLevel.HIGH, ChatterRiskLevel.CRITICAL)
        ]
        self.high_risk_segment_count = len(high_risk)
        self.high_risk_pct = len(high_risk) / len(cutting) * 100.0 if cutting else 0.0

        aggressive = [r for r in cutting if r.is_aggressive_cut]
        self.aggressive_segment_count = len(aggressive)
        self.aggressive_segment_pct = len(aggressive) / len(cutting) * 100.0 if cutting else 0.0
