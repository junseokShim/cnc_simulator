"""
절삭 조건 추출 및 절입각 계산 모듈

NC 세그먼트로부터 절삭 조건(fz, Vc, ae, ap)과
Altintas 모델에 필요한 절입각(φ_entry, φ_exit)을 계산합니다.

[참고 문헌]
- Altintas, Y. (2000). Manufacturing Automation: Metal Cutting Mechanics,
  Machine Tool Vibrations, and CNC Design. Cambridge University Press.
  → 절입각 정의 및 맞물림 기하학 (Chapter 2)
- Altintas, Y., & Budak, E. (1995). Analytical Prediction of Stability Lobes
  in Milling. CIRP Annals, 44(1), 357-362.
  → φ_entry, φ_exit의 안정성 해석에서의 역할 (Eq. 4-6)

[절입각 정의]
- φ_entry (φ_st): 날이 소재에 진입하는 각도
- φ_exit  (φ_ex): 날이 소재에서 이탈하는 각도
- 업밀링:  φ_entry = arccos(1 - 2*ae/D),  φ_exit = π
- 다운밀링: φ_entry = 0,  φ_exit = π - arccos(1 - 2*ae/D)
- 슬로팅:  φ_entry = 0,  φ_exit = π (ae = D)
"""
from __future__ import annotations

import math
import numpy as np
from typing import Optional

from app.models.model_interfaces import CuttingFeatures
from app.models.tool import Tool
from app.models.toolpath import MotionSegment, MotionType
from app.utils.logger import get_logger

logger = get_logger("cutting_conditions")

# 업밀링/다운밀링 모드
UP_MILLING = "up_milling"
DOWN_MILLING = "down_milling"
SLOTTING = "slotting"

# 가공 상태 상수 (공중이송과 절삭을 명확히 분리)
STATE_RAPID = "RAPID"       # G0 급속 이동 (절삭 없음)
STATE_AIR_FEED = "AIR_FEED" # G1 공중 이송 (소재 비접촉, 스핀들은 회전)
STATE_PLUNGE = "PLUNGE"     # Z방향 플런지 (소재 하강 진입)
STATE_CUTTING = "CUTTING"   # 정상 측면 절삭 (소재 접촉)
STATE_EXIT = "EXIT"         # 절삭 이탈 구간


def compute_engagement_angles(
    ae: float,
    D: float,
    mode: str = UP_MILLING,
) -> tuple[float, float]:
    """
    반경방향 맞물림(ae)과 공구 직경(D)으로 절입각을 계산합니다.

    Altintas (2000) Manufacturing Automation, Chapter 2, Eq. 2.5-2.6

    업밀링:
        φ_entry = arccos(1 - 2*ae/D)    [rad]
        φ_exit  = π                       [rad]

    다운밀링:
        φ_entry = 0                       [rad]
        φ_exit  = arccos(-(1 - 2*ae/D)) = π - arccos(1 - 2*ae/D)  [rad]

    슬로팅 (ae ≥ D):
        φ_entry = 0
        φ_exit  = π

    Args:
        ae: 반경방향 맞물림 (mm), ae ≤ D
        D:  공구 직경 (mm)
        mode: UP_MILLING, DOWN_MILLING, SLOTTING

    Returns:
        (phi_entry_rad, phi_exit_rad): 절입각/이탈각 (라디안)
    """
    if D <= 0:
        return 0.0, math.pi

    ae_ratio = float(np.clip(ae / D, 0.0, 1.0))

    if ae_ratio >= 1.0 or mode == SLOTTING:
        # 슬로팅: 전체 원 절반
        return 0.0, math.pi

    # cos(φ_entry) for up-milling, validated to [-1, 1]
    cos_phi = float(np.clip(1.0 - 2.0 * ae_ratio, -1.0, 1.0))
    angle = math.acos(cos_phi)  # 0 ~ π

    if mode == DOWN_MILLING:
        return 0.0, (math.pi - angle)
    else:  # UP_MILLING (default)
        return angle, math.pi


def compute_directional_coefficients(
    phi_st: float,
    phi_ex: float,
    Krc: float,
) -> tuple[float, float, float, float]:
    """
    방향 계수(directional coefficients)를 계산합니다.

    Altintas & Budak (1995) Eq. 4-6, Altintas (2000) Eq. 2.23-2.26:

    X방향:
        α_xx = 0.5 * [-cos(2φ) - 2*Krc*φ + Krc*sin(2φ)] from φ_st to φ_ex
        α_xy = 0.5 * [-sin(2φ) + 2*φ - Krc*cos(2φ)]     from φ_st to φ_ex

    Y방향:
        α_yx = 0.5 * [sin(2φ) - 2*φ - Krc*cos(2φ)]      from φ_st to φ_ex
        α_yy = 0.5 * [-cos(2φ) + 2*Krc*φ + Krc*sin(2φ)] from φ_st to φ_ex

    Args:
        phi_st: 절입각 (rad)
        phi_ex: 이탈각 (rad)
        Krc:    반경/접선 절삭력 비율 Krc = Kr / Kt

    Returns:
        (a_xx, a_xy, a_yx, a_yy): 방향 계수
    """
    def eval_at(phi: float):
        c2 = math.cos(2 * phi)
        s2 = math.sin(2 * phi)
        # X방향
        xx = -c2 - 2 * Krc * phi + Krc * s2
        xy = -s2 + 2 * phi - Krc * c2
        # Y방향
        yx = s2 - 2 * phi - Krc * c2
        yy = -c2 + 2 * Krc * phi + Krc * s2
        return xx, xy, yx, yy

    ex = eval_at(phi_ex)
    st = eval_at(phi_st)

    a_xx = 0.5 * (ex[0] - st[0])
    a_xy = 0.5 * (ex[1] - st[1])
    a_yx = 0.5 * (ex[2] - st[2])
    a_yy = 0.5 * (ex[3] - st[3])

    return a_xx, a_xy, a_yx, a_yy


class CuttingConditionExtractor:
    """
    NC 세그먼트로부터 절삭 조건을 추출하는 클래스

    파싱된 MotionSegment 정보와 공구 정의를 조합하여
    수치 모델에 필요한 CuttingFeatures 인스턴스를 생성합니다.

    [ap 추정 전략]
    1. 플런지(Z 하강): |Δz|를 ap로 사용
    2. 수평 절삭: 직전 플런지 깊이를 ap로 유지
    3. 경사 절입: |Δz| * 보정 계수 사용
    4. 설정 기본값: 위 모두 해당 없을 때

    [ae 추정 전략]
    현재: 공구 직경 × ae_ratio (설정값)
    향후: Z-맵 기반 실제 접촉폭 계산으로 교체 가능
    """

    def __init__(
        self,
        default_ae_ratio: float = 0.5,
        default_ap_mm: float = 2.0,
        default_flute_count: int = 4,
        milling_mode: str = UP_MILLING,
    ):
        self.default_ae_ratio = default_ae_ratio
        self.default_ap_mm = default_ap_mm
        self.default_flute_count = default_flute_count
        self.milling_mode = milling_mode

        # 상태 (세그먼트 간 유지)
        self._last_ap: float = default_ap_mm
        self._prev_dir: Optional[np.ndarray] = None

    def reset(self):
        """시퀀스 처리 전 상태 초기화"""
        self._last_ap = self.default_ap_mm
        self._prev_dir = None

    def extract(
        self,
        seg: MotionSegment,
        tool: Optional[Tool],
    ) -> CuttingFeatures:
        """
        단일 MotionSegment에서 CuttingFeatures를 추출합니다.

        Args:
            seg:  MotionSegment 인스턴스
            tool: 현재 공구 (없으면 기본값 사용)

        Returns:
            CuttingFeatures
        """
        is_cutting = seg.is_cutting_move

        # ---- 공구 파라미터 ----
        if tool is not None:
            D = tool.diameter
            z = tool.flute_count
        else:
            D = 10.0
            z = self.default_flute_count

        n = seg.spindle_speed   # RPM
        F = seg.feedrate        # mm/min

        # ---- 기본 절삭 조건 ----
        Vc = math.pi * D * n / 1000.0 if n > 0 else 0.0
        fz = F / (n * z) if (n > 0 and z > 0 and is_cutting) else 0.0

        # ---- ap 추정 ----
        delta_xyz = seg.end_pos - seg.start_pos
        delta_z = float(delta_xyz[2])
        xy_dist = float(np.linalg.norm(delta_xyz[:2]))

        is_plunge = (delta_z < -0.01) and is_cutting
        is_ramp = (abs(delta_z) > 0.01 and xy_dist > 0.01 and is_cutting)

        if is_plunge:
            ap = abs(delta_z)
            self._last_ap = ap
        elif is_ramp:
            ap = abs(delta_z) * 0.65  # 경사 절입 보정
            self._last_ap = max(ap, self.default_ap_mm)
        elif is_cutting:
            ap = self._last_ap
        else:
            ap = 0.0

        # ---- ae 추정 ----
        # 주의: 이 ae는 스톡 모델 기반 보정 전의 초기 추정값입니다.
        # machining_model.py에서 stock 기반으로 재보정합니다.
        ae = D * self.default_ae_ratio if is_cutting else 0.0

        # ---- 절입각 계산 (Altintas 2000, Ch.2) ----
        if is_cutting and ae > 0 and ap > 0:
            phi_st, phi_ex = compute_engagement_angles(ae, D, self.milling_mode)
        else:
            phi_st, phi_ex = 0.0, 0.0  # 비절삭: 맞물림 없음

        eng_arc_deg = math.degrees(phi_ex - phi_st)

        # ---- 초기 가공 상태 분류 (스톡 접촉 여부는 machining_model.py에서 보정) ----
        if seg.motion_type.name == "RAPID":
            machining_state = STATE_RAPID
        elif is_plunge:
            machining_state = STATE_PLUNGE
        elif is_cutting:
            # 아직 스톡 접촉 여부 불명 → 일단 AIR_FEED로 설정
            # machining_model.py에서 stock 기반으로 CUTTING으로 승격됩니다.
            machining_state = STATE_AIR_FEED
        else:
            machining_state = STATE_AIR_FEED

        # ---- 방향 변화각 계산 ----
        seg_vec = delta_xyz
        seg_len = float(np.linalg.norm(seg_vec))
        dir_change_deg = 0.0

        if seg_len > 0.001:
            cur_dir = seg_vec / seg_len
            if self._prev_dir is not None:
                cos_a = float(np.clip(np.dot(cur_dir, self._prev_dir), -1.0, 1.0))
                dir_change_deg = math.degrees(math.acos(cos_a))
            self._prev_dir = cur_dir
        else:
            self._prev_dir = None

        # ---- MRR ----
        MRR = ae * ap * F if is_cutting else 0.0

        feat = CuttingFeatures(
            cutting_speed_vc=Vc,
            feed_per_tooth_fz=fz,
            axial_depth_ap=ap,
            radial_depth_ae=ae,
            radial_ratio=ae / D if D > 0 else 0.0,
            tool_diameter=D,
            flute_count=z,
            spindle_rpm=n,
            feedrate=F,
            phi_entry_rad=phi_st,
            phi_exit_rad=phi_ex,
            phi_entry_deg=math.degrees(phi_st),
            phi_exit_deg=math.degrees(phi_ex),
            engagement_arc_deg=eng_arc_deg,
            direction_change_deg=dir_change_deg,
            is_plunge=is_plunge,
            is_ramp=is_ramp,
            is_cutting=is_cutting,
            mrr_mm3_per_min=MRR,
            machining_state=machining_state,
            contact_ratio=0.0,
        )
        return feat
