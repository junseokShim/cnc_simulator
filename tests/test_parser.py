"""
G코드 파서 단위 테스트
NC 토크나이저와 G코드 파서의 정확성을 검증합니다.
"""
import pytest
import numpy as np
from app.parser.gcode_parser import GCodeParser
from app.parser.nc_tokenizer import tokenize_block
from app.models.toolpath import MotionType


def test_tokenize_basic():
    """기본 토크나이징: G0 X10.0 Y20.0 Z-5.0 파싱 테스트"""
    tokens = tokenize_block("G0 X10.0 Y20.0 Z-5.0")
    assert len(tokens) == 4
    assert tokens[0].letter == 'G'
    assert tokens[0].value == 0
    assert tokens[1].letter == 'X'
    assert tokens[1].value == 10.0
    assert tokens[2].letter == 'Y'
    assert tokens[2].value == 20.0
    assert tokens[3].letter == 'Z'
    assert tokens[3].value == -5.0


def test_tokenize_comment():
    """괄호 주석이 있는 토크나이징 테스트: 주석 내용은 제외되어야 함"""
    tokens = tokenize_block("G1 X10.0 (이것은 주석입니다) Y20.0")
    letters = [t.letter for t in tokens]
    assert 'G' in letters
    assert 'X' in letters
    assert 'Y' in letters
    # 주석 내용이 토큰에 포함되지 않아야 함
    assert len(tokens) == 3


def test_tokenize_line_number():
    """N 코드(라인 번호)는 토큰에서 제외되어야 함"""
    tokens = tokenize_block("N100 G1 X10.0 F500")
    letters = [t.letter for t in tokens]
    assert 'N' not in letters
    assert 'G' in letters
    assert 'X' in letters
    assert 'F' in letters


def test_tokenize_negative_value():
    """음수 값 파싱 테스트"""
    tokens = tokenize_block("G1 Z-15.5 F200")
    z_token = next(t for t in tokens if t.letter == 'Z')
    assert z_token.value == pytest.approx(-15.5)


def test_tokenize_semicolon_comment():
    """세미콜론 주석 제거 테스트"""
    tokens = tokenize_block("G0 X0 Y0 ; 이것은 세미콜론 주석")
    letters = [t.letter for t in tokens]
    assert 'G' in letters
    assert 'X' in letters
    # 세미콜론 이후 내용 제거 확인
    assert len([t for t in tokens if t.letter not in ['G', 'X', 'Y']]) == 0


def test_parse_rapid_move():
    """G0 급속 이동 파싱 테스트"""
    parser = GCodeParser()
    tp = parser.parse_string("G0 X10.0 Y20.0 Z-5.0")
    assert len(tp.segments) == 1
    assert tp.segments[0].motion_type == MotionType.RAPID
    assert tp.segments[0].end_pos[0] == pytest.approx(10.0)
    assert tp.segments[0].end_pos[1] == pytest.approx(20.0)
    assert tp.segments[0].end_pos[2] == pytest.approx(-5.0)


def test_parse_linear_feed():
    """G1 직선 이송 파싱 테스트"""
    parser = GCodeParser()
    tp = parser.parse_string("G1 X10.0 Y20.0 Z-5.0 F500")
    assert len(tp.segments) == 1
    assert tp.segments[0].motion_type == MotionType.LINEAR
    assert tp.segments[0].feedrate == 500.0
    assert tp.segments[0].end_pos[0] == pytest.approx(10.0)


def test_parse_toolchange():
    """공구 교환(T코드 + M6) 파싱 테스트"""
    parser = GCodeParser()
    tp = parser.parse_string("T1 M6")
    # 공구 교환 후 세그먼트에 공구 번호 반영
    assert tp.segments[0].tool_number == 1


def test_parse_multiline():
    """다중 라인 G코드 파싱 테스트"""
    code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5.0
G1 Z-5.0 F200
G1 X50.0 F800
G0 Z5.0
M5
M30
"""
    parser = GCodeParser()
    tp = parser.parse_string(code)
    # 최소 3개 이상의 이동 세그먼트가 있어야 함
    assert len(tp.segments) > 3
    # 총 이동 거리는 0보다 커야 함
    assert tp.total_distance > 0


def test_arc_parsing():
    """G2/G3 원호 이동 파싱 테스트"""
    parser = GCodeParser()
    tp = parser.parse_string("G17\nG2 X0 Y-40.0 I0 J40.0 F600")
    arcs = [s for s in tp.segments if s.motion_type == MotionType.ARC_CW]
    assert len(arcs) >= 1
    # 원호 중심과 반경이 설정되어야 함
    assert arcs[0].arc_center is not None
    assert arcs[0].arc_radius is not None
    assert arcs[0].arc_radius > 0


def test_incremental_mode():
    """G91 증분 좌표 모드 파싱 테스트"""
    parser = GCodeParser()
    tp = parser.parse_string("G91\nG1 X10.0 Y0 Z0 F500\nG1 X10.0 Y0 Z0 F500")
    assert len(tp.segments) == 2
    # 두 번째 세그먼트의 시작점은 첫 번째의 끝점이어야 함 (증분 누적)
    assert tp.segments[1].start_pos[0] == pytest.approx(10.0, abs=0.01)
    # 두 번째 세그먼트의 끝점은 X=20이어야 함
    assert tp.segments[1].end_pos[0] == pytest.approx(20.0, abs=0.01)


def test_modal_feedrate():
    """이송 속도가 다음 라인까지 모달로 유지되는지 테스트"""
    parser = GCodeParser()
    tp = parser.parse_string("G1 X10.0 F800\nG1 X20.0\nG1 X30.0")
    # F800이 후속 라인에도 적용되어야 함
    assert tp.segments[0].feedrate == pytest.approx(800.0)
    assert tp.segments[1].feedrate == pytest.approx(800.0)
    assert tp.segments[2].feedrate == pytest.approx(800.0)


def test_spindle_state():
    """주축 상태(M3/M5)가 세그먼트에 반영되는지 테스트"""
    parser = GCodeParser()
    tp = parser.parse_string("S3000 M3\nG1 X10.0 F500\nM5\nG0 X20.0")
    # M3 이후 세그먼트는 spindle_on=True
    cutting_segs = [s for s in tp.segments if s.motion_type == MotionType.LINEAR]
    if cutting_segs:
        assert cutting_segs[0].spindle_on == True

    # M5 이후 세그먼트는 spindle_on=False
    rapid_segs_after = [s for s in tp.segments if s.motion_type == MotionType.RAPID]
    if rapid_segs_after:
        assert rapid_segs_after[-1].spindle_on == False


def test_parse_file():
    """실제 NC 파일 파싱 테스트"""
    import os
    nc_file = os.path.join("examples", "simple_pocket.nc")
    if not os.path.exists(nc_file):
        pytest.skip("예제 파일 없음")

    parser = GCodeParser()
    tp = parser.parse_file(nc_file)
    assert len(tp.segments) > 10
    assert tp.total_distance > 0
    assert tp.cutting_distance > 0
