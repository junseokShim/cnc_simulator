"""
소재 원점/크기 설정 테스트
"""
import numpy as np

from app.models.project import (
    ProjectConfig,
    compute_stock_bounds_from_origin,
    compute_stock_origin_from_bounds,
)


def test_compute_stock_bounds_from_top_center_origin():
    """상면 중심 원점에서 min/max가 올바르게 계산되어야 한다."""

    stock_min, stock_max = compute_stock_bounds_from_origin(
        origin=[10.0, -5.0, 0.0],
        size=[100.0, 40.0, 20.0],
        origin_mode="top_center",
    )

    assert np.allclose(stock_min, [-40.0, -25.0, -20.0])
    assert np.allclose(stock_max, [60.0, 15.0, 0.0])


def test_compute_stock_origin_from_bounds_round_trip():
    """min/max -> origin -> min/max 변환이 왕복 일관성을 유지해야 한다."""

    original_min = np.array([-60.0, -30.0, -25.0])
    original_max = np.array([60.0, 30.0, 5.0])

    origin = compute_stock_origin_from_bounds(original_min, original_max, "top_center")
    stock_min, stock_max = compute_stock_bounds_from_origin(origin, original_max - original_min, "top_center")

    assert np.allclose(origin, [0.0, 0.0, 5.0])
    assert np.allclose(stock_min, original_min)
    assert np.allclose(stock_max, original_max)


def test_project_config_to_dict_includes_origin_and_size():
    """프로젝트 저장 시 origin/size/origin_mode가 함께 기록되어야 한다."""

    config = ProjectConfig.create_default()
    config.set_stock_from_origin(origin=[5.0, 10.0, 0.0], size=[80.0, 60.0, 25.0], origin_mode="top_center")

    data = config.to_dict()

    assert data["stock"]["origin_mode"] == "top_center"
    assert data["stock"]["origin"] == [5.0, 10.0, 0.0]
    assert data["stock"]["size"] == [80.0, 60.0, 25.0]
    assert np.allclose(data["stock"]["min"], [-35.0, -20.0, -25.0])
    assert np.allclose(data["stock"]["max"], [45.0, 40.0, 0.0])
