"""
가공 해석 오케스트레이터

공구경로를 세그먼트 단위로 해석하여
부하/진동/채터/공구 메타/디버그 정보를 하나의 결과로 통합합니다.
"""
from __future__ import annotations

import math
import os
from dataclasses import replace as dc_replace
from typing import Dict, List, Optional

import numpy as np

from app.geometry.stock_model import StockModel
from app.machines.machine_profile import MachineProfile, MachineProfileRegistry
from app.models.chatter_model import StabilityLobeChatterModel
from app.models.cutting_conditions import (
    CuttingConditionExtractor,
    STATE_AIR_FEED,
    STATE_CUTTING,
    STATE_ENTRY_CUT,
    STATE_EXIT_CUT,
    STATE_PLUNGE,
    STATE_RAPID,
    UP_MILLING,
    compute_engagement_angles,
)
from app.models.cutting_force_model import (
    MATERIAL_FORCE_COEFFICIENTS,
    MechanisticCuttingForceModel,
)
from app.models.machining_result import (
    ChatterRiskLevel,
    MachiningAnalysis,
    SegmentMachiningResult,
)
from app.models.model_interfaces import ChatterRiskPredictor, SpindleLoadPredictor
from app.models.tool import Tool, ToolType
from app.models.toolpath import MotionSegment, MotionType, Toolpath
from app.utils.logger import get_logger

logger = get_logger("machining_model")


class MachiningModelConfig:
    """가공 해석 모델 설정"""

    def __init__(self, config_dict: Optional[dict] = None):
        cfg = config_dict or {}

        self.material: str = cfg.get("material", "aluminum")
        self.default_ae_ratio: float = float(cfg.get("default_ae_ratio", 0.5))
        self.default_ap_mm: float = float(cfg.get("default_ap_mm", 2.0))
        self.default_flute_count: int = int(cfg.get("default_flute_count", 4))
        self.milling_mode: str = cfg.get("milling_mode", UP_MILLING)
        self.machine_profile_id: str = cfg.get("machine_profile_id", "t4000")
        self.mrr_reference_mm3min: float = float(cfg.get("mrr_reference_mm3min", 50000.0))

        self.high_load_threshold_pct: float = float(cfg.get("high_load_threshold_pct", 80.0))
        self.aggressive_ap_ratio: float = float(cfg.get("aggressive_ap_ratio", 0.50))
        self.aggressive_ae_ratio: float = float(cfg.get("aggressive_ae_ratio", 0.65))
        self.unstable_chatter_threshold: float = float(cfg.get("unstable_chatter_threshold", 0.65))
        self.motion_risk_warning_threshold: float = float(cfg.get("motion_risk_warning_threshold", 0.58))
        self.xy_vibration_warning_um: float = float(cfg.get("xy_vibration_warning_um", 12.0))
        self.z_vibration_warning_um: float = float(cfg.get("z_vibration_warning_um", 9.0))
        self.resultant_vibration_warning_um: float = float(cfg.get("resultant_vibration_warning_um", 16.0))
        self.rapid_vibration_warning_um: float = float(cfg.get("rapid_vibration_warning_um", 6.0))

        self.engagement_sample_count: int = int(cfg.get("engagement_sample_count", 7))
        self.entry_contact_threshold: float = float(cfg.get("entry_contact_threshold", 0.45))
        self.exit_contact_threshold: float = float(cfg.get("exit_contact_threshold", 0.60))


class MachiningModel:
    """공구경로 해석 모델"""

    def __init__(
        self,
        config: Optional[MachiningModelConfig] = None,
        load_predictor: Optional[SpindleLoadPredictor] = None,
        chatter_predictor: Optional[ChatterRiskPredictor] = None,
        machine_profile: Optional[MachineProfile] = None,
    ):
        self.config = config or MachiningModelConfig()

        if machine_profile is not None:
            self._machine_profile = machine_profile
        else:
            profile_id = self.config.machine_profile_id
            loaded = MachineProfileRegistry.get(profile_id)
            if loaded is None:
                configs_dir = os.path.normpath(
                    os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        "..",
                        "..",
                        "configs",
                        "machines",
                    )
                )
                MachineProfileRegistry.load_from_directory(configs_dir)
                loaded = MachineProfileRegistry.get(profile_id)
            self._machine_profile = loaded or MachineProfileRegistry.get_default()

        logger.info(
            "기계 프로파일 적용: %s (ID=%s)",
            self._machine_profile.name,
            self._machine_profile.model_id,
        )

        self._load_predictor: SpindleLoadPredictor = load_predictor or MechanisticCuttingForceModel()
        self._chatter_predictor: ChatterRiskPredictor = chatter_predictor or StabilityLobeChatterModel()
        self._extractor = CuttingConditionExtractor(
            default_ae_ratio=self.config.default_ae_ratio,
            default_ap_mm=self.config.default_ap_mm,
            default_flute_count=self.config.default_flute_count,
            milling_mode=self.config.milling_mode,
            rapid_traverse_mm_min=self._machine_profile.rapid_traverse_mm_min,
        )

        machine_params = self._machine_profile.to_params_dict()
        self._load_params = {
            **machine_params,
            "material": self.config.material,
            "mrr_reference_mm3min": self.config.mrr_reference_mm3min,
        }
        self._chatter_params = dict(machine_params)

        self._prev_load: float = 0.0

    @property
    def machine_profile(self) -> MachineProfile:
        """현재 적용 중인 기계 프로파일"""

        return self._machine_profile

    def analyze_toolpath(
        self,
        toolpath: Toolpath,
        tools: Dict[int, Tool],
        stock_model: Optional[StockModel] = None,
    ) -> MachiningAnalysis:
        """전체 공구경로를 해석합니다."""

        logger.info(
            "가공 해석 시작: %d개 세그먼트, 기계=%s",
            len(toolpath.segments),
            self._machine_profile.name,
        )

        self._prev_load = 0.0
        self._extractor.reset()

        analysis_stock = stock_model.copy() if stock_model is not None else None
        results: List[SegmentMachiningResult] = []
        total_removed_volume = 0.0

        for index, seg in enumerate(toolpath.segments):
            prev_result = results[-1] if results else None
            next_seg = toolpath.segments[index + 1] if index + 1 < len(toolpath.segments) else None
            tool = self._resolve_tool(seg, tools)
            result = self._analyze_segment(
                seg=seg,
                tool=tool,
                stock_model=analysis_stock,
                prev_result=prev_result,
                next_seg=next_seg,
            )
            results.append(result)

            if result.is_cutting:
                self._prev_load = result.spindle_load_pct
                total_removed_volume += result.radial_depth_ae * result.axial_depth_ap * seg.get_distance()
                if analysis_stock is not None:
                    self._apply_segment_to_stock(analysis_stock, seg, tool, result)

        analysis = MachiningAnalysis(
            results=results,
            model_params={
                "material": self.config.material,
                "spindle_rated_power_w": self._machine_profile.spindle_rated_power_w,
                "machine_efficiency": self._machine_profile.machine_efficiency,
                "machine_stiffness": self._machine_profile.machine_stiffness_factor,
                "k_n_per_um": self._machine_profile.tool_tip_stiffness_n_per_um,
                "zeta": self._machine_profile.damping_ratio,
                "f_natural_hz": self._machine_profile.natural_frequency_hz,
                "rapid_vibration_sensitivity": self._machine_profile.rapid_vibration_sensitivity,
                "servo_jerk_sensitivity": self._machine_profile.servo_jerk_sensitivity,
                "xy_vibration_warning_um": self.config.xy_vibration_warning_um,
                "z_vibration_warning_um": self.config.z_vibration_warning_um,
                "resultant_vibration_warning_um": self.config.resultant_vibration_warning_um,
                "rapid_vibration_warning_um": self.config.rapid_vibration_warning_um,
                "motion_risk_warning_threshold": self.config.motion_risk_warning_threshold,
            },
            machine_profile_name=self._machine_profile.name,
            machine_profile_id=self._machine_profile.model_id,
        )
        analysis.compute_statistics()
        analysis.total_mrr = total_removed_volume

        logger.info(
            "가공 해석 완료: 최대부하 %.1f%%, 최대채터위험 %.1f%%, 최대합성진동 %.2f μm",
            analysis.max_spindle_load_pct,
            analysis.max_chatter_risk * 100.0,
            analysis.max_resultant_vibration_um,
        )
        return analysis

    def _resolve_tool(self, seg: MotionSegment, tools: Dict[int, Tool]) -> Tool:
        """공구가 누락된 경우에도 모델이 동작하도록 보수적 fallback 공구를 만듭니다."""

        tool = tools.get(seg.tool_number)
        if tool is not None:
            return tool

        diameter = 10.0
        logger.warning("공구 T%d가 정의되지 않아 fallback 공구를 사용합니다.", seg.tool_number)
        return Tool(
            tool_number=seg.tool_number,
            name=f"임시 공구 T{seg.tool_number}",
            tool_type=ToolType.END_MILL,
            tool_category="EM",
            diameter=diameter,
            length=diameter * 6.0,
            flute_length=max(self.config.default_ap_mm * 3.0, diameter * 2.0),
            corner_radius=0.0,
            material="카바이드",
            flute_count=self.config.default_flute_count,
            overhang_mm=diameter * 4.0,
            notes="정의되지 않은 공구로 인해 fallback 사용",
        )

    def _analyze_segment(
        self,
        seg: MotionSegment,
        tool: Tool,
        stock_model: Optional[StockModel],
        prev_result: Optional[SegmentMachiningResult],
        next_seg: Optional[MotionSegment],
    ) -> SegmentMachiningResult:
        """단일 세그먼트를 해석합니다."""

        diameter_mm = max(tool.diameter_mm, 0.1)
        features = self._extractor.extract(seg, tool)
        contact_ratio = 0.0

        if stock_model is not None and features.is_cutting:
            engagement = stock_model.estimate_segment_engagement(
                seg.start_pos,
                seg.end_pos,
                tool,
                sample_count=self.config.engagement_sample_count,
            )
            engaged_n = int(engagement.get("engaged_samples", 0))

            if engaged_n > 0:
                ae_s = float(np.clip(engagement["ae"], 0.0, diameter_mm))
                ap_s = float(np.clip(engagement["ap"], 0.0, tool.flute_length))
                contact_ratio = float(
                    np.clip(
                        engagement.get("engaged_path_ratio", engagement.get("engagement_ratio", 0.0)),
                        0.0,
                        1.0,
                    )
                )

                if tool.is_drill:
                    if features.is_plunge:
                        ae_s = min(diameter_mm, max(ae_s, diameter_mm * 0.90))
                    else:
                        ae_s = min(ae_s, diameter_mm * 0.35)
                elif tool.tool_category == "REM":
                    ae_s = min(diameter_mm, ae_s * 0.92)

                if tool.is_drill and features.is_plunge:
                    phi_st_s, phi_ex_s = 0.0, math.pi
                else:
                    phi_st_s, phi_ex_s = compute_engagement_angles(ae_s, diameter_mm, self.config.milling_mode)

                state = self._classify_motion_state(features, prev_result, next_seg, contact_ratio)
                features = dc_replace(
                    features,
                    axial_depth_ap=ap_s,
                    radial_depth_ae=ae_s,
                    radial_ratio=ae_s / diameter_mm if diameter_mm > 0.0 else 0.0,
                    phi_entry_rad=phi_st_s,
                    phi_exit_rad=phi_ex_s,
                    phi_entry_deg=math.degrees(phi_st_s),
                    phi_exit_deg=math.degrees(phi_ex_s),
                    engagement_arc_deg=math.degrees(phi_ex_s - phi_st_s),
                    mrr_mm3_per_min=ae_s * ap_s * max(features.effective_feedrate, 0.0),
                    machining_state=state,
                    contact_ratio=contact_ratio,
                )
            else:
                features = dc_replace(
                    features,
                    axial_depth_ap=0.0,
                    radial_depth_ae=0.0,
                    radial_ratio=0.0,
                    phi_entry_rad=0.0,
                    phi_exit_rad=0.0,
                    phi_entry_deg=0.0,
                    phi_exit_deg=0.0,
                    engagement_arc_deg=0.0,
                    mrr_mm3_per_min=0.0,
                    is_cutting=False,
                    machining_state=STATE_AIR_FEED,
                    contact_ratio=0.0,
                )
        elif seg.motion_type == MotionType.RAPID:
            features = dc_replace(
                features,
                is_cutting=False,
                machining_state=STATE_RAPID,
                axial_depth_ap=0.0,
                radial_depth_ae=0.0,
                radial_ratio=0.0,
                mrr_mm3_per_min=0.0,
            )
        elif features.is_cutting:
            state = self._classify_motion_state(features, prev_result, next_seg, 1.0)
            features = dc_replace(features, machining_state=state, contact_ratio=1.0)

        load_pred = self._load_predictor.predict(features, self._load_params)

        chatter_params = dict(self._chatter_params)
        material_coeff = load_pred.debug_components.get("coefficients")
        if isinstance(material_coeff, dict) and material_coeff.get("Ktc"):
            chatter_params["Ktc"] = float(material_coeff["Ktc"])
            chatter_params["Krc_ratio"] = float(material_coeff["Krc"]) / max(float(material_coeff["Ktc"]), 1e-6)
        else:
            base_coeff = MATERIAL_FORCE_COEFFICIENTS.get(self.config.material, MATERIAL_FORCE_COEFFICIENTS["default"])
            chatter_params["Ktc"] = float(base_coeff["Ktc"])
            chatter_params["Krc_ratio"] = float(base_coeff["Krc_ratio"])

        chatter_pred = self._chatter_predictor.predict(features, load_pred, chatter_params)
        risk_level = self._classify_chatter_level(features.is_cutting, chatter_pred.chatter_risk_score)

        load_change = abs(load_pred.spindle_load_pct - self._prev_load)
        warning_messages = self._build_segment_warnings(
            machining_state=features.machining_state,
            tool_category=features.tool_category,
            ae_ratio=features.radial_ratio,
            ap=features.axial_depth_ap,
            diameter=diameter_mm,
            spindle_load_pct=load_pred.spindle_load_pct,
            chatter_score=chatter_pred.chatter_risk_score,
            motion_risk_score=chatter_pred.motion_risk_score,
            motion_vibration_um=chatter_pred.motion_vibration_um,
            is_plunge=features.is_plunge,
            is_ramp=features.is_ramp,
            load_change=load_change,
            vibration_x_um=chatter_pred.vibration_x_um,
            vibration_y_um=chatter_pred.vibration_y_um,
            vibration_z_um=chatter_pred.vibration_z_um,
            resultant_vibration_um=chatter_pred.resultant_vibration_um,
            stability_margin=chatter_pred.stability_margin,
        )
        if "fallback" in tool.notes or "정의되지" in tool.notes:
            warning_messages.insert(0, f"T{tool.tool_number} 공구 정의가 없어 fallback 공구 모델을 사용했습니다.")

        risk_factors = dict(chatter_pred.risk_factors)
        risk_factors.update(
            {
                "tool_number": tool.tool_number,
                "tool_name": tool.name,
                "tool_category": tool.tool_category,
                "tool_overhang_mm": round(tool.effective_overhang_mm, 3),
                "contact_ratio": round(features.contact_ratio, 3),
                "estimated_ft_n": round(load_pred.cutting_force_ft, 3),
                "estimated_fr_n": round(load_pred.cutting_force_fr, 3),
                "estimated_fa_n": round(load_pred.cutting_force_fa, 3),
                "estimated_fx_n": round(load_pred.force_x, 3),
                "estimated_fy_n": round(load_pred.force_y, 3),
                "estimated_fz_n": round(load_pred.force_z, 3),
                "torque_nm": round(load_pred.torque_nm, 3),
                "spindle_power_w": round(load_pred.power_w, 3),
                "baseline_load_pct": round(load_pred.baseline_load_pct, 3),
                "axis_motion_load_pct": round(load_pred.axis_motion_load_pct, 3),
                "cutting_load_pct": round(load_pred.cutting_load_pct, 3),
                "spindle_load_pct": round(load_pred.spindle_load_pct, 3),
                "mrr_mm3min": round(features.mrr_mm3_per_min, 3),
                "motion_vibration_um": round(chatter_pred.motion_vibration_um, 3),
                "cutting_vibration_um": round(chatter_pred.cutting_vibration_um, 3),
                "motion_risk_score": round(chatter_pred.motion_risk_score, 3),
                "chatter_raw_score": round(chatter_pred.chatter_raw_score, 3),
            }
        )
        if load_pred.debug_components:
            risk_factors["spindle_load_debug"] = dict(load_pred.debug_components)

        engagement_ratio = max(
            features.contact_ratio,
            features.radial_ratio * min(1.0, features.axial_depth_ap / max(tool.flute_length, diameter_mm)),
        )

        return SegmentMachiningResult(
            segment_id=seg.segment_id,
            spindle_speed=features.spindle_rpm,
            feedrate=features.effective_feedrate,
            tool_diameter=diameter_mm,
            flute_count=features.flute_count,
            tool_category=features.tool_category,
            tool_overhang_mm=tool.effective_overhang_mm,
            cutting_speed=features.cutting_speed_vc,
            feed_per_tooth=features.feed_per_tooth_fz,
            axial_depth_ap=features.axial_depth_ap,
            radial_depth_ae=features.radial_depth_ae,
            radial_ratio=features.radial_ratio,
            engagement_ratio=engagement_ratio,
            material_removal_rate=features.mrr_mm3_per_min,
            estimated_cutting_force=load_pred.cutting_force_ft,
            estimated_spindle_power=load_pred.power_w,
            spindle_load_pct=load_pred.spindle_load_pct,
            aggressiveness_score=load_pred.aggressiveness,
            estimated_force_x=load_pred.force_x,
            estimated_force_y=load_pred.force_y,
            estimated_force_z=load_pred.force_z,
            vibration_x_um=chatter_pred.vibration_x_um,
            vibration_y_um=chatter_pred.vibration_y_um,
            vibration_z_um=chatter_pred.vibration_z_um,
            resultant_vibration_um=chatter_pred.resultant_vibration_um,
            motion_vibration_um=chatter_pred.motion_vibration_um,
            cutting_vibration_um=chatter_pred.cutting_vibration_um,
            chatter_risk_score=chatter_pred.chatter_risk_score,
            motion_risk_score=chatter_pred.motion_risk_score,
            chatter_risk_level=risk_level,
            direction_change_angle=features.direction_change_deg,
            is_plunge=features.is_plunge,
            is_ramp=features.is_ramp,
            is_cutting=features.is_cutting,
            machining_state=features.machining_state,
            contact_ratio=features.contact_ratio,
            baseline_load_pct=load_pred.baseline_load_pct,
            axis_motion_load_pct=load_pred.axis_motion_load_pct,
            cutting_load_pct=load_pred.cutting_load_pct,
            risk_factors=risk_factors,
            warning_messages=warning_messages,
        )

    def _classify_motion_state(
        self,
        features,
        prev_result: Optional[SegmentMachiningResult],
        next_seg: Optional[MotionSegment],
        contact_ratio: float,
    ) -> str:
        """상태별 motion state를 세분화합니다."""

        if features.machining_state == STATE_RAPID:
            return STATE_RAPID
        if not features.is_cutting:
            return STATE_AIR_FEED
        if features.is_plunge:
            return STATE_PLUNGE

        prev_is_cutting = bool(prev_result and prev_result.is_cutting)
        next_is_cutting_move = bool(next_seg and next_seg.is_cutting_move and next_seg.motion_type != MotionType.RAPID)

        if not prev_is_cutting or contact_ratio <= self.config.entry_contact_threshold:
            return STATE_ENTRY_CUT
        if not next_is_cutting_move or contact_ratio <= self.config.exit_contact_threshold:
            return STATE_EXIT_CUT
        return STATE_CUTTING

    @staticmethod
    def _classify_chatter_level(is_cutting: bool, chatter_score: float) -> ChatterRiskLevel:
        """절삭 채터 수준을 단계화합니다."""

        if not is_cutting:
            return ChatterRiskLevel.NONE
        if chatter_score < 0.25:
            return ChatterRiskLevel.LOW
        if chatter_score < 0.50:
            return ChatterRiskLevel.MEDIUM
        if chatter_score < 0.75:
            return ChatterRiskLevel.HIGH
        return ChatterRiskLevel.CRITICAL

    def _build_segment_warnings(
        self,
        machining_state: str,
        tool_category: str,
        ae_ratio: float,
        ap: float,
        diameter: float,
        spindle_load_pct: float,
        chatter_score: float,
        motion_risk_score: float,
        motion_vibration_um: float,
        is_plunge: bool,
        is_ramp: bool,
        load_change: float,
        vibration_x_um: float,
        vibration_y_um: float,
        vibration_z_um: float,
        resultant_vibration_um: float,
        stability_margin: float,
    ) -> List[str]:
        """경보 메시지를 생성합니다."""

        warnings: List[str] = []

        if machining_state == STATE_RAPID:
            if motion_risk_score >= self.config.motion_risk_warning_threshold:
                warnings.append("급속 이송의 방향 전환/가감속 충격이 큽니다.")
            if motion_vibration_um >= self.config.rapid_vibration_warning_um:
                warnings.append("급속 이송 진동이 높습니다. 코너링/짧은 블록을 점검하세요.")
            return warnings

        if machining_state == STATE_AIR_FEED:
            if motion_risk_score >= self.config.motion_risk_warning_threshold:
                warnings.append("공중이송이지만 과도한 가감속/코너링으로 진동이 큽니다.")
            return warnings

        if tool_category == "DR" and not is_plunge:
            warnings.append("드릴 계열 공구의 측면 절삭은 보수적으로 해석됩니다.")

        if ae_ratio >= 0.85:
            warnings.append("풀폭 절삭에 가까운 맞물림입니다.")
        elif ae_ratio >= self.config.aggressive_ae_ratio:
            warnings.append("반경방향 맞물림이 커서 절삭 부하가 증가합니다.")

        ap_ratio = ap / diameter if diameter > 0.0 else 0.0
        if ap_ratio >= self.config.aggressive_ap_ratio:
            warnings.append("축방향 절입이 커서 절삭력이 증가합니다.")

        if is_plunge and ap >= max(self.config.default_ap_mm * 1.2, 2.0):
            warnings.append("깊은 플런지 진입으로 축방향 불안정 가능성이 있습니다.")
        elif is_ramp and ap >= max(self.config.default_ap_mm, 1.0):
            warnings.append("램프 진입 구간으로 절삭 부하가 증가합니다.")

        if spindle_load_pct >= self.config.high_load_threshold_pct:
            warnings.append(f"스핀들 부하가 높습니다 ({spindle_load_pct:.1f}%).")

        if load_change >= 18.0:
            warnings.append("블록 간 부하 변동이 큽니다.")

        if stability_margin < 1.0:
            warnings.append(f"안정성 마진 SM={stability_margin:.2f} < 1: 채터 불안정 구간입니다.")
        elif stability_margin < 1.5:
            warnings.append(f"안정성 마진 SM={stability_margin:.2f}: 안정 경계에 가깝습니다.")
        elif chatter_score >= self.config.unstable_chatter_threshold:
            warnings.append("채터/불안정 절삭 위험이 높습니다.")

        if motion_risk_score >= self.config.motion_risk_warning_threshold and machining_state in {
            STATE_ENTRY_CUT,
            STATE_EXIT_CUT,
            STATE_PLUNGE,
        }:
            warnings.append("과도 구간의 이송 충격이 절삭 진동을 키울 수 있습니다.")

        if vibration_x_um >= self.config.xy_vibration_warning_um:
            warnings.append("X축 예상 진동이 커서 측면 품질 저하 가능성이 있습니다.")
        if vibration_y_um >= self.config.xy_vibration_warning_um:
            warnings.append("Y축 예상 진동이 커서 측면 품질 저하 가능성이 있습니다.")
        if vibration_z_um >= self.config.z_vibration_warning_um:
            warnings.append("Z축 예상 진동이 커서 바닥면/깊이 품질 저하 가능성이 있습니다.")
        if resultant_vibration_um >= self.config.resultant_vibration_warning_um:
            warnings.append("합성 진동이 높습니다. AE/AP 또는 이송 조건 완화를 권장합니다.")

        return warnings

    def _apply_segment_to_stock(
        self,
        stock_model: StockModel,
        seg: MotionSegment,
        tool: Tool,
        result: SegmentMachiningResult,
    ):
        """절삭 결과를 스톡에 반영합니다."""

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
        """원호 세그먼트를 스톡 반영용 polyline으로 변환합니다."""

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
                end_angle -= 2.0 * math.pi
        elif end_angle < start_angle:
            end_angle += 2.0 * math.pi

        total_angle = abs(end_angle - start_angle)
        arc_length = seg.arc_radius * total_angle
        step_pitch = max(tool.radius_mm * 0.5, 0.5)
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
    """설정 딕셔너리로부터 `MachiningModel`을 생성합니다."""

    return MachiningModel(MachiningModelConfig(config_dict))
