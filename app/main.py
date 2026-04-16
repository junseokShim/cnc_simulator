"""
CNC 가공 시뮬레이션 및 NC 코드 검증 애플리케이션
메인 진입점

사용 방법:
  python -m app.main [옵션]
  python -m app.main --file examples/simple_pocket.nc
  python -m app.main --headless --file examples/simple_pocket.nc
"""
import sys
import argparse
from app.utils.logger import setup_logger


def main():
    """애플리케이션 진입점 함수"""
    # 로거 설정 (가장 먼저 설정)
    logger = setup_logger()
    logger.info("CNC 시뮬레이터 시작")
    logger.info(f"Python 버전: {sys.version}")

    # 명령행 인수 파싱
    parser = argparse.ArgumentParser(
        description='CNC NC 코드 시뮬레이터 - G코드 파싱, 시각화 및 검증',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예제:
  %(prog)s                                    # GUI 모드로 시작
  %(prog)s --file examples/simple_pocket.nc   # NC 파일과 함께 시작
  %(prog)s --project examples/example_project.yaml  # 프로젝트와 함께 시작
  %(prog)s --headless --file example.nc       # UI 없이 검증만 실행
        """
    )

    parser.add_argument(
        '--file', '-f',
        metavar='NC_FILE',
        help='로드할 NC 파일 경로 (.nc, .tap, .cnc 등)'
    )
    parser.add_argument(
        '--project', '-p',
        metavar='PROJECT_FILE',
        help='로드할 프로젝트 파일 경로 (.yaml)'
    )
    parser.add_argument(
        '--headless',
        action='store_true',
        help='UI 없이 검증만 실행하고 결과를 콘솔에 출력'
    )
    parser.add_argument(
        '--output', '-o',
        metavar='REPORT_FILE',
        help='헤드리스 모드에서 보고서를 저장할 파일 경로'
    )

    args = parser.parse_args()

    if args.headless:
        # 헤드리스 모드: UI 없이 검증만 실행
        run_headless(args, logger)
    else:
        # GUI 모드: PySide6 애플리케이션 실행
        run_gui(args, logger)


def run_gui(args, logger):
    """
    GUI 모드로 애플리케이션을 실행합니다.

    Args:
        args: 파싱된 명령행 인수
        logger: 로거 인스턴스
    """
    # PySide6 임포트를 여기서 수행 (헤드리스 모드에서는 불필요)
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        logger.error("PySide6를 찾을 수 없습니다. 'pip install PySide6'로 설치하세요.")
        sys.exit(1)

    from app.ui.main_window import MainWindow

    # Qt 애플리케이션 생성
    app = QApplication(sys.argv)
    app.setApplicationName("CNC Simulator")
    app.setApplicationVersion("0.1.0")
    app.setOrganizationName("OpenCNC")

    # 어두운 테마 스타일 적용
    app.setStyle("Fusion")
    _apply_dark_theme(app)

    # 메인 윈도우 생성 및 표시
    window = MainWindow()
    window.show()

    # 명령행에서 지정된 파일 로드
    if args.file:
        logger.info(f"지정된 NC 파일 로드: {args.file}")
        window.load_nc_file(args.file)
    elif args.project:
        logger.info(f"지정된 프로젝트 파일 로드: {args.project}")
        window.load_project(args.project)

    logger.info("GUI 시작 완료, 이벤트 루프 진입")
    exit_code = app.exec()
    logger.info(f"애플리케이션 종료 (코드: {exit_code})")
    sys.exit(exit_code)


def run_headless(args, logger):
    """
    UI 없이 NC 파일 검증만 실행합니다.

    Args:
        args: 파싱된 명령행 인수
        logger: 로거 인스턴스
    """
    if not args.file:
        print("오류: 헤드리스 모드에서는 --file 인수가 필요합니다")
        print("사용 예: python -m app.main --headless --file example.nc")
        sys.exit(1)

    import os
    if not os.path.exists(args.file):
        print(f"오류: 파일을 찾을 수 없습니다: {args.file}")
        sys.exit(1)

    from app.parser.gcode_parser import GCodeParser
    from app.verification.checker import VerificationChecker
    from app.services.report_service import ReportService
    from app.models.machine import create_default_machine
    import numpy as np

    print("=" * 60)
    print("CNC NC 코드 검증 (헤드리스 모드)")
    print("=" * 60)

    # G-코드 파싱
    print(f"\n[1/3] NC 파일 파싱: {args.file}")
    parser = GCodeParser()
    toolpath = parser.parse_file(args.file)

    print(f"      파싱 완료: {len(toolpath.segments)}개 세그먼트")
    print(f"      총 이동 거리: {toolpath.total_distance:.1f} mm")
    print(f"      절삭 거리: {toolpath.cutting_distance:.1f} mm")
    print(f"      파싱 경고: {len(toolpath.warnings)}개")

    # 검증 실행
    print("\n[2/3] NC 코드 검증 중...")

    # 기본 머신과 소재 설정 사용
    from app.geometry.stock_model import StockModel
    machine = create_default_machine()
    stock = StockModel(
        np.array([-60.0, -60.0, -30.0]),
        np.array([60.0, 60.0, 0.0]),
        resolution=5.0
    )

    checker = VerificationChecker()
    warnings = checker.run_all_checks(toolpath, stock, machine, {})

    error_count = sum(1 for w in warnings if w.severity == "ERROR")
    warning_count = sum(1 for w in warnings if w.severity == "WARNING")
    info_count = sum(1 for w in warnings if w.severity == "INFO")

    print(f"      검증 완료: 오류 {error_count}개, 경고 {warning_count}개, 정보 {info_count}개")

    # 경고 목록 출력
    if warnings:
        print("\n발견된 문제:")
        for w in warnings:
            print(f"  [{w.severity:7s}] 라인 {w.line_number:5d} | {w.code}")
            print(f"    → {w.message}")

    # 보고서 생성 및 저장
    if args.output:
        print(f"\n[3/3] 보고서 생성: {args.output}")
        report_service = ReportService()
        report = report_service.generate_report(toolpath, warnings, machine, {})
        report_service.save_report(report, args.output)
        print(f"      보고서 저장 완료")
    else:
        print("\n[3/3] 보고서 생성 건너뜀 (--output 옵션으로 저장 가능)")

    print("\n" + "=" * 60)
    if error_count > 0:
        print(f"결과: 오류 {error_count}개 발견 - NC 코드 수정 필요")
        sys.exit(1)
    elif warning_count > 0:
        print(f"결과: 경고 {warning_count}개 - 검토 권장")
        sys.exit(0)
    else:
        print("결과: 정상 - 검증 통과")
        sys.exit(0)


def _apply_dark_theme(app):
    """
    Qt 애플리케이션에 어두운 테마를 적용합니다.

    Args:
        app: QApplication 인스턴스
    """
    from PySide6.QtGui import QPalette, QColor

    palette = QPalette()

    # 어두운 배경색 설정
    dark_bg = QColor(35, 35, 38)
    mid_bg = QColor(45, 45, 48)
    light_bg = QColor(60, 60, 65)
    text_color = QColor(220, 220, 220)
    highlight_color = QColor(42, 130, 218)

    palette.setColor(QPalette.ColorRole.Window, dark_bg)
    palette.setColor(QPalette.ColorRole.WindowText, text_color)
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 28))
    palette.setColor(QPalette.ColorRole.AlternateBase, mid_bg)
    palette.setColor(QPalette.ColorRole.ToolTipBase, mid_bg)
    palette.setColor(QPalette.ColorRole.ToolTipText, text_color)
    palette.setColor(QPalette.ColorRole.Text, text_color)
    palette.setColor(QPalette.ColorRole.Button, mid_bg)
    palette.setColor(QPalette.ColorRole.ButtonText, text_color)
    palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Link, highlight_color)
    palette.setColor(QPalette.ColorRole.Highlight, highlight_color)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))

    app.setPalette(palette)


if __name__ == "__main__":
    main()
