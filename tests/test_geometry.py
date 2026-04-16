"""
기하학 모듈 단위 테스트
소재 모델, 공구 기하학, 재료 제거 시뮬레이션을 검증합니다.
"""
import pytest
import numpy as np
from app.geometry.stock_model import StockModel
from app.geometry.tool_geometry import ToolGeometry
from app.models.tool import Tool, ToolType


def make_test_tool(diameter: float = 10.0) -> Tool:
    """테스트용 공구를 생성합니다."""
    return Tool(
        tool_number=1,
        name="테스트 공구",
        tool_type=ToolType.END_MILL,
        diameter=diameter,
        length=75.0,
        flute_length=25.0,
        corner_radius=0.0
    )


def test_stock_creation():
    """소재 모델 생성 테스트"""
    stock = StockModel(
        np.array([-50.0, -50.0, -25.0]),
        np.array([50.0, 50.0, 0.0]),
        resolution=5.0
    )
    # 격자가 생성되어야 함
    assert stock.grid is not None
    assert stock.grid.ndim == 2

    # 초기 Z 높이는 max Z (0.0)이어야 함
    h = stock.get_height_at(0.0, 0.0)
    assert h == pytest.approx(0.0, abs=0.1)


def test_stock_bounds():
    """소재 경계 반환 테스트"""
    min_c = np.array([-50.0, -50.0, -25.0])
    max_c = np.array([50.0, 50.0, 0.0])
    stock = StockModel(min_c, max_c, resolution=5.0)

    bounds_min, bounds_max = stock.get_stock_bounds()
    assert bounds_max[2] == pytest.approx(0.0, abs=0.1)


def test_stock_height_outside():
    """소재 범위 외부의 높이 조회 테스트"""
    stock = StockModel(
        np.array([-50.0, -50.0, -25.0]),
        np.array([50.0, 50.0, 0.0]),
        resolution=5.0
    )
    # 소재 외부 위치는 최소 Z를 반환해야 함
    h = stock.get_height_at(200.0, 200.0)
    assert h == pytest.approx(-25.0, abs=0.1)


def test_material_removal():
    """재료 제거 테스트"""
    stock = StockModel(
        np.array([-50.0, -50.0, -25.0]),
        np.array([50.0, 50.0, 0.0]),
        resolution=2.0
    )
    tool = make_test_tool(diameter=10.0)

    start = np.array([0.0, 0.0, -10.0])
    end = np.array([20.0, 0.0, -10.0])
    stock.remove_material(start, end, tool)

    # 공구 경로 위의 Z 높이가 -10.0 이하여야 함
    h_after = stock.get_height_at(10.0, 0.0)
    assert h_after <= -10.0 + 0.5  # 약간의 여유 허용


def test_material_removal_width():
    """재료 제거 너비가 공구 반경을 포함하는지 테스트"""
    stock = StockModel(
        np.array([-50.0, -50.0, -25.0]),
        np.array([50.0, 50.0, 0.0]),
        resolution=1.0
    )
    tool = make_test_tool(diameter=10.0)  # 반경 5mm

    # X 방향 직선 이동
    start = np.array([0.0, 0.0, -5.0])
    end = np.array([30.0, 0.0, -5.0])
    stock.remove_material(start, end, tool)

    # 공구 중심에서 반경 이내는 재료가 제거되어야 함
    h_center = stock.get_height_at(15.0, 0.0)
    assert h_center <= -5.0 + 0.5

    # 공구 반경보다 많이 벗어난 위치는 제거되지 않아야 함
    h_far = stock.get_height_at(15.0, 20.0)  # Y=20 (반경 5mm 초과)
    assert h_far == pytest.approx(0.0, abs=0.5)


def test_material_removal_vertical():
    """수직 이동(Z 플런지)에 대한 재료 제거 테스트"""
    stock = StockModel(
        np.array([-50.0, -50.0, -25.0]),
        np.array([50.0, 50.0, 0.0]),
        resolution=2.0
    )
    tool = make_test_tool(diameter=8.0)

    # 순수 Z 방향 이동 (플런지)
    start = np.array([0.0, 0.0, 0.0])
    end = np.array([0.0, 0.0, -15.0])
    stock.remove_material(start, end, tool)

    # 공구 아래 재료가 제거되어야 함
    h = stock.get_height_at(0.0, 0.0)
    assert h <= -15.0 + 0.5


def test_stock_reset():
    """소재 모델 리셋 테스트"""
    stock = StockModel(
        np.array([-50.0, -50.0, -25.0]),
        np.array([50.0, 50.0, 0.0]),
        resolution=5.0
    )
    tool = make_test_tool()

    # 재료 제거 후 리셋
    stock.remove_material(
        np.array([0.0, 0.0, -10.0]),
        np.array([20.0, 0.0, -10.0]),
        tool
    )
    stock.reset()

    # 리셋 후 초기 높이로 복원되어야 함
    h = stock.get_height_at(10.0, 0.0)
    assert h == pytest.approx(0.0, abs=0.1)


def test_stock_to_mesh_data():
    """Z-맵에서 메시 데이터 생성 테스트"""
    stock = StockModel(
        np.array([-10.0, -10.0, -5.0]),
        np.array([10.0, 10.0, 0.0]),
        resolution=5.0
    )

    vertices, faces = stock.to_mesh_data()

    # 꼭짓점과 면이 생성되어야 함
    assert vertices.shape[1] == 3  # [x, y, z]
    assert faces.shape[1] == 3     # 삼각형 (3개 인덱스)
    assert len(vertices) > 0
    assert len(faces) > 0


def test_tool_geometry_cylinder():
    """공구 절삭 원통 형상 테스트"""
    tool = make_test_tool(diameter=10.0)
    cylinder = ToolGeometry.get_cutting_cylinder(tool)

    assert cylinder['radius'] == pytest.approx(5.0)
    assert cylinder['height'] == pytest.approx(25.0)
    assert cylinder['type'] == ToolType.END_MILL


def test_tool_geometry_swept_volume():
    """공구 스윕 볼륨 경계 박스 테스트"""
    tool = make_test_tool(diameter=10.0)
    start = np.array([0.0, 0.0, -5.0])
    end = np.array([20.0, 0.0, -5.0])

    min_c, max_c = ToolGeometry.get_swept_volume_bbox(start, end, tool)

    # 경계 박스는 공구 반경만큼 확장되어야 함
    assert min_c[0] <= start[0] - tool.radius
    assert max_c[0] >= end[0] + tool.radius
    assert min_c[1] <= -tool.radius
    assert max_c[1] >= tool.radius


def test_material_removal_simulator():
    """재료 제거 시뮬레이터 통합 테스트"""
    from app.geometry.material_removal import MaterialRemovalSimulator
    from app.parser.gcode_parser import GCodeParser

    code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5.0
G1 Z-5.0 F200
G1 X20.0 F800
G0 Z5.0
M5 M30
"""

    parser = GCodeParser()
    tp = parser.parse_string(code)

    stock = StockModel(
        np.array([-30.0, -30.0, -20.0]),
        np.array([30.0, 30.0, 0.0]),
        resolution=2.0
    )

    tool = make_test_tool(diameter=10.0)
    tools = {1: tool}

    simulator = MaterialRemovalSimulator()
    result_stock = simulator.simulate(tp, stock, tools)

    # 결과 소재가 반환되어야 함
    assert result_stock is not None

    # 가공 경로에서 재료가 제거되어야 함
    h = result_stock.get_height_at(10.0, 0.0)
    assert h <= -5.0 + 1.0
