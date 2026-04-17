"""
보고서/CSV 저장 서비스 모듈

텍스트 보고서와 CSV 기반 해석 결과 저장을 담당합니다.

[저장 철학]
- 현장 검토용 텍스트 보고서와 후처리/엑셀 분석용 CSV를 분리합니다.
- 세그먼트 단위 상세 정보는 별도 CSV로 저장해 좌표, 공구, 가공 상태,
  AE/AP, 부하, 진동, 위험도를 한 번에 재활용할 수 있게 합니다.
- 모든 컬럼명과 설명은 한국어 맥락에 맞게 유지하되, CSV 헤더는
  후처리 편의성을 위해 영문 snake_case를 사용합니다.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import numpy as np

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
    """검증/가공 해석 결과를 텍스트와 CSV로 저장하는 서비스"""

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
        """화면 표시 및 파일 저장용 텍스트 보고서를 생성합니다."""

        lines: List[str] = []
        sep_major = "=" * 78
        sep_minor = "-" * 78

        total_segments = len(toolpath.segments)
        rapid_segments = len([s for s in toolpath.segments if s.motion_type == MotionType.RAPID])
        linear_segments = len([s for s in toolpath.segments if s.motion_type == MotionType.LINEAR])
        arc_segments = len([s for s in toolpath.segments if s.is_arc])
        dwell_segments = len([s for s in toolpath.segments if s.motion_type == MotionType.DWELL])

        error_count = sum(1 for warning in warnings if warning.severity == "ERROR")
        warning_count = sum(1 for warning in warnings if warning.severity == "WARNING")
        info_count = sum(1 for warning in warnings if warning.severity == "INFO")

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
                f"Y{project_config.stock_origin[1]:.3f} "
                f"Z{project_config.stock_origin[2]:.3f}"
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
            lines.append("  프로젝트 기반 소재 정보 없음")
        lines.append("")

        lines.append(sep_minor)
        lines.append("  [ 툴패스 요약 ]")
        lines.append(sep_minor)
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
            lines.append(f"  {'번호':>4}  {'이름':<24}  {'직경':>10}  {'종류':<14}  상태")
            lines.append("  " + "-" * 70)
            for tool_number in sorted(toolpath.used_tools):
                tool = tools.get(tool_number)
                if tool is None:
                    lines.append(f"  T{tool_number:<3}  {'(미정의)':<24}  {'':>10}  {'':<14}  누락")
                    continue
                lines.append(
                    f"  T{tool_number:<3}  {tool.name[:24]:<24}  "
                    f"{tool.diameter:>10.2f}  {tool.tool_type.value:<14}  사용"
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
            analysis = machining_analysis
            params = analysis.model_params

            lines.append(sep_minor)
            lines.append("  [ 가공 해석 결과 ]")
            lines.append(sep_minor)
            lines.append(f"  재질 설정: {params.get('material', '?')}")
            lines.append(f"  비절삭 계수 Kc1: {params.get('Kc1', 0):.0f} N/mm^2")
            lines.append(f"  mc 계수: {params.get('mc', 0):.3f}")
            lines.append(
                f"  스핀들 정격 출력: {params.get('spindle_rated_power_w', 0) / 1000:.2f} kW"
            )
            lines.append(
                f"  축 강성 X/Y/Z: "
                f"{params.get('x_axis_stiffness_n_per_um', 0):.1f} / "
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
                f"  고위험 블록:      {analysis.high_risk_segment_count}개"
                f" ({analysis.high_risk_pct:.1f}%)"
            )
            lines.append(
                f"  공격 절삭 블록:   {analysis.aggressive_segment_count}개"
                f" ({analysis.aggressive_segment_pct:.1f}%)"
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

        lines.append(sep_minor)
        lines.append("  [ 참고 사항 ]")
        lines.append(sep_minor)
        lines.append("  * AE/AP 및 축방향 진동은 절삭 조건 기반 공학 근사 계산 결과입니다.")
        lines.append("  * 가공 흔적의 footprint와 Z-map은 격자 해상도에 따라 시각 차이가 납니다.")
        lines.append("  * 채터 위험은 SLD 기반 정밀 해석이 아닌, 공정 불안정도 근사 지표입니다.")
        lines.append("  * 실제 적용 전에는 장비/공구/소재 실측 조건으로 재검증해야 합니다.")
        lines.append("")
        lines.append(sep_major)
        lines.append("  End of Report")
        lines.append(sep_major)

        return "\n".join(lines)

    def save_report(self, report_text: str, filepath: str):
        """텍스트 보고서를 파일로 저장합니다."""

        save_dir = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(save_dir, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as file:
            file.write(report_text)

        logger.info("보고서 저장 완료: %s", filepath)

    def save_analysis_csv_bundle(
        self,
        filepath: str,
        toolpath: Toolpath,
        warnings: List[VerificationWarning],
        machine: MachineDef,
        tools: Dict[int, Tool],
        project_config: Optional[ProjectConfig] = None,
        machining_analysis: Optional[MachiningAnalysis] = None,
    ) -> Dict[str, str]:
        """
        해석 결과를 CSV 묶음으로 저장합니다.

        저장 파일:
        - *_summary.csv: 프로젝트/가공 요약
        - *_tools.csv: 공구 정보
        - *_warnings.csv: 검증 경고
        - *_segments.csv: 세그먼트 해석/좌표/상태 상세
        """

        base_dir = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(base_dir, exist_ok=True)

        root, ext = os.path.splitext(os.path.abspath(filepath))
        if ext.lower() != ".csv":
            root = os.path.abspath(filepath)

        paths = {
            "summary": f"{root}_summary.csv",
            "tools": f"{root}_tools.csv",
            "warnings": f"{root}_warnings.csv",
            "segments": f"{root}_segments.csv",
        }

        self._write_csv(paths["summary"], self._build_summary_rows(toolpath, warnings, machine, project_config, machining_analysis))
        self._write_csv(paths["tools"], self._build_tool_rows(toolpath, tools))
        self._write_csv(paths["warnings"], self._build_warning_rows(warnings))
        self._write_csv(paths["segments"], self._build_segment_rows(toolpath, machine, tools, machining_analysis))

        logger.info("CSV 저장 완료: %s", paths)
        return paths

    def _build_summary_rows(
        self,
        toolpath: Toolpath,
        warnings: List[VerificationWarning],
        machine: MachineDef,
        project_config: Optional[ProjectConfig],
        machining_analysis: Optional[MachiningAnalysis],
    ) -> List[dict]:
        """요약 CSV 행을 생성합니다."""

        rows: List[dict] = []

        def add_row(category: str, key: str, value, unit: str = ""):
            rows.append({
                "category": category,
                "key": key,
                "value": value,
                "unit": unit,
            })

        add_row("meta", "generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        add_row("meta", "machine_name", machine.name)
        add_row("toolpath", "total_segments", len(toolpath.segments), "count")
        add_row("toolpath", "total_distance", round(toolpath.total_distance, 6), "mm")
        add_row("toolpath", "rapid_distance", round(toolpath.rapid_distance, 6), "mm")
        add_row("toolpath", "cutting_distance", round(toolpath.cutting_distance, 6), "mm")

        estimated_time = self._time_estimator.estimate_total_time(toolpath, machine)
        add_row("toolpath", "estimated_time_s", round(estimated_time, 6), "s")

        if toolpath.segments:
            bounds_min, bounds_max = toolpath.get_bounds()
            for axis, idx in (("x", 0), ("y", 1), ("z", 2)):
                add_row("bounds", f"{axis}_min", round(float(bounds_min[idx]), 6), "mm")
                add_row("bounds", f"{axis}_max", round(float(bounds_max[idx]), 6), "mm")

        error_count = sum(1 for warning in warnings if warning.severity == "ERROR")
        warning_count = sum(1 for warning in warnings if warning.severity == "WARNING")
        info_count = sum(1 for warning in warnings if warning.severity == "INFO")
        add_row("warnings", "error_count", error_count, "count")
        add_row("warnings", "warning_count", warning_count, "count")
        add_row("warnings", "info_count", info_count, "count")

        if project_config is not None:
            stock_size = project_config.get_stock_size()
            add_row("stock", "origin_mode", project_config.stock_origin_mode)
            add_row("stock", "origin_x", round(float(project_config.stock_origin[0]), 6), "mm")
            add_row("stock", "origin_y", round(float(project_config.stock_origin[1]), 6), "mm")
            add_row("stock", "origin_z", round(float(project_config.stock_origin[2]), 6), "mm")
            add_row("stock", "size_x", round(float(stock_size[0]), 6), "mm")
            add_row("stock", "size_y", round(float(stock_size[1]), 6), "mm")
            add_row("stock", "size_z", round(float(stock_size[2]), 6), "mm")
            add_row("stock", "resolution", round(float(project_config.stock_resolution), 6), "mm")

        if machining_analysis is not None:
            add_row("analysis", "max_spindle_load_pct", round(machining_analysis.max_spindle_load_pct, 6), "%")
            add_row("analysis", "avg_spindle_load_pct", round(machining_analysis.avg_spindle_load_pct, 6), "%")
            add_row("analysis", "max_chatter_risk_pct", round(machining_analysis.max_chatter_risk * 100.0, 6), "%")
            add_row("analysis", "avg_chatter_risk_pct", round(machining_analysis.avg_chatter_risk * 100.0, 6), "%")
            add_row("analysis", "max_cutting_force_n", round(machining_analysis.max_cutting_force, 6), "N")
            add_row("analysis", "avg_ae_mm", round(machining_analysis.avg_radial_depth_ae, 6), "mm")
            add_row("analysis", "avg_ap_mm", round(machining_analysis.avg_axial_depth_ap, 6), "mm")
            add_row("analysis", "max_ae_mm", round(machining_analysis.max_radial_depth_ae, 6), "mm")
            add_row("analysis", "max_ap_mm", round(machining_analysis.max_axial_depth_ap, 6), "mm")
            add_row("analysis", "max_vibration_x_um", round(machining_analysis.max_vibration_x_um, 6), "um")
            add_row("analysis", "max_vibration_y_um", round(machining_analysis.max_vibration_y_um, 6), "um")
            add_row("analysis", "max_vibration_z_um", round(machining_analysis.max_vibration_z_um, 6), "um")
            add_row(
                "analysis",
                "max_resultant_vibration_um",
                round(machining_analysis.max_resultant_vibration_um, 6),
                "um",
            )
            add_row("analysis", "high_risk_segment_count", machining_analysis.high_risk_segment_count, "count")
            add_row("analysis", "aggressive_segment_count", machining_analysis.aggressive_segment_count, "count")

            for key, value in machining_analysis.model_params.items():
                add_row("model_params", key, value)

        return rows

    def _build_tool_rows(self, toolpath: Toolpath, tools: Dict[int, Tool]) -> List[dict]:
        """공구 정보 CSV 행을 생성합니다."""

        rows: List[dict] = []
        for tool_number in sorted(toolpath.used_tools):
            tool = tools.get(tool_number)
            if tool is None:
                rows.append({
                    "tool_number": tool_number,
                    "name": "",
                    "tool_type": "",
                    "diameter_mm": "",
                    "radius_mm": "",
                    "length_mm": "",
                    "flute_length_mm": "",
                    "corner_radius_mm": "",
                    "flute_count": "",
                    "material": "",
                    "defined": False,
                })
                continue

            rows.append({
                "tool_number": tool.tool_number,
                "name": tool.name,
                "tool_type": tool.tool_type.value,
                "diameter_mm": round(float(tool.diameter), 6),
                "radius_mm": round(float(tool.radius), 6),
                "length_mm": round(float(tool.length), 6),
                "flute_length_mm": round(float(tool.flute_length), 6),
                "corner_radius_mm": round(float(tool.corner_radius), 6),
                "flute_count": int(tool.flute_count),
                "material": tool.material,
                "defined": True,
            })

        return rows

    def _build_warning_rows(self, warnings: List[VerificationWarning]) -> List[dict]:
        """검증 경고 CSV 행을 생성합니다."""

        rows: List[dict] = []
        for warning in warnings:
            position = warning.position if warning.position is not None else [None, None, None]
            rows.append({
                "severity": warning.severity,
                "code": warning.code,
                "message": warning.message,
                "line_number": warning.line_number,
                "segment_id": warning.segment_id,
                "x_mm": self._round_or_blank(position[0]),
                "y_mm": self._round_or_blank(position[1]),
                "z_mm": self._round_or_blank(position[2]),
            })
        return rows

    def _build_segment_rows(
        self,
        toolpath: Toolpath,
        machine: MachineDef,
        tools: Dict[int, Tool],
        machining_analysis: Optional[MachiningAnalysis],
    ) -> List[dict]:
        """세그먼트 상세 CSV 행을 생성합니다."""

        rows: List[dict] = []
        cumulative_distance = 0.0
        cumulative_cutting_distance = 0.0
        cumulative_time = 0.0
        cumulative_cutting_time = 0.0

        for index, segment in enumerate(toolpath.segments):
            result = None
            if machining_analysis is not None and index < len(machining_analysis.results):
                result = machining_analysis.results[index]

            tool = tools.get(segment.tool_number)
            segment_distance = float(segment.get_distance())
            segment_time = self._estimate_segment_time_seconds(segment, machine)
            cumulative_distance += segment_distance
            cumulative_time += segment_time
            if segment.is_cutting_move:
                cumulative_cutting_distance += segment_distance
                cumulative_cutting_time += segment_time

            warning_messages = ""
            chatter_level = ""
            if result is not None:
                warning_messages = " | ".join(result.warning_messages)
                chatter_level = result.chatter_risk_level.value

            rows.append({
                "segment_index": index,
                "segment_id": segment.segment_id,
                "line_number": segment.line_number,
                "motion_type": segment.motion_type.value,
                "is_arc": bool(segment.is_arc),
                "is_cutting_move": bool(segment.is_cutting_move),
                "spindle_on": bool(segment.spindle_on),
                "tool_number": segment.tool_number,
                "tool_name": tool.name if tool is not None else "",
                "tool_type": tool.tool_type.value if tool is not None else "",
                "tool_diameter_mm": self._round_or_blank(tool.diameter if tool is not None else None),
                "tool_radius_mm": self._round_or_blank(tool.radius if tool is not None else None),
                "tool_flute_count": int(tool.flute_count) if tool is not None else "",
                "feedrate_mm_min": round(float(segment.feedrate), 6),
                "spindle_speed_rpm": round(float(segment.spindle_speed), 6),
                "start_x_mm": round(float(segment.start_pos[0]), 6),
                "start_y_mm": round(float(segment.start_pos[1]), 6),
                "start_z_mm": round(float(segment.start_pos[2]), 6),
                "end_x_mm": round(float(segment.end_pos[0]), 6),
                "end_y_mm": round(float(segment.end_pos[1]), 6),
                "end_z_mm": round(float(segment.end_pos[2]), 6),
                "arc_center_x_mm": self._round_or_blank(segment.arc_center[0] if segment.arc_center is not None else None),
                "arc_center_y_mm": self._round_or_blank(segment.arc_center[1] if segment.arc_center is not None else None),
                "arc_center_z_mm": self._round_or_blank(segment.arc_center[2] if segment.arc_center is not None else None),
                "arc_radius_mm": self._round_or_blank(segment.arc_radius),
                "segment_distance_mm": round(segment_distance, 6),
                "cumulative_distance_mm": round(cumulative_distance, 6),
                "cumulative_cutting_distance_mm": round(cumulative_cutting_distance, 6),
                "estimated_segment_time_s": round(segment_time, 6),
                "cumulative_time_s": round(cumulative_time, 6),
                "cumulative_cutting_time_s": round(cumulative_cutting_time, 6),
                "cutting_speed_m_min": self._result_value(result, "cutting_speed"),
                "feed_per_tooth_mm": self._result_value(result, "feed_per_tooth"),
                "radial_depth_ae_mm": self._result_value(result, "radial_depth_ae"),
                "axial_depth_ap_mm": self._result_value(result, "axial_depth_ap"),
                "radial_ratio": self._result_value(result, "radial_ratio"),
                "engagement_ratio": self._result_value(result, "engagement_ratio"),
                "material_removal_rate_mm3_min": self._result_value(result, "material_removal_rate"),
                "estimated_cutting_force_n": self._result_value(result, "estimated_cutting_force"),
                "estimated_spindle_power_w": self._result_value(result, "estimated_spindle_power"),
                "spindle_load_pct": self._result_value(result, "spindle_load_pct"),
                "aggressiveness_score": self._result_value(result, "aggressiveness_score"),
                "estimated_force_x_n": self._result_value(result, "estimated_force_x"),
                "estimated_force_y_n": self._result_value(result, "estimated_force_y"),
                "estimated_force_z_n": self._result_value(result, "estimated_force_z"),
                "vibration_x_um": self._result_value(result, "vibration_x_um"),
                "vibration_y_um": self._result_value(result, "vibration_y_um"),
                "vibration_z_um": self._result_value(result, "vibration_z_um"),
                "resultant_vibration_um": self._result_value(result, "resultant_vibration_um"),
                "chatter_risk_score": self._result_value(result, "chatter_risk_score"),
                "chatter_risk_pct": round(float(result.chatter_risk_pct), 6) if result is not None else "",
                "chatter_risk_level": chatter_level,
                "direction_change_angle_deg": self._result_value(result, "direction_change_angle"),
                "is_plunge": bool(result.is_plunge) if result is not None else False,
                "is_ramp": bool(result.is_ramp) if result is not None else False,
                "is_high_risk": bool(result.is_high_risk) if result is not None else False,
                "is_aggressive_cut": bool(result.is_aggressive_cut) if result is not None else False,
                "warning_messages": warning_messages,
                "raw_block": segment.raw_block,
            })

        return rows

    def _estimate_segment_time_seconds(self, segment, machine: MachineDef) -> float:
        """
        세그먼트 시간 근사값을 계산합니다.

        CSV 저장용 누적 시간은 UI 상태와 독립적으로 재구성 가능해야 하므로
        feedrate/rapid_feedrate 기반 근사 시간을 별도로 계산합니다.
        """

        distance = float(segment.get_distance())
        if distance <= 1e-9:
            return 0.0

        if segment.motion_type == MotionType.RAPID:
            rate = max(float(machine.rapid_feedrate), 1e-6)
        else:
            rate = max(float(segment.feedrate), 1e-6)

        return distance / rate * 60.0

    def _result_value(self, result, attr: str):
        """해석 결과가 없을 때는 빈 문자열을 반환합니다."""

        if result is None:
            return ""
        value = getattr(result, attr)
        if isinstance(value, (float, np.floating)):
            return round(float(value), 6)
        return value

    def _round_or_blank(self, value):
        """숫자는 반올림하고 없으면 빈 문자열로 반환합니다."""

        if value is None:
            return ""
        return round(float(value), 6)

    def _write_csv(self, filepath: str, rows: Iterable[dict]):
        """dict 행 목록을 UTF-8 CSV로 저장합니다."""

        rows = list(rows)
        save_dir = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(save_dir, exist_ok=True)

        if rows:
            fieldnames = list(rows[0].keys())
        else:
            fieldnames = ["empty"]
            rows = [{"empty": ""}]

        with open(filepath, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
