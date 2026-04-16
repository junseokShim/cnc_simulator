"""
검증 체커(Verification Checker) 모듈
모든 검증 규칙을 실행하고 결과를 집계합니다.
"""
from __future__ import annotations
from typing import List, Dict, Optional
import numpy as np

from app.models.toolpath import Toolpath
from app.models.machine import MachineDef
from app.models.tool import Tool
from app.geometry.stock_model import StockModel
from app.verification.rules import (
    VerificationWarning,
    check_rapid_into_stock,
    check_out_of_bounds,
    check_missing_tool,
    check_spindle_off_cutting,
    check_large_z_plunge,
    check_zero_feedrate,
    check_arc_radius,
    check_excessive_feedrate,
    check_excessive_spindle_speed,
)
from app.utils.logger import get_logger

logger = get_logger("verification_checker")


class VerificationChecker:
    """
    NC 코드 검증 체커 클래스

    여러 검증 규칙을 일괄 실행하고 결과를 수집합니다.
    발견된 경고와 오류를 라인 번호 순서로 정렬하여 반환합니다.
    """

    def __init__(self):
        # 각 규칙의 활성화 여부 설정
        self.enabled_rules = {
            'rapid_into_stock': True,
            'out_of_bounds': True,
            'missing_tool': True,
            'spindle_off': True,
            'large_z_plunge': True,
            'zero_feedrate': True,
            'arc_radius': True,
            'excessive_feedrate': True,
            'excessive_spindle': True,
        }

        # Z 플런지 한계값 (mm)
        self.z_plunge_threshold = 10.0

    def configure(self, options: dict):
        """
        검증 옵션을 설정합니다.

        Args:
            options: 검증 옵션 딕셔너리
        """
        if 'check_rapid_into_stock' in options:
            self.enabled_rules['rapid_into_stock'] = bool(options['check_rapid_into_stock'])
        if 'check_out_of_bounds' in options:
            self.enabled_rules['out_of_bounds'] = bool(options['check_out_of_bounds'])
        if 'check_missing_tool' in options:
            self.enabled_rules['missing_tool'] = bool(options['check_missing_tool'])
        if 'check_spindle_off' in options:
            self.enabled_rules['spindle_off'] = bool(options['check_spindle_off'])
        if 'z_plunge_threshold' in options:
            self.z_plunge_threshold = float(options['z_plunge_threshold'])

    def run_all_checks(self, toolpath: Toolpath, stock: StockModel,
                       machine: MachineDef,
                       tools: Dict[int, Tool]) -> List[VerificationWarning]:
        """
        모든 활성화된 검증 규칙을 실행하고 결과를 반환합니다.

        실행 순서:
        1. 급속 이동 충돌 검사
        2. 이동 범위 초과 검사
        3. 미정의 공구 참조 검사
        4. 주축 정지 절삭 검사
        5. 대형 Z 플런지 검사
        6. 이송 속도 0 검사
        7. 원호 반경 검사
        8. 최대 이송 속도 초과 검사
        9. 최대 주축 회전수 초과 검사

        Args:
            toolpath: 검증할 공구경로
            stock: 소재 모델
            machine: 머신 사양
            tools: 공구 딕셔너리

        Returns:
            라인 번호 순으로 정렬된 검증 경고 목록
        """
        if not toolpath or not toolpath.segments:
            logger.warning("검증할 세그먼트가 없습니다")
            return []

        all_warnings: List[VerificationWarning] = []
        segments = toolpath.segments

        logger.info(f"NC 코드 검증 시작: {len(segments)}개 세그먼트")

        # 1. 급속 이동 충돌 검사
        if self.enabled_rules['rapid_into_stock'] and stock is not None:
            try:
                warnings = check_rapid_into_stock(segments, stock)
                all_warnings.extend(warnings)
                if warnings:
                    logger.debug(f"급속 이동 충돌: {len(warnings)}개 발견")
            except Exception as e:
                logger.error(f"급속 충돌 검사 실패: {e}")

        # 2. 이동 범위 초과 검사
        if self.enabled_rules['out_of_bounds'] and machine is not None:
            try:
                warnings = check_out_of_bounds(segments, machine)
                all_warnings.extend(warnings)
                if warnings:
                    logger.debug(f"범위 초과: {len(warnings)}개 발견")
            except Exception as e:
                logger.error(f"범위 검사 실패: {e}")

        # 3. 미정의 공구 참조 검사
        if self.enabled_rules['missing_tool']:
            try:
                warnings = check_missing_tool(segments, tools)
                all_warnings.extend(warnings)
                if warnings:
                    logger.debug(f"미정의 공구: {len(warnings)}개 발견")
            except Exception as e:
                logger.error(f"공구 검사 실패: {e}")

        # 4. 주축 정지 절삭 검사
        if self.enabled_rules['spindle_off']:
            try:
                warnings = check_spindle_off_cutting(segments)
                all_warnings.extend(warnings)
                if warnings:
                    logger.debug(f"주축 정지 절삭: {len(warnings)}개 발견")
            except Exception as e:
                logger.error(f"주축 검사 실패: {e}")

        # 5. 대형 Z 플런지 검사
        if self.enabled_rules['large_z_plunge']:
            try:
                warnings = check_large_z_plunge(segments, self.z_plunge_threshold)
                all_warnings.extend(warnings)
                if warnings:
                    logger.debug(f"대형 Z 플런지: {len(warnings)}개 발견")
            except Exception as e:
                logger.error(f"Z 플런지 검사 실패: {e}")

        # 6. 이송 속도 0 검사
        if self.enabled_rules['zero_feedrate']:
            try:
                warnings = check_zero_feedrate(segments)
                all_warnings.extend(warnings)
                if warnings:
                    logger.debug(f"이송 속도 0: {len(warnings)}개 발견")
            except Exception as e:
                logger.error(f"이송 속도 검사 실패: {e}")

        # 7. 원호 반경 검사
        if self.enabled_rules['arc_radius']:
            try:
                warnings = check_arc_radius(segments)
                all_warnings.extend(warnings)
                if warnings:
                    logger.debug(f"원호 반경 이상: {len(warnings)}개 발견")
            except Exception as e:
                logger.error(f"원호 검사 실패: {e}")

        # 8. 최대 이송 속도 초과 검사
        if self.enabled_rules['excessive_feedrate'] and machine is not None:
            try:
                warnings = check_excessive_feedrate(segments, machine)
                all_warnings.extend(warnings)
                if warnings:
                    logger.debug(f"이송 속도 초과: {len(warnings)}개 발견")
            except Exception as e:
                logger.error(f"이송 속도 한계 검사 실패: {e}")

        # 9. 최대 주축 회전수 초과 검사
        if self.enabled_rules['excessive_spindle'] and machine is not None:
            try:
                warnings = check_excessive_spindle_speed(segments, machine)
                all_warnings.extend(warnings)
                if warnings:
                    logger.debug(f"주축 회전수 초과: {len(warnings)}개 발견")
            except Exception as e:
                logger.error(f"주축 회전수 검사 실패: {e}")

        # 라인 번호 순으로 정렬, 같은 라인이면 심각도 순
        severity_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
        all_warnings.sort(
            key=lambda w: (w.line_number, severity_order.get(w.severity, 3))
        )

        # 검증 결과 요약 로그
        error_count = sum(1 for w in all_warnings if w.severity == "ERROR")
        warning_count = sum(1 for w in all_warnings if w.severity == "WARNING")
        info_count = sum(1 for w in all_warnings if w.severity == "INFO")

        logger.info(
            f"검증 완료: 오류 {error_count}개, 경고 {warning_count}개, "
            f"정보 {info_count}개 (총 {len(all_warnings)}개)"
        )

        return all_warnings

    def get_warnings_for_segment(self, warnings: List[VerificationWarning],
                                  segment_id: int) -> List[VerificationWarning]:
        """
        특정 세그먼트와 관련된 경고만 필터링합니다.

        Args:
            warnings: 전체 경고 목록
            segment_id: 조회할 세그먼트 ID

        Returns:
            해당 세그먼트의 경고 목록
        """
        return [w for w in warnings if w.segment_id == segment_id]
