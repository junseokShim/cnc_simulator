"""
보고서 생성(Report Service) 모듈
NC 코드 검증 결과와 시뮬레이션 통계를 포함한 텍스트 보고서를 생성합니다.
"""
from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Optional
import os

from app.models.toolpath import Toolpath, MotionType
from app.models.machine import MachineDef
from app.models.tool import Tool
from app.models.project import ProjectConfig
from app.models.machining_result import MachiningAnalysis, ChatterRiskLevel
from app.verification.rules import VerificationWarning
from app.simulation.time_estimator import TimeEstimator
from app.utils.logger import get_logger

logger = get_logger("report_service")


class ReportService:
    """
    보고서 생성 서비스 클래스

    NC 코드 검증 결과, 가공 통계, 공구 사용 정보 등을
    포맷된 텍스트 보고서로 생성합니다.
    """

    def __init__(self):
        self._time_estimator = TimeEstimator()

    def generate_report(self, toolpath: Toolpath,
                        warnings: List[VerificationWarning],
                        machine: MachineDef,
                        tools: Dict[int, Tool],
                        project_config: Optional[ProjectConfig] = None,
                        machining_analysis: Optional[MachiningAnalysis] = None) -> str:
        """
        종합 검증 보고서를 생성합니다.

        보고서 구성:
        1. 헤더 (프로젝트 정보, 생성 일시)
        2. 파싱 요약 (세그먼트 수, 경고 수)
        3. 공구 사용 테이블
        4. 이동 통계
        5. 예상 가공 시간
        6. 검증 경고/오류 목록
        7. 시스템 한계 주의사항

        Args:
            toolpath: 분석할 공구경로
            warnings: 검증 경고 목록
            machine: 머신 사양
            tools: 공구 딕셔너리
            project_config: 프로젝트 설정 (없어도 됨)

        Returns:
            포맷된 텍스트 보고서 문자열
        """
        lines = []

        # 구분선
        sep_major = "=" * 70
        sep_minor = "-" * 70

        # 1. 헤더
        lines.append(sep_major)
        lines.append("  CNC NC 코드 검증 보고서")
        lines.append("  CNC NC Code Verification Report")
        lines.append(sep_major)
        lines.append(f"  생성 일시: {datetime.now().strftime('%Y년 %m월 %d일 %H:%M:%S')}")

        if project_config:
            lines.append(f"  프로젝트: {project_config.project_name}")
            if project_config.nc_file_path:
                lines.append(f"  NC 파일: {os.path.basename(project_config.nc_file_path)}")
        if toolpath.source_file:
            lines.append(f"  소스 파일: {os.path.basename(toolpath.source_file)}")

        lines.append(f"  머신: {machine.name}")
        lines.append("")

        # 2. 파싱 요약
        lines.append(sep_minor)
        lines.append("  [ 파싱 요약 ]")
        lines.append(sep_minor)

        total_segs = len(toolpath.segments)
        rapid_segs = len([s for s in toolpath.segments if s.motion_type == MotionType.RAPID])
        linear_segs = len([s for s in toolpath.segments if s.motion_type == MotionType.LINEAR])
        arc_segs = len([s for s in toolpath.segments if s.is_arc])
        dwell_segs = len([s for s in toolpath.segments if s.motion_type == MotionType.DWELL])

        lines.append(f"  총 세그먼트:       {total_segs:>8d} 개")
        lines.append(f"  급속 이동 (G0):    {rapid_segs:>8d} 개")
        lines.append(f"  직선 이송 (G1):    {linear_segs:>8d} 개")
        lines.append(f"  원호 이동 (G2/G3): {arc_segs:>8d} 개")
        lines.append(f"  드웰 (G4):         {dwell_segs:>8d} 개")
        lines.append("")

        # 3. 공구 사용 테이블
        lines.append(sep_minor)
        lines.append("  [ 공구 사용 현황 ]")
        lines.append(sep_minor)

        if toolpath.used_tools:
            header = f"  {'번호':>4}  {'이름':<20}  {'직경':>8}  {'종류':<12}  {'사용 여부'}"
            lines.append(header)
            lines.append("  " + "-" * 60)

            for tool_num in sorted(toolpath.used_tools):
                tool = tools.get(tool_num)
                if tool:
                    name = tool.name[:20]
                    diameter = f"φ{tool.diameter:.1f}mm"
                    tool_type = tool.tool_type.value
                    lines.append(
                        f"  T{tool_num:<3}  {name:<20}  {diameter:>8}  {tool_type:<12}  사용됨"
                    )
                else:
                    lines.append(
                        f"  T{tool_num:<3}  {'(미정의)':<20}  {'':>8}  {'':12}  사용됨(미정의)"
                    )
        else:
            lines.append("  공구 정보 없음")

        lines.append("")

        # 4. 이동 통계
        lines.append(sep_minor)
        lines.append("  [ 이동 통계 ]")
        lines.append(sep_minor)
        lines.append(f"  전체 이동 거리:   {toolpath.total_distance:>10.2f} mm")
        lines.append(f"  급속 이동 거리:   {toolpath.rapid_distance:>10.2f} mm")
        lines.append(f"  절삭 이동 거리:   {toolpath.cutting_distance:>10.2f} mm")

        if toolpath.total_distance > 0:
            cutting_ratio = toolpath.cutting_distance / toolpath.total_distance * 100
            lines.append(f"  절삭 비율:        {cutting_ratio:>9.1f} %")

        # 공구경로 범위
        if toolpath.segments:
            bounds_min, bounds_max = toolpath.get_bounds()
            lines.append(f"  X 범위:  {bounds_min[0]:>8.2f} ~ {bounds_max[0]:>8.2f} mm")
            lines.append(f"  Y 범위:  {bounds_min[1]:>8.2f} ~ {bounds_max[1]:>8.2f} mm")
            lines.append(f"  Z 범위:  {bounds_min[2]:>8.2f} ~ {bounds_max[2]:>8.2f} mm")

        lines.append("")

        # 5. 예상 가공 시간
        lines.append(sep_minor)
        lines.append("  [ 예상 가공 시간 ]")
        lines.append(sep_minor)

        estimated_time = self._time_estimator.estimate_total_time(toolpath, machine)
        time_str = self._time_estimator.format_time(estimated_time)
        lines.append(f"  예상 가공 시간: {time_str} ({estimated_time:.1f}초)")
        lines.append(f"  (급속 이동 속도 {machine.rapid_feedrate:.0f} mm/min 기준)")
        lines.append("")

        # 6. 검증 경고/오류 목록
        lines.append(sep_minor)
        lines.append("  [ 검증 결과 ]")
        lines.append(sep_minor)

        error_count = sum(1 for w in warnings if w.severity == "ERROR")
        warning_count = sum(1 for w in warnings if w.severity == "WARNING")
        info_count = sum(1 for w in warnings if w.severity == "INFO")

        lines.append(f"  오류:   {error_count:>5d}개")
        lines.append(f"  경고:   {warning_count:>5d}개")
        lines.append(f"  정보:   {info_count:>5d}개")
        lines.append("")

        if warnings:
            for w in warnings:
                severity_tag = {
                    "ERROR": "[오류]",
                    "WARNING": "[경고]",
                    "INFO": "[정보]"
                }.get(w.severity, "[기타]")

                lines.append(f"  {severity_tag} 라인 {w.line_number:>5d} | {w.code}")
                lines.append(f"    → {w.message}")
                if w.position is not None:
                    lines.append(
                        f"    위치: X{w.position[0]:.2f} "
                        f"Y{w.position[1]:.2f} "
                        f"Z{w.position[2]:.2f}"
                    )
                lines.append("")
        else:
            lines.append("  검증 경고 없음 - NC 코드가 정상입니다.")
            lines.append("")

        # 파싱 중 발생한 경고
        if toolpath.warnings:
            lines.append(sep_minor)
            lines.append("  [ 파싱 경고 ]")
            lines.append(sep_minor)
            for w in toolpath.warnings:
                lines.append(f"  [{w.severity}] 라인 {w.line_number}: {w.message}")
            lines.append("")

        # 6.5 가공 수치 모델 해석 결과
        if machining_analysis is not None:
            lines.append(sep_minor)
            lines.append("  [ 가공 수치 모델 해석 결과 ]")
            lines.append(sep_minor)
            a = machining_analysis
            params = a.model_params
            lines.append(f"  재료 설정:        {params.get('material', '?')}")
            lines.append(f"  비절삭저항 Kc1:   {params.get('Kc1', 0):.0f} N/mm²")
            lines.append(f"  날당이송 지수 mc: {params.get('mc', 0):.3f}")
            lines.append(f"  스핀들 정격출력:  {params.get('spindle_rated_power_w', 0)/1000:.1f} kW")
            lines.append(f"  기본 ae/D 비율:   {params.get('default_ae_ratio', 0):.2f}")
            lines.append(f"  기본 ap:          {params.get('default_ap_mm', 0):.1f} mm")
            lines.append("")
            lines.append(f"  최대 스핀들 부하: {a.max_spindle_load_pct:.1f}%")
            lines.append(f"  평균 스핀들 부하: {a.avg_spindle_load_pct:.1f}%")
            lines.append(f"  최대 채터 위험도: {a.max_chatter_risk*100:.1f}%")
            lines.append(f"  평균 채터 위험도: {a.avg_chatter_risk*100:.1f}%")
            lines.append(f"  최대 절삭력:      {a.max_cutting_force:.1f} N")
            lines.append(f"  고위험 블록 수:   {a.high_risk_segment_count}개 ({a.high_risk_pct:.1f}%)")
            lines.append("")

            # 고위험 세그먼트 목록 (최대 20개)
            high_risk = [r for r in a.results if r.is_high_risk]
            if high_risk:
                lines.append(f"  ※ 채터 고위험 구간 (상위 {min(20, len(high_risk))}개):")
                for r in sorted(high_risk, key=lambda x: x.chatter_risk_score, reverse=True)[:20]:
                    lines.append(
                        f"    블록 {r.segment_id:>5d} | "
                        f"위험도: {r.chatter_risk_pct:5.1f}%  "
                        f"부하: {r.spindle_load_pct:5.1f}%  "
                        f"[{r.chatter_risk_level.value}]"
                    )
                lines.append("")

        # 7. 시스템 한계 주의사항
        lines.append(sep_minor)
        lines.append("  [ 주의사항 및 시스템 한계 ]")
        lines.append(sep_minor)
        lines.append("  * 본 검증 시스템은 Z-맵 방식의 소재 모델을 사용합니다.")
        lines.append("    실제 3D 충돌 검사와 차이가 있을 수 있습니다.")
        lines.append("  * 예상 가공 시간은 근사값이며 실제 머신의 가감속,")
        lines.append("    공구 교환 시간 등에 따라 다를 수 있습니다.")
        lines.append("  * G54~G59 좌표계 오프셋은 현재 지원되지 않습니다.")
        lines.append("  * 서브프로그램(M98/M99)은 현재 지원되지 않습니다.")
        lines.append("  * 스핀들 부하 및 채터 위험도는 공학적 근사 모델 결과입니다.")
        lines.append("    실제 가공 조건과 차이가 있을 수 있으며, 실제 가공 전")
        lines.append("    반드시 숙련된 기술자의 최종 검토가 필요합니다.")
        lines.append("  * 채터 안정성 로브선도(SLD) 완전 해석은 미구현 상태입니다.")
        lines.append("")
        lines.append(sep_major)
        lines.append("  보고서 끝 / End of Report")
        lines.append(sep_major)

        return "\n".join(lines)

    def save_report(self, report_text: str, filepath: str):
        """
        보고서를 텍스트 파일로 저장합니다.

        Args:
            report_text: 저장할 보고서 텍스트
            filepath: 저장 파일 경로
        """
        save_dir = os.path.dirname(os.path.abspath(filepath))
        os.makedirs(save_dir, exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(report_text)

        logger.info(f"보고서 저장 완료: {filepath}")
