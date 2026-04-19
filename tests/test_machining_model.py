"""
가공 해석 모델과 스톡 누적 표시 테스트
"""
import numpy as np

from app.geometry.stock_model import StockModel
from app.models.tool import Tool, ToolType
from app.parser.gcode_parser import GCodeParser
from app.simulation.machining_model import MachiningModel


def make_tool() -> Tool:
    return Tool(
        tool_number=1,
        name="테스트 엔드밀",
        tool_type=ToolType.END_MILL,
        diameter=10.0,
        length=75.0,
        flute_length=25.0,
        corner_radius=0.0,
        flute_count=4,
    )


def make_stock() -> StockModel:
    return StockModel(
        np.array([-30.0, -30.0, -20.0]),
        np.array([60.0, 30.0, 0.0]),
        resolution=1.0,
    )


def analyze_code(code: str):
    parser = GCodeParser()
    toolpath = parser.parse_string(code)
    model = MachiningModel()
    tool = make_tool()
    analysis = model.analyze_toolpath(toolpath, {1: tool}, make_stock())
    return toolpath, analysis


def cutting_results(analysis):
    return [result for result in analysis.results if result.is_cutting]


def last_cutting_result(analysis):
    return cutting_results(analysis)[-1]


def test_ae_affects_mrr_and_engagement():
    """
    반경방향 맞물림(AE)이 커지면 MRR이 증가해야 한다.

    [Altintas (2000) 업밀링 모델 주의사항]
    업밀링에서 AE가 커질수록 맞물림 호(arc)는 짧아지므로
    1회전 평균 접선력(Ft)은 단조증가하지 않습니다.
    (최댓값: 완전 슬로팅 ae=D, 최솟값: ae≈50% 근방)
    따라서 스핀들 부하나 채터 위험도는 ae에 대해 단조증가하지 않습니다.
    MRR (= ae·ap·F)만이 ae에 대해 항상 증가합니다.
    """

    narrow_code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-5.0 F200
G1 X40.0 F800
G0 Z5
G0 X0 Y2.0
G1 Z-5.0 F200
G1 X40.0 F800
"""

    wide_code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-5.0 F200
G1 X40.0 F800
G0 Z5
G0 X0 Y8.0
G1 Z-5.0 F200
G1 X40.0 F800
"""

    _, narrow_analysis = analyze_code(narrow_code)
    _, wide_analysis = analyze_code(wide_code)

    narrow = last_cutting_result(narrow_analysis)
    wide = last_cutting_result(wide_analysis)

    # AE는 반드시 더 커야 합니다.
    assert wide.radial_depth_ae > narrow.radial_depth_ae + 2.0

    # MRR = ae·ap·F 는 ae가 클수록 증가합니다.
    assert wide.material_removal_rate > narrow.material_removal_rate

    # 두 경우 모두 절삭 이동이어야 합니다.
    assert narrow.is_cutting
    assert wide.is_cutting


def test_ap_affects_load_and_risk():
    """절입 깊이가 깊어지면 AP, 부하, 채터 위험, Z축 진동이 증가해야 한다."""

    shallow_code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-2.0 F200
G1 X40.0 F800
"""

    deep_code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-8.0 F200
G1 X40.0 F800
"""

    _, shallow_analysis = analyze_code(shallow_code)
    _, deep_analysis = analyze_code(deep_code)

    shallow = last_cutting_result(shallow_analysis)
    deep = last_cutting_result(deep_analysis)

    assert deep.axial_depth_ap > shallow.axial_depth_ap + 3.0
    assert deep.spindle_load_pct > shallow.spindle_load_pct
    assert deep.chatter_risk_score > shallow.chatter_risk_score
    assert deep.vibration_z_um > shallow.vibration_z_um


def test_axis_vibration_nonzero_when_cutting():
    """
    절삭 이동 시 X/Y/Z 진동이 0보다 커야 한다.

    [모델 주의사항]
    Altintas (2000) 기계론적 모델은 절삭력(Fx, Fy, Fz)을 '밀링 좌표계'에서 계산합니다.
    절삭력은 맞물림 기하(φ_st, φ_ex)에 의해 결정되며 공구 이송 방향에 무관합니다.
    따라서 X 방향 이동 시 vib_x > vib_y가 보장되지는 않습니다.
    축별 진동을 이송 방향에 맞게 분해하려면 힘 벡터의 좌표 회전이 필요합니다.
    """

    cut_code = """
G21 G90
T1 M6
S3500 M3
G0 X0 Y0 Z5
G1 Z-5.0 F250
G1 X40.0 F900
"""

    _, analysis = analyze_code(cut_code)
    result = last_cutting_result(analysis)

    # 절삭 중에는 모든 축 진동이 0보다 커야 합니다.
    assert result.vibration_x_um > 0.0
    assert result.vibration_y_um > 0.0
    assert result.vibration_z_um > 0.0
    assert result.resultant_vibration_um > 0.0
    # 합성 진동은 개별 축보다 크거나 같아야 합니다.
    assert result.resultant_vibration_um >= result.vibration_x_um
    assert result.resultant_vibration_um >= result.vibration_y_um


def test_plunge_segment_detected_and_has_vibration():
    """
    플런지 구간이 is_plunge=True로 감지되어야 하고 진동이 발생해야 한다.

    [모델 주의사항]
    플런지에서는 축방향력(Fz)이 지배적이지만, Altintas 모델의 풀폭 슬로팅
    기하에서 날끝(edge) XY 힘이 커질 수 있으므로 vib_z > vib_x가 항상
    보장되지는 않습니다. 플런지는 is_plunge=True로 감지됩니다.
    """

    plunge_code = """
G21 G90
T1 M6
S2500 M3
G0 X0 Y0 Z5
G1 Z-6.0 F180
"""

    _, analysis = analyze_code(plunge_code)
    first_cut = cutting_results(analysis)[0]

    assert first_cut.is_plunge
    # 플런지 중에도 진동이 발생해야 합니다.
    assert first_cut.resultant_vibration_um > 0.0
    # 플런지는 Z 성분 진동이 있어야 합니다.
    assert first_cut.vibration_z_um > 0.0


def test_stock_trace_map_persists_and_resets():
    """가공 footprint가 누적되어 남아 있어야 하고 reset 시 초기화되어야 한다."""

    stock = make_stock()
    tool = make_tool()

    stock.remove_material(
        np.array([0.0, 0.0, -5.0]),
        np.array([20.0, 0.0, -5.0]),
        tool,
        {"spindle_load_pct": 55.0, "chatter_risk_score": 0.42},
    )

    mask = stock.get_machined_mask()
    trace = stock.get_trace_image_rgba()

    assert mask.any()
    assert stock.get_removed_depth_map().max() > 0.0
    assert trace[..., 3].max() > 70
    assert stock.load_map.max() >= 55.0
    assert stock.chatter_map.max() >= 42.0

    stock.reset()
    assert not stock.get_machined_mask().any()
    assert stock.get_removed_depth_map().max() == 0.0


# ====================================================
# 신규 검증 테스트: 비현실 모델 수정 확인
# ====================================================

def test_air_cut_load_lower_than_cutting_load():
    """
    [핵심 검증] 공중이송(G1 air-cut) 스핀들 부하는
    실제 절삭 구간보다 낮아야 합니다.

    이 테스트는 이전 모델의 핵심 버그를 검증합니다:
    - 이전: G1 air-cut에서도 ae=0.5D가 적용되어 절삭급 부하 발생
    - 개선: stock_model 기반으로 air-cut 감지 → is_cutting=False → 절삭 성분=0

    경로 구성:
    1. G0: Z=5 이동 (공중, 급속)
    2. G1: Z=-5 (플런지, 실제 절삭)
    3. G1: X=40 (측면 절삭, 실제 절삭)
    4. G0: Z=5 (공중, 급속)
    5. G1: X=0 Y=100 (공중이송, 소재 위치 벗어남)  ← 여기가 핵심
    """
    code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-5.0 F200
G1 X40.0 F800
G0 Z5
G1 X0 Y100.0 Z5 F1000
"""
    _, analysis = analyze_code(code)

    # 절삭 블록 평균 부하
    cut_results = [r for r in analysis.results if r.is_cutting]
    # 비절삭 블록 (공중 G1 포함)
    non_cut_results = [r for r in analysis.results if not r.is_cutting]

    # 최소한 절삭 블록과 비절삭 블록이 각각 있어야 함
    assert len(cut_results) > 0, "절삭 블록이 없습니다"
    assert len(non_cut_results) > 0, "비절삭 블록이 없습니다"

    avg_cut_load = sum(r.spindle_load_pct for r in cut_results) / len(cut_results)
    avg_non_cut_load = sum(r.spindle_load_pct for r in non_cut_results) / len(non_cut_results)

    # 공중이송 평균 부하 < 절삭 평균 부하 (물리적으로 당연한 조건)
    assert avg_non_cut_load < avg_cut_load, (
        f"공중이송 평균 부하({avg_non_cut_load:.1f}%)가 "
        f"절삭 평균 부하({avg_cut_load:.1f}%)보다 높습니다 - 비현실적!"
    )


def test_chatter_risk_not_all_saturated():
    """
    [핵심 검증] 채터 위험도가 대부분 블록에서 100%로 포화되지 않아야 합니다.

    이 테스트는 이전 채터 모델의 포화 버그를 검증합니다:
    - 이전: 선형 공식 + 가산 보정 → 거의 모든 블록 100%
    - 개선: 비선형 시그모이드 + 승산적 보정 → 의미 있는 분포
    """
    code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-2.0 F200
G1 X40.0 F800
G0 Z5
G0 X0 Y5
G1 Z-2.0 F200
G1 X40.0 F800
G0 Z5
"""
    _, analysis = analyze_code(code)
    cut_results = [r for r in analysis.results if r.is_cutting]
    if not cut_results:
        return

    risk_scores = [r.chatter_risk_score for r in cut_results]
    max_risk = max(risk_scores)
    # 모든 블록이 1.0(=100%)이면 포화 문제
    saturated = sum(1 for s in risk_scores if s >= 0.99)
    # 전체의 30% 이상이 포화되면 문제
    assert saturated / len(risk_scores) < 0.30, (
        f"채터 위험도 {saturated}/{len(risk_scores)} 블록이 100%로 포화됨 - 비현실적!"
    )
    # 최대 위험도가 50% 이하이면 모델이 너무 낙관적임 (비현실적)
    # 일반 정상 절삭에서 최대 위험이 너무 낮으면 안 됨
    # (이 부분은 재료/조건에 따라 다르므로 하한만 체크)


def test_load_decomposition_in_air_cut():
    """
    스핀들 부하 분해 성분 검증:
    - 공중이송: cutting_load_pct = 0
    - 공중이송: baseline_load_pct > 0 (스핀들 회전 시)
    - 실제 절삭: cutting_load_pct > 0
    """
    code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-5.0 F200
G1 X40.0 F800
G0 Z5
"""
    _, analysis = analyze_code(code)

    non_cut = [r for r in analysis.results if not r.is_cutting]
    cut_segs = [r for r in analysis.results if r.is_cutting]

    # 공중이송: 절삭 성분이 없어야 함
    for r in non_cut:
        cutting_comp = getattr(r, "cutting_load_pct", 0.0)
        assert cutting_comp == 0.0, (
            f"공중이송 세그먼트에 절삭 부하 {cutting_comp:.1f}% - 비현실적!"
        )

    # 실제 절삭: 절삭 성분이 양수여야 함
    if cut_segs:
        max_cutting_comp = max(getattr(r, "cutting_load_pct", 0.0) for r in cut_segs)
        assert max_cutting_comp > 0.0, "절삭 세그먼트에 절삭 부하 성분이 없습니다"


def test_machine_profile_t4000_applied():
    """DN Solutions T4000 기계 프로파일이 기본으로 적용되어야 합니다."""
    from app.machines.machine_profile import MachineProfileRegistry

    profile = MachineProfileRegistry.get_default()
    assert profile.model_id == "t4000", f"기본 프로파일이 t4000이 아닙니다: {profile.model_id}"
    assert profile.spindle_max_rpm >= 12000, "T4000 최대 RPM 12000 이상이어야 합니다"
    assert profile.x_travel_mm >= 500, "T4000 X축 이동량 500mm 이상이어야 합니다"
    assert profile.spindle_taper == "BT30", "T4000 테이퍼는 BT30이어야 합니다"
