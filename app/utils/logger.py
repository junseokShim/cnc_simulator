"""
로깅 유틸리티 모듈
애플리케이션 전체에서 사용하는 구조화된 로깅 설정을 제공합니다.
콘솔과 파일(logs/app.log) 두 곳에 동시에 로그를 출력합니다.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def setup_logger(name: str = "cnc_simulator", log_level: int = logging.DEBUG) -> logging.Logger:
    """
    애플리케이션 로거를 설정하고 반환합니다.

    Args:
        name: 로거 이름 (기본값: cnc_simulator)
        log_level: 로그 레벨 (기본값: DEBUG)

    Returns:
        설정된 Logger 인스턴스
    """
    # 로거 인스턴스 생성
    logger = logging.getLogger(name)

    # 이미 핸들러가 설정된 경우 중복 설정 방지
    if logger.handlers:
        return logger

    logger.setLevel(log_level)

    # 로그 포맷 정의 - 시간, 레벨, 모듈명, 메시지 포함
    log_format = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s.%(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 콘솔 핸들러 설정 (INFO 이상만 출력하여 노이즈 감소)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    # 파일 핸들러 설정 - 로그 디렉토리가 없으면 생성
    log_dir = "logs"
    if not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            logger.warning(f"로그 디렉토리 생성 실패: {e}")
            return logger

    log_file_path = os.path.join(log_dir, "app.log")

    # 파일 로테이션 핸들러: 최대 5MB, 최대 3개 백업 파일 유지
    try:
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(log_format)
        logger.addHandler(file_handler)
    except (OSError, IOError) as e:
        logger.warning(f"파일 로그 핸들러 설정 실패: {e}")

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    모듈별 자식 로거를 반환합니다.

    Args:
        name: 로거 이름 (보통 __name__ 사용)

    Returns:
        해당 이름의 Logger 인스턴스
    """
    # 루트 로거가 설정되지 않은 경우 먼저 설정
    root_logger = logging.getLogger("cnc_simulator")
    if not root_logger.handlers:
        setup_logger()

    return logging.getLogger(f"cnc_simulator.{name}")
