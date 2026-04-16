"""
보고서 다이얼로그(Report Dialog) 모듈
NC 코드 검증 보고서를 표시하고 파일로 저장하는 다이얼로그입니다.
"""
from __future__ import annotations
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QFileDialog, QLabel, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from app.utils.logger import get_logger

logger = get_logger("report_dialog")


class ReportDialog(QDialog):
    """
    검증 보고서 표시 다이얼로그

    생성된 텍스트 보고서를 읽기 전용 텍스트 에디터로 표시합니다.
    보고서를 텍스트 파일로 저장하는 기능도 제공합니다.
    """

    def __init__(self, report_text: str = "", parent=None):
        """
        Args:
            report_text: 표시할 보고서 텍스트
            parent: 부모 위젯
        """
        super().__init__(parent)

        self._report_text = report_text

        self.setWindowTitle("NC 코드 검증 보고서")
        self.setMinimumSize(750, 600)
        self.resize(800, 650)

        self._setup_ui()

        if report_text:
            self._text_edit.setPlainText(report_text)

    def _setup_ui(self):
        """UI 레이아웃을 설정합니다."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # 헤더 레이블
        header_label = QLabel("CNC NC 코드 검증 보고서")
        header_label.setStyleSheet(
            "QLabel { font-size: 14px; font-weight: bold; "
            "color: #ffffff; padding: 4px; }"
        )
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header_label)

        # 보고서 텍스트 에디터 (읽기 전용)
        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont(QFont("Courier New", 10))
        self._text_edit.setStyleSheet(
            "QTextEdit { "
            "background-color: #1a1a1a; "
            "color: #e0e0e0; "
            "border: 1px solid #444; "
            "border-radius: 4px; "
            "padding: 8px; "
            "}"
        )
        main_layout.addWidget(self._text_edit)

        # 버튼 행
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        # 저장 버튼
        save_btn = QPushButton("📄 보고서 저장")
        save_btn.setToolTip("보고서를 텍스트 파일로 저장합니다")
        save_btn.setMinimumWidth(120)
        save_btn.clicked.connect(self._save_report)
        save_btn.setStyleSheet(self._button_style("#2a5080"))

        # 복사 버튼
        copy_btn = QPushButton("📋 클립보드 복사")
        copy_btn.setToolTip("보고서 내용을 클립보드에 복사합니다")
        copy_btn.setMinimumWidth(120)
        copy_btn.clicked.connect(self._copy_to_clipboard)
        copy_btn.setStyleSheet(self._button_style("#2a5040"))

        # 닫기 버튼
        close_btn = QPushButton("✕ 닫기")
        close_btn.setMinimumWidth(80)
        close_btn.clicked.connect(self.accept)
        close_btn.setStyleSheet(self._button_style("#502020"))

        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(copy_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)

        main_layout.addLayout(btn_layout)

    def _button_style(self, bg_color: str) -> str:
        """버튼 스타일 문자열을 반환합니다."""
        return (
            f"QPushButton {{ "
            f"background-color: {bg_color}; "
            f"color: #ffffff; "
            f"border: 1px solid #666; "
            f"border-radius: 4px; "
            f"padding: 6px 12px; "
            f"font-size: 12px; "
            f"}} "
            f"QPushButton:hover {{ "
            f"border-color: #aaa; "
            f"}} "
            f"QPushButton:pressed {{ "
            f"background-color: #111; "
            f"}}"
        )

    def _save_report(self):
        """보고서를 텍스트 파일로 저장합니다."""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "보고서 저장",
            "nc_verification_report.txt",
            "텍스트 파일 (*.txt);;모든 파일 (*)"
        )

        if not file_path:
            return

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(self._text_edit.toPlainText())

            logger.info(f"보고서 저장 완료: {file_path}")
            QMessageBox.information(
                self, "저장 완료",
                f"보고서가 저장되었습니다:\n{file_path}"
            )
        except (OSError, IOError) as e:
            logger.error(f"보고서 저장 실패: {e}")
            QMessageBox.critical(
                self, "저장 오류",
                f"보고서 저장 중 오류가 발생했습니다:\n{str(e)}"
            )

    def _copy_to_clipboard(self):
        """보고서 내용을 클립보드에 복사합니다."""
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(self._text_edit.toPlainText())

        # 간단한 완료 메시지 표시
        QMessageBox.information(
            self, "복사 완료",
            "보고서 내용이 클립보드에 복사되었습니다."
        )

    def set_report(self, report_text: str):
        """
        표시할 보고서 텍스트를 설정합니다.

        Args:
            report_text: 새 보고서 텍스트
        """
        self._report_text = report_text
        self._text_edit.setPlainText(report_text)
