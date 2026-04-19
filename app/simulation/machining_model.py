"""
가공 해석 모델(Machining Model) 오케스트레이터 모듈

NC 공구경로를 세그먼트 단위로 해석하여 스핀들 부하, 채터 위험도,
X/Y/Z 축별 진동 등을 추정합니다.

[주요 개선사항 - 비현실 모델 수정]

1. 공중 이송(G1 Air-Cut) vs 절삭 분리
   - 이전: G1 이동이면 무조건 ae=0.5D 적용 → 공중이송에서도 절삭급 부하 발생
   - 개선: stock_model이 있을 때 engaged_samples==0이면 is_cutting=False로 강제 전환
   - 스핀들 부하 = baseline + axis_motion (절삭 성분 없음) → 공중이송 ~8~12%

2. 채터 위험도 포화 방지
   - 이전: 선형 공식 + 가산 보정 → 거의 항상 100%
   - 개선: 비선형 시그모이드 공식 + 승산적 보정 → 의미 있는 분포

3. 기계 특성 반영 (DN Solutions T4000)
   - 이전: 하드코딩된 7500W 단일 값
   - 개선: MachineProfile 객체를 통해 모든 파라미터 공급

[스핀들 부하 분해]
    total_load = baseline_component + axis_motion_component + cutting_component

    비절삭 (G0/G1 공중이송):
        total ≈ 7~12% (기저 7% + 이송 속도에 비례 axis)

    실제 절삭:
        total = 7% + 1~3% + (Altintas 계산 절삭 부하)
        → 재료/조건에 따라 20~80%

[파이프라인]
  NC 세그먼트
      │
      ▼
  CuttingConditionExtractor   → CuttingFeatures (초기 추정)
      │
      ▼ (stock_model 있으면 AE/AP/접촉 보정)
  [Stock Engagement Gate]     → is_cutting 최종 결정
      │
      ├──▶ MechanisticCuttingForceModel → SpindleLoadPrediction (분해 포함)
      │
      └──▶ StabilityLobeChatterModel   → ChatterRiskPrediction (비선형 점수)

[교체 지점]
  - SpindleLoadPredictor 인터페이스를 구현하는 ML 모델로 교체 가능
  - ChatterRiskPredictor 인터페이스를 구현하는 ML 모델로 교체 가능
  - docs/model_replacement_guide.md 참조

[참고 문헌]
  [1] Altintas, Y. (2000). Manufacturing Automation. Cambridge.
  [2] Altintas, Y., & Budak, E. (1995). CIRP Annals, 44(1), 357–362.
  [3] Schmitz, T.L., & Smith, K.S. (2009). Machining Dynamics. Springer.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np

from app.geometry.stock_model import StockModel
from app.machines.machine_profile import MachineProfile, MachineProfileRegistry
from app.models.cutting_conditions import (
    CuttingConditionExtractor,
    DOWN_MILLING,
    SLOTTING,
    UP_MILLING,
    STATE_AIR_FEED,
    STATE_CUTTING,
    STATE_PLUNGE,
    STATE_RAPID,
)
from app.models.cutting_force_model import MechanisticCuttingForceModel
from app.models.chatter_model import StabilityLobeChatterModel
from app.models.machining_result import (
    ChatterRiskLevel,
    MachiningAnalysis,
    SegmentMachiningResult,
)
from app.models.model_interfaces import (
    ChatterRiskPredictor,
    SpindleLoadPredictor,
)
from app.models.tool import Tool, ToolType
from app.models.toolpath import MotionSegment, MotionType, Toolpath
from app.utils.logger import get_logger

logger = get_logger("machining_model")


class MachiningModelConfig:
    """
    가공 해석 모델 설정 파라미터

    모든 값은 `configs/simulation_options.yaml`의 `machining` 섹션에서 덮어쓸 수 있습니다.
    기계 특성값은 MachineProfile 객체로 분리됩니다.

    [수학 모델 파라미터]
    스핀들 부하 모델 (MechanisticCuttingForceModel):
        - material:           재료 키 (aluminum/steel_mild/steel_hard/stainless/titanium/cast_iron)
        - default_ae_ratio:   반경방향 맞물림 기본 비율 (ae/D, stock 없을 때 fallback)
        - default_ap_mm:      축방향 절입 기본값 (mm, stock 없을 때 fallback)
        - milling_mode:       업밀링/다운밀링/슬로팅

    채터 위험 모델 (StabilityLobeChatterModel):
        - (기계 특성 파라미터는 MachineProfile로 공급됨)

    기계 프로파일 (MachineProfile):
        - machine_profile_id: 사용할 기계 프로파일 ID (기본: t4000)
    """

    def __init__(self, config_dict: Optional[dict] = None):
        cfg = config_dict or {}

        # ---- 재료 ----
        self.material: str = cfg.get("material", "aluminum")

        # ---- 기본 절삭 조건 (stock 모델 없을 때 fallback) ----
        self.default_ae_ratio: float = float(cfg.get("default_ae_ratio", 0.5))
        self.default_ap_mm: float = float(cfg.get("default_ap_mm", 2.0))
        self.default_flute_count: int = int(cfg.get("default_flute_count", 4))
        self.milling_mode: str = cfg.get("milling_mode", UP_MILLING)

        # ---- 기계 프로파일 ID ----
        self.machine_profile_id: str = cfg.get("machine_profile_id", "t4000")

        # ---- MRR 참조값 (정규화용) ----
        self.mrr_reference_mm3min: float = float(cfg.get("mrr_reference_mm3min", 50000.0))

        # ---- 경보 기준 ----
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

        # ---- stock 탐색 샘플 수 ----
        self.engagement_sample_count: int = int(cfg.get("engagement_sample_count", 7))


class MachiningModel:
    """
    CNC 가공 해석 모델 클래스

    [파이프라인]
    1. CuttingConditionExtractor로 세그먼트→CuttingFeatures 추출
    2. StockModel 기반 AE/AP 보정 및 공중이송 판별 (is_cutting 최종 확정)
    3. SpindleLoadPredictor로 절삭력/스핀들 부하 예측 (분해 포함)
    4. ChatterRiskPredictor로 채터 위험도/진동 진폭 예측 (비선형)
    5. SegmentMachiningResult 조립 및 경보 생성

    [ML 교체 지점]
    - load_predictor: SpindleLoadPredictor를 구현한 임의의 모델
    - chatter_predictor: ChatterRiskPredictor를 구현한 임의의 모델
    - docs/model_replacement_guide.md 참조
    """

    def __init__(
        self,
        config: Optional[MachiningModelConfig] = None,
        load_predictor: Optional[SpindleLoadPredictor] = None,
        chatter_predictor: Optional[ChatterRiskPredictor] = None,
        machine_profile: Optional[MachineProfile] = None,
    ):
        self.config = config or MachiningModelConfig()

        # ── 기계 프로파일 로드 ──────────────────────────────────────
        if machine_profile is not None:
            self._machine_profile = machine_profile
        else:
            profile_id = self.config.machine_profile_id
            loaded = MachineProfileRegistry.get(profile_id)
            if loaded is None:
                # configs/machines/ 디렉토리에서 일괄 로드 시도
                import os
                configs_dir = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "..", "..", "configs", "machines"
                )
                configs_dir = os.path.normpath(configs_dir)
                MachineProfileRegistry.load_from_directory(configs_dir)
                loaded = MachineProfileRegistry.get(profile_id)
            self._machine_profile = loaded or MachineProfileRegistry.get_default()

        logger.info(
            "기계 프로파일 적용: %s (ID=%s)",
            self._machine_profile.name,
            self._machine_profile.model_id,
        )

        # ── 교체 가능한 예측기 (기본: 수학적 모델) ──────────────────
        self._load_predictor: SpindleLoadPredictor = (
            load_predictor or MechanisticCuttingForceModel()
        )
        self._chatter_predictor: ChatterRiskPredictor = (
            chatter_predictor or StabilityLobeChatterModel()
        )

        # ── 절삭 조건 추출기 ─────────────────────────────────────────
        self._extractor = CuttingConditionExtractor(
            default_ae_ratio=self.config.default_ae_ratio,
            default_ap_mm=self.config.default_ap_mm,
            default_flute_count=self.config.default_flute_count,
            milling_mode=self.config.milling_mode,
        )

        # ── 모델 파라미터 딕셔너리 (predictors에 전달) ───────────────
        # 기계 프로파일 파라미터가 기본값으로 사용되고
        # 재료 등 추가 파라미터가 병합됩니다.
        machine_params = self._machine_profile.to_params_dict()
        self._load_params: dict = {
            **machine_params,
            "material": self.config.material,
            "mrr_reference_mm3min": self.config.mrr_reference_mm3min,
        }
        self._chatter_params: dict = {
            **machine_params,
        }

        # ── 내부 상태 ─────────────────────────────────────────────────
        self._prev_load: float = 0.0

    @property
    def machine_profile(self) -> MachineProfile:
        """현재 사용 중인 기계 프로파일"""
        return self._machine_profile

    def analyze_toolpath(
        self,
        toolpath: Toolpath,
        tools: Dict[int, Tool],
        stock_model: Optional[StockModel] = None,
    ) -> MachiningAnalysis:
        """
        전체 공구경로를 세그먼트 단위로 해석합니다.

        Args:
            toolpath:    분석할 공구경로
            tools:       공구 번호 → Tool 매핑
            stock_model: 초기 스톡 모델 (있으면 AE/AP를 실제 잔여 소재 기준으로 계산하고
                         공중이송 세그먼트를 정확히 판별)

        Returns:
            MachiningAnalysis
        """
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
            tool = self._resolve_tool(seg, tools)
            result = self._analyze_segment(
                seg=seg,
                tool=tool,
                stock_model=analysis_stock,
                segment_index=index,
            )
            results.append(result)

            if result.is_cutting:
                self._prev_load = result.spindle_load_pct
                total_removed_volume += (
                    result.radial_depth_ae * result.axial_depth_ap * seg.get_distance()
                )
                if analysis_stock is not None:
                    self._apply_segment_to_stock(analysis_stock, seg, tool, result)

        analysis = MachiningAnalysis(
            results=results,
            model_params={
                "material": self.config.material,
                "spindle_rated_power_w": self._machine_profile.spindle_rated_power_w,
                "machine_efficiency": self._machine_profile.machine_efficiency,
                "machine_stiffness": self._machine_profile.machine_stiffness_factor,
                "tool_overhang_factor": 1.0 / max(self._machine_profile.tool_holder_rigidity, 0.1),
                "k_n_per_um": self._machine_profile.tool_tip_stiffness_n_per_um,
                "zeta": self._machine_profile.damping_ratio,
                "f_natural_hz": self._machine_profile.natural_frequency_hz,
                "default_ae_ratio": self.config.default_ae_ratio,
                "default_ap_mm": self.config.default_ap_mm,
                "xy_vibration_warning_um": self.config.xy_vibration_warning_um,
                "z_vibration_warning_um": self.config.z_vibration_warning_um,
                "resultant_vibration_warning_um": self.config.resultant_vibration_warning_um,
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
        stock_model: Optional[StockModel],
        segment_index: int,
    ) -> SegmentMachiningResult:
        """
        단일 세그먼트를 해석합니다.

        [공중이송 판별 로직 - 핵심 개선]
        이전 코드는 stock 접촉이 없어도 features.is_cutting=True를 유지하여
        ae=0.5D가 그대로 절삭력 계산에 사용되었습니다.

        개선:
          stock_model이 있고 engaged_samples==0이면
          → is_cutting=False로 강제 전환
          → 절삭 성분 없이 baseline+axis 부하만 계산됨
          → 공중이송 G1이 절삭보다 높은 부하를 보이는 문제 해결
        """
        del segment_index

        diameter = max(tool.diameter, 0.1)

        # ── 1. 절삭 조건 초기 추출 ─────────────────────────────────
        features = self._extractor.extract(seg, tool)

        # ── 2. 스톡 기반 AE/AP 보정 및 공중이송 판별 (핵심 수정) ──
        contact_ratio = 0.0
        machining_state = features.machining_state

        if stock_model is not None and features.is_cutting:
            engagement = stock_model.estimate_segment_engagement(
                seg.start_pos,
                seg.end_pos,
                tool,
                sample_count=self.config.engagement_sample_count,
            )
            total_samples = self.config.engagement_sample_count
            engaged_n = engagement.get("engaged_samples", 0)

            if engaged_n > 0:
                # ---- 실제 소재 접촉 ----
                from dataclasses import replace as dc_replace
                from app.models.cutting_conditions import compute_engagement_angles
                import math as _math

                ae_s = float(np.clip(engagement["ae"], 0.0, tool.diameter))
                ap_s = float(np.clip(engagement["ap"], 0.0, tool.flute_length))

                phi_st_s, phi_ex_s = compute_engagement_angles(
                    ae_s, diameter, self.config.milling_mode
                )

                contact_ratio = float(engaged_n) / max(float(total_samples), 1.0)
                machining_state = STATE_PLUNGE if features.is_plunge else STATE_CUTTING

                features = dc_replace(
                    features,
                    axial_depth_ap=ap_s,
                    radial_depth_ae=ae_s,
                    radial_ratio=ae_s / diameter if diameter > 0 else 0.0,
                    phi_entry_rad=phi_st_s,
                    phi_exit_rad=phi_ex_s,
                    phi_entry_deg=_math.degrees(phi_st_s),
                    phi_exit_deg=_math.degrees(phi_ex_s),
                    engagement_arc_deg=_math.degrees(phi_ex_s - phi_st_s),
                    mrr_mm3_per_min=ae_s * ap_s * seg.feedrate,
                    machining_state=machining_state,
                    contact_ratio=contact_ratio,
                )
            else:
                # ---- 소재 비접촉: 공중이송으로 강제 전환 ────────────
                # 이것이 "G1 공중이송이 절삭보다 높은 부하" 문제를 해결하는
                # 핵심 수정입니다.
                # engaged_samples==0 → 실제로 소재와 접촉하지 않음
                # → is_cutting=False로 전환하여 cutting_load_pct=0 보장
                from dataclasses import replace as dc_replace

                machining_state = STATE_AIR_FEED
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
                    is_cutting=False,    # ← 공중이송으로 강제 전환!
                    machining_state=machining_state,
                    contact_ratio=0.0,
                )

        elif seg.motion_type == MotionType.RAPID:
            machining_state = STATE_RAPID
            from dataclasses import replace as dc_replace
            features = dc_replace(features, machining_state=STATE_RAPID)

        # ── 3. 스핀들 부하 예측 (Altintas 기계론적 모델 + 부하 분해) ─
        # 재료별 Ktc를 채터 모델에도 전달
        from app.models.cutting_force_model import MATERIAL_FORCE_COEFFICIENTS
        mat_coeff = MATERIAL_FORCE_COEFFICIENTS.get(
            self.config.material, MATERIAL_FORCE_COEFFICIENTS["default"]
        )
        chatter_params = dict(self._chatter_params)
        chatter_params["Ktc"] = mat_coeff["Ktc"]
        chatter_params["Krc_ratio"] = mat_coeff["Krc_ratio"]

        load_pred = self._load_predictor.predict(features, self._load_params)

        # ── 4. 채터/진동 위험도 예측 (비선형 점수화) ────────────────
        chatter_pred = self._chatter_predictor.predict(features, load_pred, chatter_params)

        # ── 5. 위험 수준 분류 ─────────────────────────────────────────
        cs = chatter_pred.chatter_risk_score
        if not features.is_cutting:
            risk_level = ChatterRiskLevel.NONE
        elif cs < 0.25:
            risk_level = ChatterRiskLevel.LOW
        elif cs < 0.50:
            risk_level = ChatterRiskLevel.MEDIUM
        elif cs < 0.75:
            risk_level = ChatterRiskLevel.HIGH
        else:
            risk_level = ChatterRiskLevel.CRITICAL

        # ── 6. 경보 메시지 생성 ───────────────────────────────────────
        load_change = abs(load_pred.spindle_load_pct - self._prev_load)
        warning_messages = self._build_segment_warnings(
            ae_ratio=features.radial_ratio,
            ap=features.axial_depth_ap,
            diameter=diameter,
            spindle_load_pct=load_pred.spindle_load_pct,
            chatter_score=cs,
            is_plunge=features.is_plunge,
            is_ramp=features.is_ramp,
            load_change=load_change,
            vibration_x_um=chatter_pred.vibration_x_um,
            vibration_y_um=chatter_pred.vibration_y_um,
            vibration_z_um=chatter_pred.vibration_z_um,
            resultant_vibration_um=chatter_pred.resultant_vibration_um,
            stability_margin=chatter_pred.stability_margin,
        )

        # ── 7. 결과 조립 ──────────────────────────────────────────────
        risk_factors = dict(chatter_pred.risk_factors)
        risk_factors.update({
            "가공상태": machining_state,
            "접촉비율": round(contact_ratio, 3),
            "절삭력_Ft_N": round(load_pred.cutting_force_ft, 2),
            "절삭력_Fr_N": round(load_pred.cutting_force_fr, 2),
            "절삭력_Fa_N": round(load_pred.cutting_force_fa, 2),
            "force_x_n": round(load_pred.force_x, 2),
            "force_y_n": round(load_pred.force_y, 2),
            "force_z_n": round(load_pred.force_z, 2),
            "토크_Nm": round(load_pred.torque_nm, 3),
            "전력_W": round(load_pred.power_w, 1),
            "기저부하_pct": round(load_pred.baseline_load_pct, 1),
            "축이송부하_pct": round(load_pred.axis_motion_load_pct, 1),
            "절삭부하_pct": round(load_pred.cutting_load_pct, 1),
            "스핀들부하_pct": round(load_pred.spindle_load_pct, 1),
            "MRR_mm3min": round(features.mrr_mm3_per_min, 0),
        })

        return SegmentMachiningResult(
            segment_id=seg.segment_id,
            spindle_speed=features.spindle_rpm,
            feedrate=features.feedrate,
            tool_diameter=diameter,
            flute_count=features.flute_count,
            cutting_speed=features.cutting_speed_vc,
            feed_per_tooth=features.feed_per_tooth_fz,
            axial_depth_ap=features.axial_depth_ap,
            radial_depth_ae=features.radial_depth_ae,
            radial_ratio=features.radial_ratio,
            engagement_ratio=features.radial_ratio * min(
                1.0, features.axial_depth_ap / max(tool.flute_length, diameter)
            ),
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
            chatter_risk_score=chatter_pred.chatter_risk_score,
            chatter_risk_level=risk_level,
            direction_change_angle=features.direction_change_deg,
            is_plunge=features.is_plunge,
            is_ramp=features.is_ramp,
            is_cutting=features.is_cutting,
            machining_state=machining_state,
            contact_ratio=contact_ratio,
            baseline_load_pct=load_pred.baseline_load_pct,
            axis_motion_load_pct=load_pred.axis_motion_load_pct,
            cutting_load_pct=load_pred.cutting_load_pct,
            risk_factors=risk_factors,
            warning_messages=warning_messages,
        )

    def _build_segment_warnings(
        self,
        ae_ratio: float,
        ap: float,
        diameter: float,
        spindle_load_pct: float,
        chatter_score: float,
        is_plunge: bool,
        is_ramp: bool,
        load_change: float,
        vibration_x_um: float,
        vibration_y_um: float,
        vibration_z_um: float,
        resultant_vibration_um: float,
        stability_margin: float,
    ) -> List[str]:
        """사용자에게 보여줄 세그먼트 경보 메시지를 구성합니다."""
        warnings: List[str] = []

        if ae_ratio >= 0.85:
            warnings.append("풀폭 절삭에 가까운 맞물림입니다.")
        elif ae_ratio >= self.config.aggressive_ae_ratio:
            warnings.append("반경방향 맞물림이 커서 절삭 부하가 증가합니다.")

        ap_ratio = ap / diameter if diameter > 0 else 0.0
        if ap_ratio >= self.config.aggressive_ap_ratio:
            warnings.append("축방향 절입이 커서 절삭력이 증가합니다.")

        if is_plunge and ap >= max(self.config.default_ap_mm * 1.2, 2.0):
            warnings.append("깊은 플런지 진입으로 불안정 가능성이 있습니다.")
        elif is_ramp and ap >= max(self.config.default_ap_mm, 1.0):
            warnings.append("램프 진입 구간으로 절삭 부하가 증가합니다.")

        if spindle_load_pct >= self.config.high_load_threshold_pct:
            warnings.append(f"스핀들 부하가 높습니다 ({spindle_load_pct:.1f}%).")

        if load_change >= 18.0:
            warnings.append("블록 간 부하 변동이 큽니다.")

        if stability_margin < 1.0:
            warnings.append(
                f"안정성 마진 SM={stability_margin:.2f} < 1: 채터 불안정 구간입니다."
            )
        elif stability_margin < 1.5:
            warnings.append(
                f"안정성 마진 SM={stability_margin:.2f}: 안정 경계에 가깝습니다."
            )
        elif chatter_score >= self.config.unstable_chatter_threshold:
            warnings.append("채터/불안정 절삭 위험이 높습니다.")

        if vibration_x_um >= self.config.xy_vibration_warning_um:
            warnings.append("X축 예상 진동이 커서 측면 품질 저하 가능성이 있습니다.")
        if vibration_y_um >= self.config.xy_vibration_warning_um:
            warnings.append("Y축 예상 진동이 커서 측면 품질 저하 가능성이 있습니다.")
        if vibration_z_um >= self.config.z_vibration_warning_um:
            warnings.append("Z축 예상 진동이 커서 바닥면/깊이 품질 저하 가능성이 있습니다.")
        if resultant_vibration_um >= self.config.resultant_vibration_warning_um:
            warnings.append(
                "합성 진동이 높습니다. AE/AP 또는 이송 조건 완화를 권장합니다."
            )

        return warnings

    def _apply_segment_to_stock(
        self,
        stock_model: StockModel,
        seg: MotionSegment,
        tool: Tool,
        result: SegmentMachiningResult,
    ):
        """분석 중 얻은 세그먼트 절삭 결과를 임시 스톡에 반영합니다."""
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
