"""
가공 해석 모델(Machining Model) 모듈

3축 CNC 공구경로를 세그먼트 단위로 해석하여
AE/AP, 절삭력, 스핀들 부하, 채터 위험도, X/Y/Z 축별 진동을 추정합니다.

[핵심 개선]
1. AE/AP를 현재 스톡 상태에서 세그먼트별로 다시 추정
2. 절삭력과 스핀들 부하를 feed/speed/engagement 기반으로 수치 계산
3. 플런지/램프/방향 전환/overhang/기계 강성을 진동 위험도에 반영
4. 절삭력을 X/Y/Z 축 성분으로 분해하여 예상 축진동(um) 산출

[중요]
- 본 모델은 공학적 근사 모델입니다.
- 실제 산업용 동역학 해석(SLD, FRF 기반 채터 해석)을 대체하지는 않습니다.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.geometry.stock_model import StockModel
from app.models.machining_result import (
    ChatterRiskLevel,
    MachiningAnalysis,
    SegmentMachiningResult,
)
from app.models.tool import Tool, ToolType
from app.models.toolpath import MotionSegment, MotionType, Toolpath
from app.utils.logger import get_logger

logger = get_logger("machining_model")


MATERIAL_COEFFICIENTS = {
    "aluminum": {"Kc1": 700.0, "mc": 0.25, "name": "알루미늄 합금"},
    "steel_mild": {"Kc1": 1800.0, "mc": 0.26, "name": "저탄소강"},
    "steel_hard": {"Kc1": 2500.0, "mc": 0.28, "name": "고경도강"},
    "stainless": {"Kc1": 2200.0, "mc": 0.27, "name": "스테인리스강"},
    "titanium": {"Kc1": 2000.0, "mc": 0.30, "name": "티타늄 합금"},
    "cast_iron": {"Kc1": 1100.0, "mc": 0.23, "name": "주철"},
    "default": {"Kc1": 1500.0, "mc": 0.26, "name": "일반 금속"},
}


class MachiningModelConfig:
    """
    가공 해석 모델 설정 파라미터

    모든 값은 `configs/simulation_options.yaml`의 `machining` 섹션에서 덮어쓸 수 있습니다.
    """

    def __init__(self, config_dict: Optional[dict] = None):
        cfg = config_dict or {}

        # 재료 / 장비 / 공구 강성 계수
        self.material: str = cfg.get("material", "aluminum")
        self.machine_stiffness: float = float(cfg.get("machine_stiffness", 1.0))
        self.tool_overhang_factor: float = float(cfg.get("tool_overhang_factor", 1.0))
        self.spindle_rated_power_w: float = float(cfg.get("spindle_rated_power_w", 7500.0))
        self.spindle_efficiency: float = float(cfg.get("spindle_efficiency", 0.82))

        # 기본 fallback 가공 조건
        self.default_ae_ratio: float = float(cfg.get("default_ae_ratio", 0.5))
        self.default_ap_mm: float = float(cfg.get("default_ap_mm", 2.0))
        self.default_flute_count: int = int(cfg.get("default_flute_count", 4))

        # 절삭 해석 보조 계수
        self.min_chip_thickness_mm: float = float(cfg.get("min_chip_thickness_mm", 0.01))
        self.reference_chipload_mm: float = float(cfg.get("reference_chipload_mm", 0.06))
        self.reference_mrr_mm3_min: float = float(cfg.get("reference_mrr_mm3_min", 16000.0))
        self.engagement_sample_count: int = int(cfg.get("engagement_sample_count", 7))
        self.entry_force_multiplier: float = float(cfg.get("entry_force_multiplier", 1.15))
        self.plunge_force_multiplier: float = float(cfg.get("plunge_force_multiplier", 1.40))
        self.ramp_force_multiplier: float = float(cfg.get("ramp_force_multiplier", 1.20))

        # 축력/진동 추정 계수
        self.radial_force_ratio_base: float = float(cfg.get("radial_force_ratio_base", 0.42))
        self.radial_force_ratio_gain: float = float(cfg.get("radial_force_ratio_gain", 0.22))
        self.axial_force_ratio_base: float = float(cfg.get("axial_force_ratio_base", 0.18))
        self.axial_force_ratio_gain: float = float(cfg.get("axial_force_ratio_gain", 0.30))
        self.x_axis_stiffness_n_per_um: float = float(
            cfg.get("x_axis_stiffness_n_per_um", 60.0)
        )
        self.y_axis_stiffness_n_per_um: float = float(
            cfg.get("y_axis_stiffness_n_per_um", 58.0)
        )
        self.z_axis_stiffness_n_per_um: float = float(
            cfg.get("z_axis_stiffness_n_per_um", 85.0)
        )
        self.dynamic_vibration_gain: float = float(cfg.get("dynamic_vibration_gain", 0.85))

        # 부하 평활화
        self.load_smoothing_alpha: float = float(cfg.get("load_smoothing_alpha", 0.3))

        # 채터 위험도 가중치
        self.chatter_sensitivity: float = float(cfg.get("chatter_sensitivity", 1.0))
        self.w_engagement: float = float(cfg.get("w_engagement", 0.25))
        self.w_speed: float = float(cfg.get("w_speed", 0.10))
        self.w_direction_change: float = float(cfg.get("w_direction_change", 0.14))
        self.w_plunge: float = float(cfg.get("w_plunge", 0.16))
        self.w_force: float = float(cfg.get("w_force", 0.18))
        self.w_load_change: float = float(cfg.get("w_load_change", 0.10))
        self.w_chipload: float = float(cfg.get("w_chipload", 0.07))

        # 공격 절삭 / 경보 기준
        self.high_load_threshold_pct: float = float(cfg.get("high_load_threshold_pct", 80.0))
        self.aggressive_ap_ratio: float = float(cfg.get("aggressive_ap_ratio", 0.50))
        self.aggressive_ae_ratio: float = float(cfg.get("aggressive_ae_ratio", 0.65))
        self.unstable_chatter_threshold: float = float(
            cfg.get("unstable_chatter_threshold", 0.65)
        )
        self.xy_vibration_warning_um: float = float(cfg.get("xy_vibration_warning_um", 12.0))
        self.z_vibration_warning_um: float = float(cfg.get("z_vibration_warning_um", 9.0))
        self.resultant_vibration_warning_um: float = float(
            cfg.get("resultant_vibration_warning_um", 16.0)
        )

    def get_material_coeff(self) -> dict:
        """현재 재료의 Kienzle 계수를 반환합니다."""

        return MATERIAL_COEFFICIENTS.get(self.material, MATERIAL_COEFFICIENTS["default"])


class MachiningModel:
    """
    CNC 가공 해석 모델 클래스

    세그먼트별 계산 순서:
    1. 현재 스톡 상태에서 AE/AP 추정
    2. 절삭 속도, fz, 유효 칩두께 계산
    3. 절삭력 / 스핀들 부하 계산
    4. 채터 위험도 계산
    5. 절삭력을 X/Y/Z 축력으로 분해
    6. 축강성 기반 예상 진동(um) 산출
    7. 경보 메시지 생성
    """

    def __init__(self, config: Optional[MachiningModelConfig] = None):
        self.config = config or MachiningModelConfig()
        self._smoothed_load: float = 0.0
        self._last_ap: float = self.config.default_ap_mm
        self._prev_direction: Optional[np.ndarray] = None
        self._prev_load: float = 0.0

    def analyze_toolpath(
        self,
        toolpath: Toolpath,
        tools: Dict[int, Tool],
        stock_model: Optional[StockModel] = None,
    ) -> MachiningAnalysis:
        """
        전체 공구경로를 세그먼트 단위로 해석합니다.

        Args:
            toolpath: 분석할 공구경로
            tools: 공구 번호 -> Tool 매핑
            stock_model: 초기 스톡 모델. 주어지면 AE/AP를 실제 잔여 소재 기준으로 계산합니다.
        """
        logger.info("가공 해석 시작: %d개 세그먼트", len(toolpath.segments))

        self._smoothed_load = 0.0
        self._last_ap = self.config.default_ap_mm
        self._prev_direction = None
        self._prev_load = 0.0

        material_coeff = self.config.get_material_coeff()
        analysis_stock = stock_model.copy() if stock_model is not None else None

        results: List[SegmentMachiningResult] = []
        total_removed_volume = 0.0

        for index, seg in enumerate(toolpath.segments):
            tool = self._resolve_tool(seg, tools)
            result = self._analyze_segment(
                seg=seg,
                tool=tool,
                material_coeff=material_coeff,
                stock_model=analysis_stock,
                segment_index=index,
            )
            results.append(result)

            if result.is_cutting:
                self._prev_load = result.spindle_load_pct
                total_removed_volume += self._estimate_segment_removed_volume(seg, result)
                if analysis_stock is not None:
                    self._apply_segment_to_stock(analysis_stock, seg, tool, result)

        analysis = MachiningAnalysis(
            results=results,
            model_params={
                "material": self.config.material,
                "Kc1": material_coeff["Kc1"],
                "mc": material_coeff["mc"],
                "spindle_rated_power_w": self.config.spindle_rated_power_w,
                "spindle_efficiency": self.config.spindle_efficiency,
                "default_ae_ratio": self.config.default_ae_ratio,
                "default_ap_mm": self.config.default_ap_mm,
                "machine_stiffness": self.config.machine_stiffness,
                "tool_overhang_factor": self.config.tool_overhang_factor,
                "reference_chipload_mm": self.config.reference_chipload_mm,
                "reference_mrr_mm3_min": self.config.reference_mrr_mm3_min,
                "x_axis_stiffness_n_per_um": self.config.x_axis_stiffness_n_per_um,
                "y_axis_stiffness_n_per_um": self.config.y_axis_stiffness_n_per_um,
                "z_axis_stiffness_n_per_um": self.config.z_axis_stiffness_n_per_um,
                "xy_vibration_warning_um": self.config.xy_vibration_warning_um,
                "z_vibration_warning_um": self.config.z_vibration_warning_um,
                "resultant_vibration_warning_um": self.config.resultant_vibration_warning_um,
            },
        )
        analysis.compute_statistics()
        analysis.total_mrr = total_removed_volume

        logger.info(
            "가공 해석 완료: 최대부하 %.1f%%, 최대채터위험 %.1f%%, 최대합성진동 %.2f um",
            analysis.max_spindle_load_pct,
            analysis.max_chatter_risk * 100.0,
            analysis.max_resultant_vibration_um,
        )
        return analysis

    def _resolve_tool(self, seg: MotionSegment, tools: Dict[int, Tool]) -> Tool:
        """정의되지 않은 공구도 해석이 가능하도록 임시 공구를 생성합니다."""

        tool = tools.get(seg.tool_number)
        if tool is not None:
            return tool

        diameter = 10.0
        return Tool(
            tool_number=seg.tool_number,
            name=f"임시 공구 T{seg.tool_number}",
            tool_type=ToolType.END_MILL,
            diameter=diameter,
            length=diameter * 6.0,
            flute_length=max(self.config.default_ap_mm * 3.0, diameter * 2.0),
            corner_radius=0.0,
            material="카바이드",
            flute_count=self.config.default_flute_count,
        )

    def _analyze_segment(
        self,
        seg: MotionSegment,
        tool: Tool,
        material_coeff: dict,
        stock_model: Optional[StockModel],
        segment_index: int,
    ) -> SegmentMachiningResult:
        """단일 세그먼트를 해석합니다."""

        del segment_index  # 추후 세그먼트 인덱스 기반 보정이 필요할 때를 대비해 인자를 유지합니다.

        diameter = max(tool.diameter, 0.1)
        flute_count = max(tool.flute_count, 1)
        spindle_speed = max(seg.spindle_speed, 0.0)
        feedrate = max(seg.feedrate, 0.0)

        delta = seg.end_pos - seg.start_pos
        delta_z = float(delta[2])
        dist_xy = float(np.hypot(delta[0], delta[1]))

        is_cutting = bool(seg.is_cutting_move and seg.spindle_on and feedrate > 0.0)
        is_plunge = bool(is_cutting and delta_z < -0.01 and dist_xy < max(diameter * 0.2, 0.2))
        is_ramp = bool(is_cutting and delta_z < -0.01 and dist_xy >= max(diameter * 0.2, 0.2))

        cutting_speed = math.pi * diameter * spindle_speed / 1000.0 if spindle_speed > 0.0 else 0.0
        feed_per_tooth = (
            feedrate / (spindle_speed * flute_count)
            if spindle_speed > 0.0 and flute_count > 0
            else 0.0
        )
        direction_change_angle = self._compute_direction_change(seg)

        ae, ap, engagement_ratio = self._estimate_engagement(
            seg=seg,
            tool=tool,
            stock_model=stock_model,
            is_cutting=is_cutting,
            is_plunge=is_plunge,
            is_ramp=is_ramp,
        )
        ae_ratio = ae / diameter if diameter > 0.0 else 0.0
        ap_ratio = ap / diameter if diameter > 0.0 else 0.0

        effective_cutting = bool(is_cutting and ae > 1e-6 and ap > 1e-6)
        material_removal_rate = ae * ap * feedrate if effective_cutting else 0.0
        chip_thickness = self._estimate_chip_thickness(feed_per_tooth, ae_ratio)

        cutting_force = (
            self._compute_cutting_force(
                material_coeff=material_coeff,
                ap=ap,
                ae_ratio=ae_ratio,
                engagement_ratio=engagement_ratio,
                chip_thickness=chip_thickness,
                flute_count=flute_count,
                is_plunge=is_plunge,
                is_ramp=is_ramp,
                direction_change_angle=direction_change_angle,
            )
            if effective_cutting
            else 0.0
        )
        spindle_power_w = self._compute_spindle_power(cutting_force, cutting_speed)

        raw_load = (
            self._compute_spindle_load_pct(
                spindle_power_w=spindle_power_w,
                material_removal_rate=material_removal_rate,
                ae_ratio=ae_ratio,
                ap_ratio=ap_ratio,
            )
            if effective_cutting
            else 0.0
        )

        alpha = float(np.clip(self.config.load_smoothing_alpha, 0.0, 1.0))
        if effective_cutting:
            self._smoothed_load = alpha * raw_load + (1.0 - alpha) * self._smoothed_load
        else:
            self._smoothed_load *= 0.35
        spindle_load_pct = float(np.clip(self._smoothed_load, 0.0, 100.0))

        aggressiveness_score = (
            self._compute_aggressiveness(
                ae_ratio=ae_ratio,
                ap_ratio=ap_ratio,
                spindle_load_pct=spindle_load_pct,
                feed_per_tooth=feed_per_tooth,
                is_plunge=is_plunge,
                is_ramp=is_ramp,
            )
            if effective_cutting
            else 0.0
        )

        load_change = abs(spindle_load_pct - self._prev_load)
        chatter_score, risk_factors = self._compute_chatter_risk(
            Vc=cutting_speed,
            fz=feed_per_tooth,
            ap=ap,
            ae=ae,
            D=diameter,
            spindle_load_pct=spindle_load_pct,
            aggressiveness_score=aggressiveness_score,
            direction_change_angle=direction_change_angle,
            is_plunge=is_plunge,
            is_ramp=is_ramp,
            is_cutting=effective_cutting,
            load_change=load_change,
        )

        force_x, force_y, force_z = self._compute_axis_force_components(
            seg=seg,
            cutting_force=cutting_force if effective_cutting else 0.0,
            ae_ratio=ae_ratio,
            ap_ratio=ap_ratio,
            is_plunge=is_plunge,
            is_ramp=is_ramp,
        )
        vibration_x_um, vibration_y_um, vibration_z_um, resultant_vibration_um = (
            self._compute_axis_vibration(
                force_x=force_x,
                force_y=force_y,
                force_z=force_z,
                chatter_score=chatter_score,
                spindle_load_pct=spindle_load_pct,
                load_change=load_change,
                direction_change_angle=direction_change_angle,
                ae_ratio=ae_ratio,
                ap_ratio=ap_ratio,
                is_plunge=is_plunge,
                is_ramp=is_ramp,
            )
        )

        risk_factors.update(
            {
                "force_x_n": round(force_x, 2),
                "force_y_n": round(force_y, 2),
                "force_z_n": round(force_z, 2),
                "vibration_x_um": round(vibration_x_um, 3),
                "vibration_y_um": round(vibration_y_um, 3),
                "vibration_z_um": round(vibration_z_um, 3),
                "resultant_vibration_um": round(resultant_vibration_um, 3),
            }
        )

        warning_messages = self._build_segment_warnings(
            ae_ratio=ae_ratio,
            ap_ratio=ap_ratio,
            ap=ap,
            spindle_load_pct=spindle_load_pct,
            chatter_score=chatter_score,
            is_plunge=is_plunge,
            is_ramp=is_ramp,
            load_change=load_change,
            vibration_x_um=vibration_x_um,
            vibration_y_um=vibration_y_um,
            vibration_z_um=vibration_z_um,
            resultant_vibration_um=resultant_vibration_um,
        )

        if not effective_cutting:
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
            spindle_speed=spindle_speed,
            feedrate=feedrate,
            tool_diameter=diameter,
            flute_count=flute_count,
            cutting_speed=cutting_speed,
            feed_per_tooth=feed_per_tooth,
            axial_depth_ap=ap,
            radial_depth_ae=ae,
            radial_ratio=ae_ratio,
            engagement_ratio=engagement_ratio,
            material_removal_rate=material_removal_rate,
            estimated_cutting_force=cutting_force,
            estimated_spindle_power=spindle_power_w,
            spindle_load_pct=spindle_load_pct,
            aggressiveness_score=aggressiveness_score,
            estimated_force_x=force_x,
            estimated_force_y=force_y,
            estimated_force_z=force_z,
            vibration_x_um=vibration_x_um,
            vibration_y_um=vibration_y_um,
            vibration_z_um=vibration_z_um,
            resultant_vibration_um=resultant_vibration_um,
            chatter_risk_score=chatter_score,
            chatter_risk_level=risk_level,
            direction_change_angle=direction_change_angle,
            is_plunge=is_plunge,
            is_ramp=is_ramp,
            is_cutting=effective_cutting,
            risk_factors=risk_factors,
            warning_messages=warning_messages,
        )

    def _estimate_engagement(
        self,
        seg: MotionSegment,
        tool: Tool,
        stock_model: Optional[StockModel],
        is_cutting: bool,
        is_plunge: bool,
        is_ramp: bool,
    ) -> Tuple[float, float, float]:
        """
        세그먼트의 ae/ap를 추정합니다.

        우선순위:
        1. 현재 잔여 스톡 기반 추정
        2. 세그먼트 기하 + 직전 ap를 이용한 fallback
        """
        if not is_cutting:
            return 0.0, 0.0, 0.0

        if stock_model is not None:
            engagement = stock_model.estimate_segment_engagement(
                seg.start_pos,
                seg.end_pos,
                tool,
                sample_count=self.config.engagement_sample_count,
            )
            if engagement["engaged_samples"] > 0:
                ae = float(np.clip(engagement["ae"], 0.0, tool.diameter))
                ap = float(np.clip(engagement["ap"], 0.0, tool.flute_length))
                engagement_ratio = float(np.clip(engagement["engagement_ratio"], 0.0, 1.0))
                if ap > 1e-6:
                    self._last_ap = ap
                return ae, ap, engagement_ratio

        delta_z = float(seg.end_pos[2] - seg.start_pos[2])
        diameter = max(tool.diameter, 0.1)

        if is_plunge:
            ap = max(abs(delta_z), self.config.default_ap_mm)
            ae = diameter
        elif is_ramp:
            ap = max(abs(delta_z), self._last_ap * 0.7, self.config.default_ap_mm * 0.6)
            ae = min(diameter, max(diameter * self.config.default_ae_ratio, diameter * 0.6))
        else:
            ap = max(self._last_ap, self.config.default_ap_mm)
            ae = diameter * self.config.default_ae_ratio

        ap = float(np.clip(ap, 0.0, tool.flute_length))
        ae = float(np.clip(ae, 0.0, diameter))
        engagement_ratio = float(
            np.clip((ae / diameter) * min(1.0, ap / max(tool.flute_length, diameter)), 0.0, 1.0)
        )
        if ap > 1e-6:
            self._last_ap = ap
        return ae, ap, engagement_ratio

    def _estimate_chip_thickness(self, feed_per_tooth: float, ae_ratio: float) -> float:
        """
        ae 비율을 반영한 유효 칩두께를 추정합니다.

        stepover가 작아질수록 동일한 fz라도 평균 칩두께가 줄어드는 경향을 반영합니다.
        """
        if feed_per_tooth <= 0.0:
            return 0.0

        chip_factor = 0.55 + 0.45 * math.sqrt(max(ae_ratio, 1e-4))
        return max(self.config.min_chip_thickness_mm, feed_per_tooth * chip_factor)

    def _compute_cutting_force(
        self,
        material_coeff: dict,
        ap: float,
        ae_ratio: float,
        engagement_ratio: float,
        chip_thickness: float,
        flute_count: int,
        is_plunge: bool,
        is_ramp: bool,
        direction_change_angle: float,
    ) -> float:
        """
        절삭력을 추정합니다.

        [근사식]
        1. Kienzle 계열 비절삭저항을 기반으로 칩두께에 따른 비선형성을 반영
        2. AP, AE, 실제 engagement 비율을 함께 고려
        3. 램프/플런지/방향 전환 시 순간 부하 증가를 보정
        """
        if ap <= 0.0 or chip_thickness <= 0.0:
            return 0.0

        kc1 = material_coeff["Kc1"]
        mc = material_coeff["mc"]
        specific_force = kc1 / (chip_thickness ** mc)

        avg_flutes_in_cut = max(0.45, flute_count * (0.18 + 0.82 * min(1.0, ae_ratio)))
        engagement_factor = 0.55 + 0.95 * ae_ratio + 0.50 * engagement_ratio
        direction_factor = 1.0 + 0.12 * min(1.0, direction_change_angle / 180.0)

        entry_factor = self.config.entry_force_multiplier
        if is_plunge:
            entry_factor = self.config.plunge_force_multiplier
        elif is_ramp:
            entry_factor = self.config.ramp_force_multiplier

        return (
            specific_force
            * ap
            * chip_thickness
            * avg_flutes_in_cut
            * engagement_factor
            * direction_factor
            * entry_factor
        )

    def _compute_spindle_power(self, cutting_force: float, cutting_speed: float) -> float:
        """절삭력과 절삭속도로 스핀들 소비 전력을 추정합니다."""

        if cutting_force <= 0.0 or cutting_speed <= 0.0:
            return 0.0

        power_mech_w = cutting_force * (cutting_speed / 60.0)
        efficiency = max(0.1, self.config.spindle_efficiency)
        return power_mech_w / efficiency

    def _compute_spindle_load_pct(
        self,
        spindle_power_w: float,
        material_removal_rate: float,
        ae_ratio: float,
        ap_ratio: float,
    ) -> float:
        """
        스핀들 부하 백분율을 추정합니다.

        전력 기반 부하와 MRR 기반 부하를 혼합하고,
        AE/AP가 클수록 순간 부하가 더 높아지도록 보정합니다.
        """
        rated_power = max(self.config.spindle_rated_power_w, 1.0)
        power_load = spindle_power_w / rated_power * 100.0
        mrr_load = material_removal_rate / max(self.config.reference_mrr_mm3_min, 1.0) * 100.0
        engagement_bonus = 1.0 + 0.20 * ae_ratio + 0.18 * min(ap_ratio, 1.5)
        raw_load = (power_load * 0.72 + mrr_load * 0.28) * engagement_bonus
        return float(np.clip(raw_load, 0.0, 100.0))

    def _compute_aggressiveness(
        self,
        ae_ratio: float,
        ap_ratio: float,
        spindle_load_pct: float,
        feed_per_tooth: float,
        is_plunge: bool,
        is_ramp: bool,
    ) -> float:
        """공격 절삭 점수를 계산합니다."""

        ap_norm = min(1.0, ap_ratio / max(self.config.aggressive_ap_ratio, 1e-6))
        ae_norm = min(1.0, ae_ratio / max(self.config.aggressive_ae_ratio, 1e-6))
        load_norm = min(1.0, spindle_load_pct / max(self.config.high_load_threshold_pct, 1.0))
        chip_norm = min(1.0, feed_per_tooth / max(self.config.reference_chipload_mm, 1e-6))
        entry_norm = 1.0 if is_plunge else (0.55 if is_ramp else 0.15)

        score = (
            0.26 * ap_norm
            + 0.24 * ae_norm
            + 0.26 * load_norm
            + 0.14 * chip_norm
            + 0.10 * entry_norm
        )
        return float(np.clip(score, 0.0, 1.0))

    def _compute_chatter_risk(
        self,
        Vc: float,
        fz: float,
        ap: float,
        ae: float,
        D: float,
        spindle_load_pct: float,
        aggressiveness_score: float,
        direction_change_angle: float,
        is_plunge: bool,
        is_ramp: bool,
        is_cutting: bool,
        load_change: float,
    ) -> Tuple[float, dict]:
        """복합 위험 인자 기반으로 채터/진동 위험도를 계산합니다."""

        if not is_cutting or ap <= 1e-6 or ae <= 1e-6:
            return 0.0, {}

        ae_ratio = ae / D if D > 0.0 else 0.0
        ap_ratio = ap / D if D > 0.0 else 0.0
        risk_engagement = min(1.0, 0.55 * ae_ratio + 0.45 * min(ap_ratio / 0.80, 1.0))

        if Vc <= 0.0:
            risk_speed = 0.0
        elif Vc < 30.0:
            risk_speed = 0.80
        elif Vc < 80.0:
            risk_speed = 0.45
        elif Vc < 220.0:
            risk_speed = 0.15
        elif Vc < 420.0:
            risk_speed = 0.28
        else:
            risk_speed = 0.42

        risk_direction = min(1.0, direction_change_angle / 180.0)
        if direction_change_angle < 45.0:
            risk_direction *= 0.30

        risk_plunge = 0.95 if is_plunge else (0.40 if is_ramp else 0.0)
        risk_force = min(1.0, spindle_load_pct / 95.0)
        risk_load_change = min(1.0, load_change / 22.0)
        risk_chipload = min(1.0, fz / max(self.config.reference_chipload_mm, 1e-6))

        base_risk = (
            self.config.w_engagement * risk_engagement
            + self.config.w_speed * risk_speed
            + self.config.w_direction_change * risk_direction
            + self.config.w_plunge * risk_plunge
            + self.config.w_force * risk_force
            + self.config.w_load_change * risk_load_change
            + self.config.w_chipload * risk_chipload
        )

        overhang_penalty = max(0.8, self.config.tool_overhang_factor)
        stiffness_penalty = 1.0 / max(0.55, self.config.machine_stiffness)
        chatter_score = base_risk * overhang_penalty * stiffness_penalty
        chatter_score *= 0.90 + 0.35 * aggressiveness_score
        chatter_score = min(1.0, chatter_score * self.config.chatter_sensitivity)

        risk_factors = {
            "ae_mm": round(ae, 3),
            "ap_mm": round(ap, 3),
            "engagement_risk": round(risk_engagement, 3),
            "speed_risk": round(risk_speed, 3),
            "direction_change_risk": round(risk_direction, 3),
            "entry_risk": round(risk_plunge, 3),
            "force_risk": round(risk_force, 3),
            "load_change_risk": round(risk_load_change, 3),
            "chipload_risk": round(risk_chipload, 3),
            "tool_overhang_factor": round(overhang_penalty, 3),
            "machine_stiffness_factor": round(stiffness_penalty, 3),
        }
        return float(np.clip(chatter_score, 0.0, 1.0)), risk_factors

    def _compute_axis_force_components(
        self,
        seg: MotionSegment,
        cutting_force: float,
        ae_ratio: float,
        ap_ratio: float,
        is_plunge: bool,
        is_ramp: bool,
    ) -> Tuple[float, float, float]:
        """
        절삭력을 이동 방향 기준 X/Y/Z 축 성분으로 분해합니다.

        [근사 가정]
        - XY 접선력은 공구 진행 방향으로 작용
        - XY 반경력은 공구를 옆으로 미는 방향으로 작용
        - Z 축력은 AP와 진입 방식 영향을 크게 받음
        """
        if cutting_force <= 0.0:
            return 0.0, 0.0, 0.0

        delta = seg.end_pos - seg.start_pos
        xy_vec = np.array([delta[0], delta[1]], dtype=float)
        dist_xy = float(np.linalg.norm(xy_vec))

        if dist_xy > 1e-9:
            tangent = xy_vec / dist_xy
        else:
            tangent = np.array([math.sqrt(0.5), math.sqrt(0.5)], dtype=float)
        normal = np.array([-tangent[1], tangent[0]], dtype=float)

        radial_ratio = self.config.radial_force_ratio_base + (
            self.config.radial_force_ratio_gain * min(1.0, ae_ratio)
        )
        axial_ratio = self.config.axial_force_ratio_base + (
            self.config.axial_force_ratio_gain * min(1.2, ap_ratio)
        )

        if is_plunge:
            tangential_force = cutting_force * 0.30
            radial_force = cutting_force * max(0.18, radial_ratio * 0.55)
            axial_force = cutting_force * max(0.85, axial_ratio + 0.45)
        elif is_ramp:
            tangential_force = cutting_force * 0.85
            radial_force = cutting_force * (radial_ratio + 0.08)
            axial_force = cutting_force * (axial_ratio + 0.22)
        else:
            tangential_force = cutting_force
            radial_force = cutting_force * radial_ratio
            axial_force = cutting_force * axial_ratio

        tangential_components = np.abs(tangent * tangential_force)
        radial_components = np.abs(normal * radial_force)

        force_x = float(tangential_components[0] + radial_components[0])
        force_y = float(tangential_components[1] + radial_components[1])
        force_z = float(abs(axial_force))

        # 수직 플런지에서도 편심/불균형에 의한 측면 교란을 약하게 반영합니다.
        if is_plunge and dist_xy <= 1e-9:
            lateral_bias = cutting_force * 0.18
            force_x = max(force_x, lateral_bias)
            force_y = max(force_y, lateral_bias)

        return force_x, force_y, force_z

    def _compute_axis_vibration(
        self,
        force_x: float,
        force_y: float,
        force_z: float,
        chatter_score: float,
        spindle_load_pct: float,
        load_change: float,
        direction_change_angle: float,
        ae_ratio: float,
        ap_ratio: float,
        is_plunge: bool,
        is_ramp: bool,
    ) -> Tuple[float, float, float, float]:
        """
        축별 예상 진동(um)을 계산합니다.

        [근사식]
        - 기본 정적 변위 = 축력 / 축강성
        - 동적 증폭 = 채터 위험도 + 부하 급변 + 방향 전환 + overhang + 진입 방식
        - XY는 stepover/방향 전환 영향이 크고 Z는 AP/플런지 영향이 큼
        """
        if force_x <= 0.0 and force_y <= 0.0 and force_z <= 0.0:
            return 0.0, 0.0, 0.0, 0.0

        stiffness_scale = max(self.config.machine_stiffness, 0.55)
        stiff_x = max(5.0, self.config.x_axis_stiffness_n_per_um * stiffness_scale)
        stiff_y = max(5.0, self.config.y_axis_stiffness_n_per_um * stiffness_scale)
        stiff_z = max(5.0, self.config.z_axis_stiffness_n_per_um * stiffness_scale)

        load_norm = min(1.0, spindle_load_pct / 100.0)
        load_change_norm = min(1.0, load_change / 22.0)
        direction_norm = min(1.0, direction_change_angle / 90.0)
        overhang_norm = max(0.0, self.config.tool_overhang_factor - 1.0)
        entry_norm = 1.0 if is_plunge else (0.55 if is_ramp else 0.0)

        base_dynamic = (
            1.0
            + self.config.dynamic_vibration_gain * chatter_score
            + 0.18 * load_norm
            + 0.22 * load_change_norm
            + 0.12 * overhang_norm
        )
        xy_dynamic = base_dynamic * (
            1.0 + 0.12 * direction_norm + 0.10 * min(1.0, ae_ratio) + 0.08 * entry_norm
        )
        z_dynamic = base_dynamic * (1.0 + 0.18 * min(1.2, ap_ratio) + 0.30 * entry_norm)

        vibration_x_um = float(force_x / stiff_x * xy_dynamic)
        vibration_y_um = float(force_y / stiff_y * xy_dynamic)
        vibration_z_um = float(force_z / stiff_z * z_dynamic)
        resultant_vibration_um = float(
            math.sqrt(vibration_x_um**2 + vibration_y_um**2 + vibration_z_um**2)
        )
        return vibration_x_um, vibration_y_um, vibration_z_um, resultant_vibration_um

    def _build_segment_warnings(
        self,
        ae_ratio: float,
        ap_ratio: float,
        ap: float,
        spindle_load_pct: float,
        chatter_score: float,
        is_plunge: bool,
        is_ramp: bool,
        load_change: float,
        vibration_x_um: float,
        vibration_y_um: float,
        vibration_z_um: float,
        resultant_vibration_um: float,
    ) -> List[str]:
        """사용자에게 보여줄 세그먼트 경보 메시지를 구성합니다."""

        warnings: List[str] = []

        if ae_ratio >= 0.85:
            warnings.append("풀폭 절삭에 가까운 맞물림입니다.")
        elif ae_ratio >= self.config.aggressive_ae_ratio:
            warnings.append("반경방향 맞물림이 커서 절삭 부하가 증가합니다.")

        if ap_ratio >= self.config.aggressive_ap_ratio:
            warnings.append("축방향 절입이 커서 절삭력이 증가합니다.")

        if is_plunge and ap >= max(self.config.default_ap_mm * 1.2, 2.0):
            warnings.append("깊은 플런지 진입으로 불안정 가능성이 있습니다.")
        elif is_ramp and ap >= max(self.config.default_ap_mm, 1.0):
            warnings.append("램프 진입 구간으로 절삭 부하가 증가합니다.")

        if spindle_load_pct >= self.config.high_load_threshold_pct:
            warnings.append("스핀들 부하가 높습니다.")

        if load_change >= 18.0:
            warnings.append("블록 간 부하 변동이 큽니다.")

        if chatter_score >= self.config.unstable_chatter_threshold:
            warnings.append("채터/불안정 절삭 위험이 높습니다.")

        if vibration_x_um >= self.config.xy_vibration_warning_um:
            warnings.append("X축 예상 진동이 커서 측면 품질 저하 가능성이 있습니다.")
        if vibration_y_um >= self.config.xy_vibration_warning_um:
            warnings.append("Y축 예상 진동이 커서 측면 품질 저하 가능성이 있습니다.")
        if vibration_z_um >= self.config.z_vibration_warning_um:
            warnings.append("Z축 예상 진동이 커서 바닥면/깊이 품질 저하 가능성이 있습니다.")
        if resultant_vibration_um >= self.config.resultant_vibration_warning_um:
            warnings.append("합성 진동이 높습니다. AE/AP 또는 이송 조건 완화를 권장합니다.")

        return warnings

    def _compute_direction_change(self, seg: MotionSegment) -> float:
        """직전 세그먼트 대비 방향 전환 각도를 계산합니다."""

        vec = seg.end_pos - seg.start_pos
        length = float(np.linalg.norm(vec))
        if length <= 1e-9:
            self._prev_direction = None
            return 0.0

        current_dir = vec / length
        angle = 0.0
        if self._prev_direction is not None:
            cos_a = float(np.clip(np.dot(current_dir, self._prev_direction), -1.0, 1.0))
            angle = math.degrees(math.acos(cos_a))
        self._prev_direction = current_dir
        return angle

    def _estimate_segment_removed_volume(
        self,
        seg: MotionSegment,
        result: SegmentMachiningResult,
    ) -> float:
        """세그먼트 길이와 AE/AP로 제거 체적을 근사합니다."""

        if not result.is_cutting:
            return 0.0
        return float(result.radial_depth_ae * result.axial_depth_ap * seg.get_distance())

    def _apply_segment_to_stock(
        self,
        stock_model: StockModel,
        seg: MotionSegment,
        tool: Tool,
        result: SegmentMachiningResult,
    ):
        """
        분석 중 얻은 세그먼트 절삭 결과를 임시 스톡에 반영합니다.

        이렇게 해야 다음 세그먼트의 AE/AP를 현재 남아 있는 소재 기준으로 다시 추정할 수 있습니다.
        """
        if not result.is_cutting:
            return

        metrics = {
            "spindle_load_pct": result.spindle_load_pct,
            "chatter_risk_score": result.chatter_risk_score,
        }

        points = self._segment_to_points(seg, tool)
        for start, end in zip(points[:-1], points[1:]):
            stock_model.remove_material(start, end, tool, metrics)

    def _segment_to_points(self, seg: MotionSegment, tool: Tool) -> np.ndarray:
        """세그먼트를 스톡 갱신용 polyline 점집합으로 변환합니다."""

        if not seg.is_arc or seg.arc_center is None or seg.arc_radius is None:
            return np.array([seg.start_pos, seg.end_pos], dtype=float)

        center = seg.arc_center
        start = seg.start_pos
        end = seg.end_pos
        clockwise = seg.motion_type == MotionType.ARC_CW

        start_angle = math.atan2(start[1] - center[1], start[0] - center[0])
        end_angle = math.atan2(end[1] - center[1], end[0] - center[0])

        if clockwise:
            if end_angle > start_angle:
                end_angle -= 2 * math.pi
        elif end_angle < start_angle:
            end_angle += 2 * math.pi

        total_angle = abs(end_angle - start_angle)
        arc_length = seg.arc_radius * total_angle
        step_pitch = max(tool.radius * 0.5, 0.5)
        steps = max(8, min(96, int(math.ceil(arc_length / step_pitch))))

        points = np.zeros((steps + 1, 3), dtype=float)
        for i in range(steps + 1):
            t = i / steps
            angle = start_angle + (end_angle - start_angle) * t
            points[i, 0] = center[0] + seg.arc_radius * math.cos(angle)
            points[i, 1] = center[1] + seg.arc_radius * math.sin(angle)
            points[i, 2] = start[2] + (end[2] - start[2]) * t
        return points


def create_machining_model_from_config(config_dict: dict) -> MachiningModel:
    """설정 딕셔너리에서 MachiningModel을 생성합니다."""

    return MachiningModel(MachiningModelConfig(config_dict))
