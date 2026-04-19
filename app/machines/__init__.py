"""
공작기계 프로파일 패키지

DN Solutions T4000을 기본 프로파일로 제공하며,
configs/machines/ 디렉토리에 YAML을 추가하여 다른 기계를 등록할 수 있습니다.
"""
from app.machines.machine_profile import MachineProfile, MachineProfileRegistry

__all__ = ["MachineProfile", "MachineProfileRegistry"]
