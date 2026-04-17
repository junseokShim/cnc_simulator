"""
보고서 생성 서비스 모듈

NC 코드 검증 결과와 가공 해석 결과를 텍스트 리포트로 생성합니다.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional

from app.models.machine import MachineDef
from app.models.machining_result import ChatterRiskLevel, MachiningAnalysis
from app.models.project import ProjectConfig
from app.models.tool import Tool
from app.models.toolpath import MotionType, Toolpath
from app.simulation.time_estimator import TimeEstimator
from app.utils.logger import get_logger
from app.verification.rules import VerificationWarning

logger = get_logger("report_service")


class ReportService:
    """검증/가공 해석 리포트를 생성하는 서비스"""

    def __init__(self):
        self._time_estimator = TimeEstimator()

    def generate_report(
        self,
        toolpath: Toolpath,
        warnings: List[VerificationWarning],
        machine: MachineDef,
        tools: Dict[int, Tool],
        project_config: Optional[ProjectConfig] = None,
        machining_analysis: Optional[MachiningAnalysis] = None,
    ) -> str:
        """종합 검증 보고서를 생성합니다."""

        lines: List[str] = []
        sep_major = "=" * 78
        sep_minor = "-" * 78

        lines.append(sep_major)
        lines.append("  CNC NC 코드 시뮬레이션 / 검증 보고서")
        lines.append(sep_major)
        lines.append(f"  생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        if project_config is not None:
            lines.append(f"  프로젝트: {project_config.project_name}")
            if project_config.nc_file_path:
                lines.append(f"  NC 파일: {os.path.basename(project_config.nc_file_path)}")
        elif toolpath.source_file:
            lines.append(f"  NC 파일: {os.path.basename(toolpath.source_file)}")

        lines.append(f"  머신: {machine.name}")
        lines.append("")

        lines.append(sep_minor)
        lines.append("  [ 프로젝트 / 소재 정보 ]")
        lines.append(sep_minor)
        if project_config is not None:
            stock_size = project_config.get_stock_size()
            lines.append(f"  소재 원점 기준: {project_config.stock_origin_mode}")
            lines.append(
                f"  소재 원점: X{project_config.stock_origin[0]:.3f} "
                f"Y{project_config.stock_origin[1]:.3f} Z{project_config.stock_origin[2]:.3f}"
            )
            lines.append(
                f"  소재 크기: X{stock_size[0]:.3f} "
                f"Y{stock_size[1]:.3f} Z{stock_size[2]:.3f} mm"
            )
            lines.append(
                f"  소재 범위: min={project_config.stock_min.tolist()}  "
                f"max={project_config.stock_max.tolist()}"
            )
            lines.append(f"  격자 해상도: {project_config.stock_resolution:.3f} mm")
        else:
            lines.append("  프로젝트 설정 정보 없음")
        lines.append("")

        lines.append(sep_minor)
        lines.append("  [ 파싱 요약 ]")
        lines.append(sep_minor)
        total_segments = len(toolpath.segments)
        rapid_segments = len([s for s in toolpath.segments if s.motion_type == MotionType.RAPID])
        linear_segments = len([s for s in toolpath.segments if s.motion_type == MotionType.LINEAR])
        arc_segments = len([s for s in toolpath.segments if s.is_arc])
        dwell_segments = len([s for s in toolpath.segments if s.motion_type == MotionType.DWELL])
        lines.append(f"  총 세그먼트:       {total_segments:>8d} 개")
        lines.append(f"  급속 이동 (G0):    {rapid_segments:>8d} 개")
        lines.append(f"  직선 이송 (G1):    {linear_segments:>8d} 개")
        lines.append(f"  원호 이동 (G2/G3): {arc_segments:>8d} 개")
        lines.append(f"  정지 (G4):         {dwell_segments:>8d} 개")
        lines.append("")

        lines.append(sep_minor)
        lines.append("  [ 공구 사용 현황 ]")
        lines.append(sep_minor)
        if toolpath.used_tools:
            lines.append(f"  {'번호':>4}  {'이름':<24}  {'직경':>10}  {'종류':<14}  {'상태'}")
            lines.append("  " + "-" * 68)
            for tool_number in sorted(toolpath.used_tools):
                tool = tools.get(tool_number)
                if tool is None:
                    lines.append(f"  T{tool_number:<3}  {'(미정의)':<24}  {'':>10}  {'':<14}  누락")
                    continue
                lines.append(
                    f"  T{tool_number:<3}  {tool.name[:24]:<24}  "
                    f"Ø{tool.diameter:>7.2f}  {tool.tool_type.value:<14}  사용"
                )
        else:
            lines.append("  공구 정보 없음")
        lines.append("")

        lines.append(sep_minor)
        lines.append("  [ 이동 / 시간 요약 ]")
        lines.append(sep_minor)
        lines.append(f"  총 이동 거리:   {toolpath.total_distance:>10.2f} mm")
        lines.append(f"  급속 이동 거리: {toolpath.rapid_distance:>10.2f} mm")
        lines.append(f"  절삭 이동 거리: {toolpath.cutting_distance:>10.2f} mm")
        if toolpath.total_distance > 0.0:
            cutting_ratio = toolpath.cutting_distance / toolpath.total_distance * 100.0
            lines.append(f"  절삭 비율:      {cutting_ratio:>10.1f} %")

        estimated_time = self._time_estimator.estimate_total_time(toolpath, machine)
        lines.append(
            f"  예상 가공 시간: {self._time_estimator.format_time(estimated_time)} "
            f"({estimated_time:.1f}초)"
        )

        if toolpath.segments:
            bounds_min, bounds_max = toolpath.get_bounds()
            lines.append(f"  경로 X 범위: {bounds_min[0]:>8.2f} ~ {bounds_max[0]:>8.2f} mm")
            lines.append(f"  경로 Y 범위: {bounds_min[1]:>8.2f} ~ {bounds_max[1]:>8.2f} mm")
            lines.append(f"  경로 Z 범위: {bounds_min[2]:>8.2f} ~ {bounds_max[2]:>8.2f} mm")
        lines.append("")

        lines.append(sep_minor)
        lines.append("  [ 검증 결과 ]")
        lines.append(sep_minor)
        error_count = sum(1 for warning in warnings if warning.severity == "ERROR")
        warning_count = sum(1 for warning in warnings if warning.severity == "WARNING")
        info_count = sum(1 for warning in warnings if warning.severity == "INFO")
        lines.append(f"  오류:   {error_count:>5d}개")
        lines.append(f"  경고:   {warning_count:>5d}개")
        lines.append(f"  정보:   {info_count:>5d}개")
        lines.append("")

        if warnings:
            for warning in warnings:
                severity_tag = {
                    "ERROR": "[오류]",
                    "WARNING": "[경고]",
                    "INFO": "[정보]",
                }.get(warning.severity, "[기타]")
                lines.append(f"  {severity_tag} 라인 {warning.line_number:>5d} | {warning.code}")
                lines.append(f"    - {warning.message}")
                if warning.position is not None:
                    lines.append(
                        f"    - 위치: X{warning.position[0]:.3f} "
                        f"Y{warning.position[1]:.3f} Z{warning.position[2]:.3f}"
                    )
                lines.append("")
        else:
            lines.append("  검증 경고 없음")
            lines.append("")

        if toolpath.warnings:
            lines.append(sep_minor)
            lines.append("  [ 파싱 경고 ]")
            lines.append(sep_minor)
            for warning in toolpath.warnings:
                lines.append(f"  [{warning.severity}] 라인 {warning.line_number}: {warning.message}")
            lines.append("")

        if machining_analysis is not None:
            lines.append(sep_minor)
            lines.append("  [ 가공 해석 결과 ]")
            lines.append(sep_minor)

            analysis = machining_analysis
            params = analysis.model_params
            lines.append(f"  재료 설정: {params.get('material', '?')}")
            lines.append(f"  비절삭저항 Kc1: {params.get('Kc1', 0):.0f} N/mm^2")
            lines.append(f"  mc 계수: {params.get('mc', 0):.3f}")
            lines.append(
                f"  스핀들 정격 출력: {params.get('spindle_rated_power_w', 0) / 1000:.2f} kW"
            )
            lines.append(
                f"  축 강성 X/Y/Z: {params.get('x_axis_stiffness_n_per_um', 0):.1f} / "
                f"{params.get('y_axis_stiffness_n_per_um', 0):.1f} / "
                f"{params.get('z_axis_stiffness_n_per_um', 0):.1f} N/um"
            )
            lines.append("")
            lines.append(f"  최대 스핀들 부하: {analysis.max_spindle_load_pct:.1f}%")
            lines.append(f"  평균 스핀들 부하: {analysis.avg_spindle_load_pct:.1f}%")
            lines.append(f"  최대 채터 위험:   {analysis.max_chatter_risk * 100:.1f}%")
            lines.append(f"  평균 채터 위험:   {analysis.avg_chatter_risk * 100:.1f}%")
            lines.append(f"  최대 절삭력:      {analysis.max_cutting_force:.1f} N")
            lines.append(
                f"  평균 AE/AP:       {analysis.avg_radial_depth_ae:.2f} / "
                f"{analysis.avg_axial_depth_ap:.2f} mm"
            )
            lines.append(
                f"  최대 AE/AP:       {analysis.max_radial_depth_ae:.2f} / "
                f"{analysis.max_axial_depth_ap:.2f} mm"
            )
            lines.append(
                f"  최대 축진동 X/Y/Z: {analysis.max_vibration_x_um:.2f} / "
                f"{analysis.max_vibration_y_um:.2f} / "
                f"{analysis.max_vibration_z_um:.2f} um"
            )
            lines.append(f"  최대 합성 진동:   {analysis.max_resultant_vibration_um:.2f} um")
            lines.append(
                f"  평균 축진동 X/Y/Z: {analysis.avg_vibration_x_um:.2f} / "
                f"{analysis.avg_vibration_y_um:.2f} / "
                f"{analysis.avg_vibration_z_um:.2f} um"
            )
            lines.append(f"  평균 합성 진동:   {analysis.avg_resultant_vibration_um:.2f} um")
            lines.append(
                f"  고위험 블록:      {analysis.high_risk_segment_count}개 "
                f"({analysis.high_risk_pct:.1f}%)"
            )
            lines.append(
                f"  공격 절삭 블록:   {analysis.aggressive_segment_count}개 "
                f"({analysis.aggressive_segment_pct:.1f}%)"
            )
            lines.append("")

            high_risk_results = [result for result in analysis.results if result.is_high_risk]
            if high_risk_results:
                lines.append("  - 채터 고위험 구간 (상위 20개)")
                for result in sorted(
                    high_risk_results,
                    key=lambda item: item.chatter_risk_score,
                    reverse=True,
                )[:20]:
                    lines.append(
                        f"    블록 {result.segment_id:>5d} | "
                        f"AE/AP={result.radial_depth_ae:5.2f}/{result.axial_depth_ap:5.2f} mm | "
                        f"부하={result.spindle_load_pct:5.1f}% | "
                        f"채터={result.chatter_risk_pct:5.1f}% | "
                        f"합성진동={result.resultant_vibration_um:6.2f} um | "
                        f"[{result.chatter_risk_level.value}]"
                    )
                    lines.append(
                        f"      축진동 X/Y/Z = {result.vibration_x_um:.2f} / "
                        f"{result.vibration_y_um:.2f} / {result.vibration_z_um:.2f} um"
                    )
                    if result.warning_messages:
                        lines.append(f"      주의: {' / '.join(result.warning_messages[:4])}")
                lines.append("")

            aggressive_results = [
                result for result in analysis.results if result.is_aggressive_cut
            ]
            if aggressive_results:
                lines.append("  - 공격 절삭 구간 (상위 10개)")
                for result in sorted(
                    aggressive_results,
                    key=lambda item: item.aggressiveness_score,
                    reverse=True,
                )[:10]:
                    lines.append(
                        f"    블록 {result.segment_id:>5d} | "
                        f"공격점수={result.aggressiveness_score:.2f} | "
                        f"AE/AP={result.radial_depth_ae:.2f}/{result.axial_depth_ap:.2f} mm | "
                        f"부하={result.spindle_load_pct:.1f}%"
                    )
                lines.append("")

        lines.append(sep_minor)
        lines.append("  [ 참고 사항 ]")
        lines.append(sep_minor)
        lines.append("  * AE/AP와 축진동은 스톡 기반 근사 계산 결과입니다.")
        lines.append("  * footprint는 Z-map 해상도에 따라 세밀도가 달라집니다.")
        lines.append("  * 채터 위험도는 SLD 완전 해석이 아닌 공학적 위험도 평가입니다.")
        lines.append("  * 실제 가공 적용 전에는 장비/공구/소재 실측 조건으로 재검토해야 합니다.")
        lines.append("")
        lines.append(sep_major)
        lines.append("  End of Report")
        lines.append(sep_major)

        return "\n".join(lines)

    def save_report(self, report_text: str, filepath: str):
        """보고서를 텍스트 파일로 저장합니다."""

        save_dir = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(save_dir, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as file:
            file.write(report_text)

        logger.info("보고서 저장 완료: %s", filepath)
