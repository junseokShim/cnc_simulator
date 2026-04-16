"""
수학 유틸리티 모듈
CNC 시뮬레이션에서 자주 사용하는 수학 함수들을 제공합니다.
벡터 연산, 거리 계산, 좌표 변환 등을 포함합니다.
"""
import numpy as np
from typing import Tuple, Optional


def distance_3d(p1: np.ndarray, p2: np.ndarray) -> float:
    """
    3차원 두 점 사이의 유클리드 거리를 계산합니다.

    Args:
        p1: 시작점 [x, y, z]
        p2: 끝점 [x, y, z]

    Returns:
        두 점 사이의 거리 (mm 단위)
    """
    return float(np.linalg.norm(p2 - p1))


def normalize_vector(v: np.ndarray) -> np.ndarray:
    """
    벡터를 단위 벡터로 정규화합니다.

    Args:
        v: 입력 벡터

    Returns:
        정규화된 단위 벡터 (길이가 0이면 원본 반환)
    """
    norm = np.linalg.norm(v)
    if norm < 1e-10:
        return v.copy()
    return v / norm


def arc_length(radius: float, angle_rad: float) -> float:
    """
    호의 길이를 계산합니다.

    Args:
        radius: 호의 반지름 (mm)
        angle_rad: 호의 중심각 (라디안)

    Returns:
        호의 길이 (mm)
    """
    return abs(radius * angle_rad)


def calc_arc_angle(start: np.ndarray, end: np.ndarray, center: np.ndarray,
                   clockwise: bool = True) -> float:
    """
    XY 평면에서 호의 각도를 계산합니다.

    Args:
        start: 시작점 [x, y, z]
        end: 끝점 [x, y, z]
        center: 호의 중심점 [x, y, z]
        clockwise: 시계방향 여부 (G2=True, G3=False)

    Returns:
        호의 각도 (라디안, 항상 양수)
    """
    # 중심에서 시작점과 끝점까지의 벡터 계산
    start_vec = start[:2] - center[:2]
    end_vec = end[:2] - center[:2]

    # 시작각도와 끝각도 계산
    start_angle = np.arctan2(start_vec[1], start_vec[0])
    end_angle = np.arctan2(end_vec[1], end_vec[0])

    if clockwise:
        # 시계방향: 시작각도에서 감소하여 끝각도까지
        angle = start_angle - end_angle
        if angle <= 0:
            angle += 2 * np.pi
    else:
        # 반시계방향: 시작각도에서 증가하여 끝각도까지
        angle = end_angle - start_angle
        if angle <= 0:
            angle += 2 * np.pi

    return angle


def point_in_box(point: np.ndarray, min_corner: np.ndarray, max_corner: np.ndarray) -> bool:
    """
    점이 축 정렬 경계 박스(AABB) 내부에 있는지 확인합니다.

    Args:
        point: 확인할 점 [x, y, z]
        min_corner: 박스의 최소 모서리
        max_corner: 박스의 최대 모서리

    Returns:
        점이 박스 내부에 있으면 True
    """
    return bool(np.all(point >= min_corner) and np.all(point <= max_corner))


def line_segment_bbox(p1: np.ndarray, p2: np.ndarray,
                      radius: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
    """
    선분의 경계 박스를 계산합니다. 반지름이 있으면 공구 반경을 고려합니다.

    Args:
        p1: 선분 시작점
        p2: 선분 끝점
        radius: 공구 반경 (기본값: 0)

    Returns:
        (min_corner, max_corner) 튜플
    """
    min_corner = np.minimum(p1, p2) - radius
    max_corner = np.maximum(p1, p2) + radius
    return min_corner, max_corner


def rotate_point_2d(point: np.ndarray, center: np.ndarray, angle_rad: float) -> np.ndarray:
    """
    2D 점을 중심점 기준으로 회전합니다.

    Args:
        point: 회전할 점 [x, y]
        center: 회전 중심 [x, y]
        angle_rad: 회전 각도 (라디안, 반시계방향 양수)

    Returns:
        회전된 점 [x, y]
    """
    cos_a = np.cos(angle_rad)
    sin_a = np.sin(angle_rad)

    # 중심 기준으로 이동 후 회전
    dx = point[0] - center[0]
    dy = point[1] - center[1]

    new_x = center[0] + dx * cos_a - dy * sin_a
    new_y = center[1] + dx * sin_a + dy * cos_a

    return np.array([new_x, new_y])


def clamp(value: float, min_val: float, max_val: float) -> float:
    """
    값을 지정된 범위로 제한합니다.

    Args:
        value: 제한할 값
        min_val: 최솟값
        max_val: 최댓값

    Returns:
        제한된 값
    """
    return max(min_val, min(max_val, value))


def lerp(a: float, b: float, t: float) -> float:
    """
    두 값 사이의 선형 보간을 수행합니다.

    Args:
        a: 시작 값
        b: 끝 값
        t: 보간 비율 (0.0 ~ 1.0)

    Returns:
        보간된 값
    """
    return a + (b - a) * clamp(t, 0.0, 1.0)
