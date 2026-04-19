"""
공작기계 프로파일(Machine Profile) 모듈

각 공작기계의 특성 파라미터를 정의하고 관리합니다.
DN Solutions T4000이 기본 프로파일로 사용됩니다.

[아키텍처 설계 원칙]
- 기계별 특성값은 YAML 파일(configs/machines/)에서 로드합니다.
- 모든 수학 모델(스핀들 부하, 채터)은 MachineProfile 객체를 통해 파라미터를 받습니다.
- T4000 특성값이 모델 코드 안에 하드코딩되지 않습니다.

[새 기계 추가 방법]
1. configs/machines/{machine_id}.yaml 파일 생성
2. MachineProfileRegistry.load_from_directory("configs/machines") 호출
3. 시뮬레이션 파이프라인은 변경 불필요

[데이터 기반 모델 교체 시 참조 파일]
- app/models/cutting_force_model.py  → 스핀들 부하 모델
- app/models/chatter_model.py        → 채터 위험도 모델
- app/models/model_interfaces.py     → 인터페이스 정의
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class MachineProfile:
    """
    공작기계 특성 파라미터 컨테이너

    스핀들 부하 및 채터 위험도 모델에 사용되는 기계 특성값을 담습니다.
    모든 파라미터는 configs/machines/{id}.yaml 에서 로드 가능합니다.

    [파라미터 그룹]
    1. 기본 정보: 기계명, 제조사, 모델 ID
    2. 스핀들: 최대 RPM, 정격 출력, 최대 토크, 테이퍼 규격
    3. 이송 축: X/Y/Z 이동량, 급속 이송 속도
    4. 동특성: 강성, 감쇠비, 고유주파수, 채터 민감도
    5. 부하 분해: 기저 전력비, 축 이송 전력비, 기계 효율
    """

    # ---- 기본 정보 ----
    name: str = "Generic Machine"
    manufacturer: str = "Generic"
    model_id: str = "generic"
    description: str = ""

    # ---- 스핀들 특성 ----
    spindle_max_rpm: float = 8000.0        # 최대 스핀들 RPM
    spindle_rated_power_w: float = 7500.0  # 정격 연속 출력 (W)
    spindle_peak_power_w: float = 11000.0  # 최대 순간 출력 (W)
    spindle_max_torque_nm: float = 50.0    # 최대 토크 (N·m)
    spindle_taper: str = "BT40"            # 스핀들 테이퍼 규격

    # ---- 이송 축 특성 ----
    x_travel_mm: float = 500.0             # X축 이동량 (mm)
    y_travel_mm: float = 400.0             # Y축 이동량 (mm)
    z_travel_mm: float = 350.0             # Z축 이동량 (mm)
    rapid_traverse_mm_min: float = 36000.0 # 최대 급속 이송 속도 (mm/min)

    # ---- 기계 강성 / 동특성 파라미터 ----
    # 이 값들이 스핀들 부하 및 채터 위험도 모델에 직접 영향을 줍니다.
    # FRF 측정값이 있으면 아래 값을 실측치로 교체하세요.
    machine_stiffness_factor: float = 1.0  # 기계 강성 배율 (기준=1.0)
    damping_ratio: float = 0.03            # 구조 감쇠비 ζ
    tool_tip_stiffness_n_per_um: float = 20.0  # 공구 끝단 강성 (N/μm)
    natural_frequency_hz: float = 800.0    # 공구-스핀들 고유주파수 (Hz)
    chatter_sensitivity: float = 1.0       # 채터 민감도 계수

    # ---- 스핀들 부하 분해 파라미터 ----
    # 스핀들 무부하 기저 전력비: 스핀들이 돌기만 해도 소비되는 전력 비율
    # (베어링 마찰, 냉각팬, 윤활 등 포함)
    baseline_power_ratio: float = 0.07     # 7% of rated (무부하 회전 시)

    # 축 이송 소비 전력비: 최대 급속 이송 시 추가 소비 전력 비율
    axis_motion_power_ratio: float = 0.04  # 4% of rated (최대 급속 시)

    # 기계 전달 효율: 스핀들 출력 → 절삭 전력 변환 효율
    machine_efficiency: float = 0.85       # 85%

    # ---- 공구 홀더 강성 프록시 ----
    # >1: 더 강성 (짧은 돌출/고강성 홀더)
    # <1: 더 유연 (긴 돌출/열악한 홀더)
    tool_holder_rigidity: float = 1.0

    # ---- 안정성 로브선도 보정 계수 ----
    # 기계 구조 특성에 의한 임계 절입 깊이(ap_lim) 보정
    # >1.0: 실제 ap_lim이 이론값보다 큼 (더 안정적인 기계)
    stability_lobe_correction: float = 1.0

    @classmethod
    def from_dict(cls, d: dict) -> MachineProfile:
        """딕셔너리에서 MachineProfile을 생성합니다."""
        valid_keys = set(cls.__dataclass_fields__.keys())
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def from_yaml(cls, yaml_path: str) -> MachineProfile:
        """YAML 파일에서 MachineProfile을 로드합니다."""
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML이 필요합니다: pip install pyyaml")
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        # YAML 루트가 machine_profile 키를 가질 수 있음
        if "machine_profile" in data:
            data = data["machine_profile"]
        return cls.from_dict(data)

    def to_params_dict(self) -> dict:
        """
        기계론적 모델(절삭력/채터)에 전달할 파라미터 딕셔너리를 반환합니다.

        MachiningModel._load_params 및 _chatter_params 에 병합됩니다.
        """
        return {
            # 스핀들 출력 관련
            "spindle_rated_power_w": self.spindle_rated_power_w,
            "spindle_max_torque_nm": self.spindle_max_torque_nm,
            "machine_efficiency": self.machine_efficiency,
            # 강성/동특성
            "machine_stiffness": self.machine_stiffness_factor,
            "k_n_per_um": self.tool_tip_stiffness_n_per_um,
            "zeta": self.damping_ratio,
            "f_natural_hz": self.natural_frequency_hz,
            "chatter_sensitivity": self.chatter_sensitivity,
            # 공구 홀더 계수 (강성이 클수록 overhang_factor 작음)
            "tool_overhang_factor": 1.0 / max(self.tool_holder_rigidity, 0.1),
            # 스핀들 부하 분해
            "baseline_power_ratio": self.baseline_power_ratio,
            "axis_motion_power_ratio": self.axis_motion_power_ratio,
            "rapid_traverse_mm_min": self.rapid_traverse_mm_min,
            # 안정성 보정
            "stability_lobe_correction": self.stability_lobe_correction,
        }


class MachineProfileRegistry:
    """
    기계 프로파일 레지스트리

    사용 가능한 기계 프로파일을 관리합니다.
    DN Solutions T4000이 기본값으로 등록됩니다.

    [사용 방법]
    - MachineProfileRegistry.get_default() → T4000 프로파일
    - MachineProfileRegistry.get("t4000") → T4000 프로파일
    - MachineProfileRegistry.load_from_directory("configs/machines") → YAML 일괄 로드
    """

    _profiles: Dict[str, MachineProfile] = {}
    _default_id: str = "t4000"
    _initialized: bool = False

    @classmethod
    def _ensure_initialized(cls) -> None:
        """레지스트리 최초 사용 시 T4000을 자동 등록합니다."""
        if not cls._initialized:
            cls._initialized = True
            t4000 = _load_t4000()
            cls._profiles[t4000.model_id] = t4000

    @classmethod
    def register(cls, profile: MachineProfile) -> None:
        """프로파일을 레지스트리에 등록합니다."""
        cls._profiles[profile.model_id] = profile

    @classmethod
    def get(cls, model_id: str) -> Optional[MachineProfile]:
        """등록된 프로파일을 반환합니다. 없으면 None."""
        cls._ensure_initialized()
        return cls._profiles.get(model_id)

    @classmethod
    def get_default(cls) -> MachineProfile:
        """기본 프로파일(DN Solutions T4000)을 반환합니다."""
        cls._ensure_initialized()
        profile = cls._profiles.get(cls._default_id)
        if profile is None:
            profile = _t4000_defaults()
            cls._profiles[cls._default_id] = profile
        return profile

    @classmethod
    def list_available(cls) -> list:
        """등록된 프로파일 ID 목록을 반환합니다."""
        cls._ensure_initialized()
        return list(cls._profiles.keys())

    @classmethod
    def load_from_directory(cls, config_dir: str) -> None:
        """
        디렉토리의 모든 YAML 파일에서 프로파일을 로드합니다.

        새 기계를 추가할 때 이 메서드를 호출하면 됩니다.

        Args:
            config_dir: 기계 프로파일 YAML 파일이 있는 디렉토리 경로
        """
        if not os.path.isdir(config_dir):
            return
        for fname in sorted(os.listdir(config_dir)):
            if not (fname.endswith(".yaml") or fname.endswith(".yml")):
                continue
            path = os.path.join(config_dir, fname)
            try:
                profile = MachineProfile.from_yaml(path)
                cls.register(profile)
            except Exception:
                pass  # 개별 파일 오류가 전체를 막지 않음


def _load_t4000() -> MachineProfile:
    """DN Solutions T4000 프로파일을 configs/machines/t4000.yaml에서 로드합니다."""
    # 이 파일의 위치: app/machines/machine_profile.py
    # configs/machines/t4000.yaml의 상대 경로: ../../configs/machines/t4000.yaml
    here = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.normpath(
        os.path.join(here, "..", "..", "configs", "machines", "t4000.yaml")
    )
    if os.path.exists(config_path):
        try:
            return MachineProfile.from_yaml(config_path)
        except Exception:
            pass
    return _t4000_defaults()


def _t4000_defaults() -> MachineProfile:
    """
    DN Solutions T4000 내장 기본값

    YAML 파일 없이도 동작하는 fallback입니다.
    YAML 파일이 있으면 그쪽이 우선합니다.
    """
    return MachineProfile(
        name="DN Solutions T4000",
        manufacturer="DN Solutions",
        model_id="t4000",
        description="DN Solutions T4000 수직 머시닝센터 (BT30, 12,000 RPM)",
        spindle_max_rpm=12000.0,
        spindle_rated_power_w=7500.0,
        spindle_peak_power_w=11000.0,
        spindle_max_torque_nm=50.0,
        spindle_taper="BT30",
        x_travel_mm=520.0,
        y_travel_mm=400.0,
        z_travel_mm=350.0,
        rapid_traverse_mm_min=56000.0,
        machine_stiffness_factor=1.05,
        damping_ratio=0.03,
        tool_tip_stiffness_n_per_um=22.0,
        natural_frequency_hz=900.0,
        chatter_sensitivity=0.95,
        baseline_power_ratio=0.07,
        axis_motion_power_ratio=0.04,
        machine_efficiency=0.85,
        tool_holder_rigidity=1.05,
        stability_lobe_correction=1.02,
    )
