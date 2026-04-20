"""
절삭 조건 추출 및 절입각 계산 모듈

NC 세그먼트로부터 절삭/급속 이송 상태를 구분하고,
부하/진동 모델이 사용할 피처를 생성합니다.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np

from app.models.model_interfaces import CuttingFeatures
from app.models.tool import Tool
from app.models.toolpath import MotionSegment, MotionType
from app.utils.logger import get_logger

logger = get_logger("cutting_conditions")

UP_MILLING = "up_milling"
DOWN_MILLING = "down_milling"
SLOTTING = "slotting"

STATE_RAPID = "RAPID"
STATE_AIR_FEED = "AIR_FEED"
STATE_PLUNGE = "PLUNGE"
STATE_ENTRY_CUT = "ENTRY_CUT"
STATE_STEADY_CUT = "STEADY_CUT"
STATE_EXIT_CUT = "EXIT_CUT"
STATE_CUTTING = STATE_STEADY_CUT


def compute_engagement_angles(
    ae: float,
    D: float,
    mode: str = UP_MILLING,
) -> tuple[float, float]:
    """반경 방향 맞물림과 공구 직경으로 절입각을 계산합니다."""

    if D <= 0.0:
        return 0.0, math.pi

    ae_ratio = float(np.clip(ae / D, 0.0, 1.0))
    if ae_ratio >= 1.0 or mode == SLOTTING:
        return 0.0, math.pi

    cos_phi = float(np.clip(1.0 - 2.0 * ae_ratio, -1.0, 1.0))
    angle = math.acos(cos_phi)

    if mode == DOWN_MILLING:
        return 0.0, (math.pi - angle)
    return angle, math.pi


def compute_directional_coefficients(
    phi_st: float,
    phi_ex: float,
    Krc: float,
) -> tuple[float, float, float, float]:
    """Altintas 식 기반 방향 계수를 계산합니다."""

    def eval_at(phi: float):
        c2 = math.cos(2.0 * phi)
        s2 = math.sin(2.0 * phi)
        xx = -c2 - 2.0 * Krc * phi + Krc * s2
        xy = -s2 + 2.0 * phi - Krc * c2
        yx = s2 - 2.0 * phi - Krc * c2
        yy = -c2 + 2.0 * Krc * phi + Krc * s2
        return xx, xy, yx, yy

    ex = eval_at(phi_ex)
    st = eval_at(phi_st)

    a_xx = 0.5 * (ex[0] - st[0])
    a_xy = 0.5 * (ex[1] - st[1])
    a_yx = 0.5 * (ex[2] - st[2])
    a_yy = 0.5 * (ex[3] - st[3])
    return a_xx, a_xy, a_yx, a_yy


class CuttingConditionExtractor:
    """세그먼트와 공구 정의로부터 모델 입력 피처를 생성합니다."""

    def __init__(
        self,
        default_ae_ratio: float = 0.5,
        default_ap_mm: float = 2.0,
        default_flute_count: int = 4,
        milling_mode: str = UP_MILLING,
        rapid_traverse_mm_min: float = 36000.0,
    ):
        self.default_ae_ratio = default_ae_ratio
        self.default_ap_mm = default_ap_mm
        self.default_flute_count = default_flute_count
        self.milling_mode = milling_mode
        self.rapid_traverse_mm_min = rapid_traverse_mm_min

        self._last_ap: float = default_ap_mm
        self._prev_dir: Optional[np.ndarray] = None
        self._prev_effective_feedrate: float = 0.0

    def reset(self):
        """직전 세그먼트 상태를 초기화합니다."""

        self._last_ap = self.default_ap_mm
        self._prev_dir = None
        self._prev_effective_feedrate = 0.0

    def extract(
        self,
        seg: MotionSegment,
        tool: Optional[Tool],
    ) -> CuttingFeatures:
        """단일 세그먼트에서 `CuttingFeatures`를 추출합니다."""

        is_rapid = seg.motion_type == MotionType.RAPID
        is_cutting_move = seg.is_cutting_move and not is_rapid

        if tool is not None:
            D = float(tool.diameter_mm)
            z = int(tool.flute_count)
            tool_category = tool.tool_category
            tool_type = tool.tool_type.value
            tool_overhang = tool.effective_overhang_mm
            tool_rigidity = tool.effective_rigidity_factor
            tool_cutting_factor = tool.get_force_distribution()["force_factor"]
            tool_force_distribution = tool.get_force_distribution()
            tool_engagement_factor = tool.get_engagement_factor()
            tool_chatter_factor = tool.get_chatter_sensitivity_factor()
            tool_rapid_shock_factor = tool.get_rapid_shock_factor()
            material_overrides = dict(tool.material_coefficient_overrides)
        else:
            D = 10.0
            z = self.default_flute_count
            tool_category = "EM"
            tool_type = "END_MILL"
            tool_overhang = D * 4.0
            tool_rigidity = 1.0
            tool_cutting_factor = 1.0
            tool_force_distribution = {
                "tangential_force_factor": 1.0,
                "radial_force_factor": 1.0,
                "axial_force_factor": 1.0,
            }
            tool_engagement_factor = 1.0
            tool_chatter_factor = 1.0
            tool_rapid_shock_factor = 1.0
            material_overrides = {}

        raw_feed = float(seg.feedrate)
        effective_feed = self.rapid_traverse_mm_min if is_rapid else max(raw_feed, 0.0)
        n = float(seg.spindle_speed)

        Vc = math.pi * D * n / 1000.0 if n > 0.0 else 0.0
        fz = effective_feed / (n * z) if (n > 0.0 and z > 0 and is_cutting_move) else 0.0

        delta_xyz = seg.end_pos - seg.start_pos
        motion_distance = float(np.linalg.norm(delta_xyz))
        xy_dist = float(np.linalg.norm(delta_xyz[:2]))
        delta_z = float(delta_xyz[2])

        axis_ratios = np.zeros(3, dtype=float)
        if motion_distance > 1e-9:
            axis_ratios = np.abs(delta_xyz) / motion_distance

        is_plunge = (delta_z < -0.01) and is_cutting_move and (xy_dist < max(D * 0.15, 0.5))
        is_ramp = (abs(delta_z) > 0.01) and (xy_dist > 0.01) and is_cutting_move

        if is_plunge:
            ap = abs(delta_z)
            self._last_ap = max(ap, self.default_ap_mm)
        elif is_ramp:
            ap = max(abs(delta_z) * 0.75, self.default_ap_mm * 0.6)
            self._last_ap = max(ap, self.default_ap_mm)
        elif is_cutting_move:
            ap = self._last_ap
        else:
            ap = 0.0

        if is_cutting_move:
            if tool is not None and tool.is_drill:
                ae_ratio = 0.95 if is_plunge else 0.35
            else:
                ae_ratio = self.default_ae_ratio * tool_engagement_factor
            ae = D * float(np.clip(ae_ratio, 0.05, 1.0))
        else:
            ae = 0.0

        if is_cutting_move and ae > 0.0 and ap > 0.0:
            if tool is not None and tool.is_drill and is_plunge:
                phi_st, phi_ex = 0.0, math.pi
            else:
                phi_st, phi_ex = compute_engagement_angles(ae, D, self.milling_mode)
        else:
            phi_st, phi_ex = 0.0, 0.0

        seg_len = motion_distance
        dir_change_deg = 0.0
        if seg_len > 0.001:
            cur_dir = delta_xyz / seg_len
            if self._prev_dir is not None:
                cos_a = float(np.clip(np.dot(cur_dir, self._prev_dir), -1.0, 1.0))
                dir_change_deg = math.degrees(math.acos(cos_a))
            self._prev_dir = cur_dir
        else:
            self._prev_dir = None

        speed_ratio = float(np.clip(effective_feed / max(self.rapid_traverse_mm_min, 1.0), 0.0, 1.0))
        speed_change_ratio = float(
            np.clip(
                abs(effective_feed - self._prev_effective_feedrate) / max(self.rapid_traverse_mm_min, 1.0),
                0.0,
                1.5,
            )
        )
        short_move_factor = 1.0 - min(1.0, motion_distance / max(D * 3.0, 12.0))
        acceleration_proxy = float(np.clip(speed_change_ratio * (0.45 + 0.55 * short_move_factor), 0.0, 1.0))
        corner_factor = math.sin(math.radians(min(dir_change_deg, 180.0)) * 0.5)
        jerk_proxy = float(np.clip(0.60 * acceleration_proxy + 0.40 * corner_factor * speed_ratio, 0.0, 1.0))
        self._prev_effective_feedrate = effective_feed

        if is_rapid:
            machining_state = STATE_RAPID
        elif not is_cutting_move:
            machining_state = STATE_AIR_FEED
        elif is_plunge:
            machining_state = STATE_PLUNGE
        else:
            machining_state = STATE_ENTRY_CUT

        MRR = ae * ap * effective_feed if is_cutting_move else 0.0

        return CuttingFeatures(
            cutting_speed_vc=Vc,
            feed_per_tooth_fz=fz,
            axial_depth_ap=ap,
            radial_depth_ae=ae,
            radial_ratio=ae / D if D > 0.0 else 0.0,
            tool_diameter=D,
            flute_count=z,
            spindle_rpm=n,
            feedrate=raw_feed,
            effective_feedrate=effective_feed,
            motion_distance_mm=motion_distance,
            speed_ratio=speed_ratio,
            speed_change_ratio=speed_change_ratio,
            acceleration_proxy=acceleration_proxy,
            jerk_proxy=jerk_proxy,
            axis_ratio_x=float(axis_ratios[0]),
            axis_ratio_y=float(axis_ratios[1]),
            axis_ratio_z=float(axis_ratios[2]),
            phi_entry_rad=phi_st,
            phi_exit_rad=phi_ex,
            phi_entry_deg=math.degrees(phi_st),
            phi_exit_deg=math.degrees(phi_ex),
            engagement_arc_deg=math.degrees(phi_ex - phi_st),
            direction_change_deg=dir_change_deg,
            is_plunge=is_plunge,
            is_ramp=is_ramp,
            is_cutting=is_cutting_move,
            mrr_mm3_per_min=MRR,
            machining_state=machining_state,
            contact_ratio=0.0,
            tool_type=tool_type,
            tool_category=tool_category,
            tool_overhang_mm=tool_overhang,
            tool_rigidity_factor=tool_rigidity,
            tool_cutting_coefficient_factor=tool_cutting_factor,
            tool_engagement_factor=tool_engagement_factor,
            tool_chatter_factor=tool_chatter_factor,
            tool_tangential_force_factor=float(tool_force_distribution["tangential_force_factor"]),
            tool_radial_force_factor=float(tool_force_distribution["radial_force_factor"]),
            tool_axial_force_factor=float(tool_force_distribution["axial_force_factor"]),
            tool_rapid_shock_factor=tool_rapid_shock_factor,
            tool_material_overrides=material_overrides,
        )
