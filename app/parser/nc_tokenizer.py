"""
NC 코드 토크나이저 모듈
NC 코드의 단일 블록(라인)을 개별 토큰으로 분해합니다.
각 토큰은 어드레스 문자(예: G, X, Y, F)와 수치값으로 구성됩니다.
"""
import re
from dataclasses import dataclass
from typing import List, Optional
from app.utils.logger import get_logger

logger = get_logger("nc_tokenizer")


@dataclass
class NCToken:
    """
    NC 코드 토큰 데이터 클래스
    단일 어드레스-값 쌍을 나타냅니다. 예: G0, X10.5, F300
    """
    # 어드레스 문자 (G, X, Y, Z, F, S, T, M, I, J, K, N, R, P, Q 등)
    letter: str

    # 수치값 (예: G0이면 0, X10.5이면 10.5)
    value: float

    # 원본 문자열 (예: "X10.500", "G01")
    raw: str

    def __repr__(self) -> str:
        return f"NCToken({self.letter}{self.value})"


# NC 코드 토큰 정규식 패턴
# 어드레스 문자 후 선택적 부호와 숫자(소수점 포함)를 파싱
_TOKEN_PATTERN = re.compile(
    r'([A-Za-z])\s*([-+]?\s*\d+\.?\d*|\.\d+)',
    re.IGNORECASE
)

# 괄호 주석 제거 패턴 (중첩 괄호도 처리)
_PAREN_COMMENT_PATTERN = re.compile(r'\([^)]*\)')

# 세미콜론 이후 주석 패턴
_SEMICOLON_COMMENT_PATTERN = re.compile(r';.*$')


def tokenize_block(line: str) -> List[NCToken]:
    """
    단일 NC 블록 라인을 토큰 목록으로 분해합니다.

    처리 과정:
    1. 괄호 주석 제거 (예: "(이것은 주석)" 삭제)
    2. 세미콜론 이후 주석 제거
    3. 프로그램 시작/종료 기호 제거 (%, %)
    4. 라인 번호 (N코드) 유지하되 반환에서 제외
    5. 어드레스-값 쌍 추출

    Args:
        line: 파싱할 NC 코드 라인 문자열

    Returns:
        NCToken 목록 (라인 번호 N-코드는 제외)
    """
    if not line:
        return []

    # 프로그램 시작/종료 기호 제거
    stripped = line.strip()
    if stripped in ('%', '/'):
        return []

    # 괄호 주석 제거
    cleaned = _PAREN_COMMENT_PATTERN.sub('', stripped)

    # 세미콜론 이후 주석 제거
    cleaned = _SEMICOLON_COMMENT_PATTERN.sub('', cleaned)

    # 공백 정리
    cleaned = cleaned.strip()

    if not cleaned:
        return []

    # 토큰 파싱
    tokens: List[NCToken] = []
    for match in _TOKEN_PATTERN.finditer(cleaned):
        letter = match.group(1).upper()
        value_str = match.group(2).replace(' ', '')  # 부호와 숫자 사이 공백 제거

        try:
            value = float(value_str)
        except ValueError:
            logger.warning(f"토큰 값 파싱 실패: '{match.group(0)}'")
            continue

        raw = match.group(0).replace(' ', '')

        # N 코드(라인 번호)는 토큰에서 제외 (정보만 활용)
        if letter == 'N':
            continue

        tokens.append(NCToken(letter=letter, value=value, raw=raw))

    return tokens


def get_line_number(line: str) -> Optional[int]:
    """
    NC 코드 라인에서 블록 번호(N-코드)를 추출합니다.

    Args:
        line: NC 코드 라인

    Returns:
        블록 번호 (N-코드가 없으면 None)
    """
    match = re.match(r'^\s*[Nn](\d+)', line)
    if match:
        return int(match.group(1))
    return None


def extract_comment(line: str) -> str:
    """
    NC 코드 라인에서 괄호 주석을 추출합니다.

    Args:
        line: NC 코드 라인

    Returns:
        괄호 안의 주석 텍스트 (없으면 빈 문자열)
    """
    match = _PAREN_COMMENT_PATTERN.search(line)
    if match:
        # 괄호 제거하고 내부 텍스트만 반환
        return match.group(0)[1:-1].strip()
    return ""
