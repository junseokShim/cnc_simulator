"""
공구 라이브러리 편집 패널

앱 내부에서 T코드 공구 정의를 직접 편집하고,
직경 입력값과 내부 반경 계산값을 함께 확인할 수 있습니다.
"""
from __future__ import annotations

from typing import Dict, Iterable, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.models.tool import Tool


class ToolLibraryPanel(QWidget):
    """T코드 공구 라이브러리를 목록 + 폼 형태로 편집하는 패널"""

    apply_requested = Signal(object)
    save_requested = Signal(object)

    _KNOWN_TYPES = ("EM", "REM", "DR", "BALL", "FACE", "TAP", "CUSTOM")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[dict] = []
        self._current_index: int = -1
        self._loading: bool = False
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(6)

        source_group = QGroupBox("공구 라이브러리")
        source_layout = QVBoxLayout(source_group)
        source_layout.setContentsMargins(8, 8, 8, 8)
        source_layout.setSpacing(6)

        self._source_label = QLabel("저장 대상: -")
        self._source_label.setWordWrap(True)
        self._source_label.setStyleSheet(
            "QLabel { font-size: 11px; color: #d0d0d0; background: #1a1a1a; "
            "padding: 5px 6px; border-radius: 3px; }"
        )
        source_layout.addWidget(self._source_label)

        self._summary_label = QLabel("공구 정의 없음")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(
            "QLabel { font-size: 11px; color: #9bd3ff; background: #132330; "
            "padding: 5px 6px; border-radius: 3px; }"
        )
        source_layout.addWidget(self._summary_label)

        self._tool_list = QListWidget()
        self._tool_list.setMinimumHeight(140)
        self._tool_list.currentRowChanged.connect(self._on_row_changed)
        source_layout.addWidget(self._tool_list)

        list_button_row = QHBoxLayout()
        self._add_button = QPushButton("추가")
        self._delete_button = QPushButton("삭제")
        list_button_row.addWidget(self._add_button)
        list_button_row.addWidget(self._delete_button)
        source_layout.addLayout(list_button_row)

        self._add_button.clicked.connect(self._add_tool_row)
        self._delete_button.clicked.connect(self._delete_current_row)

        main_layout.addWidget(source_group)

        editor_group = QGroupBox("선택 공구 편집")
        editor_form = QFormLayout(editor_group)
        editor_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        editor_form.setSpacing(4)

        self._tool_number_spin = self._make_spinbox(1, 999, 1)
        self._diameter_spin = self._make_double_spinbox(0.1, 500.0, 10.0, 0.1, " mm")
        self._radius_label = self._make_value_label("5.000 mm")
        self._tool_type_combo = QComboBox()
        self._tool_type_combo.setEditable(True)
        self._tool_type_combo.addItems(list(self._KNOWN_TYPES))
        self._flute_count_spin = self._make_spinbox(0, 24, 4)
        self._overhang_spin = self._make_double_spinbox(0.0, 500.0, 50.0, 0.5, " mm")
        self._length_spin = self._make_double_spinbox(0.0, 500.0, 80.0, 0.5, " mm")
        self._rigidity_spin = self._make_double_spinbox(0.15, 5.0, 1.0, 0.01, "")
        self._kc_spin = self._make_double_spinbox(0.15, 5.0, 1.0, 0.01, "")
        self._notes_edit = QLineEdit()

        editor_form.addRow("공구 번호:", self._tool_number_spin)
        editor_form.addRow("직경(mm):", self._diameter_spin)
        editor_form.addRow("내부 반경:", self._radius_label)
        editor_form.addRow("공구 타입:", self._tool_type_combo)
        editor_form.addRow("날 수:", self._flute_count_spin)
        editor_form.addRow("오버행:", self._overhang_spin)
        editor_form.addRow("총 길이:", self._length_spin)
        editor_form.addRow("강성 보정:", self._rigidity_spin)
        editor_form.addRow("KC 보정:", self._kc_spin)
        editor_form.addRow("비고:", self._notes_edit)

        self._detail_label = QLabel("입력값은 직경 기준이며 내부 반경은 직경/2로 계산됩니다.")
        self._detail_label.setWordWrap(True)
        self._detail_label.setStyleSheet(
            "QLabel { font-size: 11px; color: #cfcfcf; background: #1a1a1a; "
            "padding: 5px 6px; border-radius: 3px; }"
        )
        editor_form.addRow("디버그:", self._detail_label)

        main_layout.addWidget(editor_group)

        action_row = QHBoxLayout()
        self._apply_button = QPushButton("적용")
        self._save_button = QPushButton("저장")
        action_row.addStretch()
        action_row.addWidget(self._apply_button)
        action_row.addWidget(self._save_button)
        main_layout.addLayout(action_row)

        self._apply_button.clicked.connect(self._emit_apply_requested)
        self._save_button.clicked.connect(self._emit_save_requested)

        for widget in (
            self._tool_number_spin,
            self._diameter_spin,
            self._flute_count_spin,
            self._overhang_spin,
            self._length_spin,
            self._rigidity_spin,
            self._kc_spin,
        ):
            widget.valueChanged.connect(self._on_form_changed)
        self._tool_type_combo.currentTextChanged.connect(self._on_form_changed)
        self._notes_edit.textChanged.connect(self._on_form_changed)

        self.set_tools([])

    def _make_spinbox(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        widget = QSpinBox()
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        return widget

    def _make_double_spinbox(
        self,
        minimum: float,
        maximum: float,
        value: float,
        step: float,
        suffix: str,
    ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(3 if step < 0.1 else 2)
        widget.setSingleStep(step)
        widget.setValue(value)
        if suffix:
            widget.setSuffix(suffix)
        return widget

    def _make_value_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            "QLabel { font-family: monospace; font-size: 12px; color: #00ddff; "
            "background: #1a1a1a; padding: 2px 6px; border-radius: 2px; }"
        )
        return label

    def set_tools(self, tools: Iterable[Tool], source_label: str = ""):
        """외부 공구 목록을 패널에 반영합니다."""

        self._loading = True
        self._rows = [self._tool_to_row(tool) for tool in sorted(tools, key=lambda item: item.tool_number)]
        if not self._rows:
            self._rows = [self._build_default_row(1)]

        self._tool_list.clear()
        for row in self._rows:
            self._tool_list.addItem(self._format_row_text(row))

        self._source_label.setText(source_label or "저장 대상: -")
        self._loading = False
        self._current_index = -1
        self._tool_list.setCurrentRow(0)
        self._refresh_summary()

    def _tool_to_row(self, tool: Tool) -> dict:
        return {
            "tool_number": int(tool.tool_number),
            "diameter_mm": float(tool.diameter_mm),
            "tool_type": str(tool.tool_category or tool.tool_type.value),
            "flute_count": int(tool.flute_count),
            "overhang_mm": float(tool.overhang_mm),
            "length_mm": float(tool.length),
            "rigidity_factor": float(tool.rigidity_factor),
            "cutting_coefficient_factor": float(tool.cutting_coefficient_factor),
            "notes": str(tool.notes or ""),
        }

    def _build_default_row(self, tool_number: int) -> dict:
        return {
            "tool_number": int(tool_number),
            "diameter_mm": 10.0,
            "tool_type": "EM",
            "flute_count": 4,
            "overhang_mm": 50.0,
            "length_mm": 80.0,
            "rigidity_factor": 1.0,
            "cutting_coefficient_factor": 1.0,
            "notes": "",
        }

    def _format_row_text(self, row: dict) -> str:
        diameter_mm = float(row.get("diameter_mm", 0.0))
        radius_mm = diameter_mm / 2.0
        flute_count = int(row.get("flute_count", 0))
        flute_text = f" | {flute_count}F" if flute_count > 0 else ""
        return (
            f"T{int(row.get('tool_number', 0))} | "
            f"{diameter_mm:.3f} mm {str(row.get('tool_type', 'EM')).upper()} | "
            f"R{radius_mm:.3f}{flute_text}"
        )

    def _on_row_changed(self, new_index: int):
        if self._loading:
            return

        previous_index = self._current_index
        self._persist_row(previous_index)
        self._current_index = new_index
        self._load_row(new_index)

    def _persist_row(self, index: int):
        if self._loading or index < 0 or index >= len(self._rows):
            return

        self._rows[index] = {
            "tool_number": int(self._tool_number_spin.value()),
            "diameter_mm": float(self._diameter_spin.value()),
            "tool_type": self._tool_type_combo.currentText().strip().upper(),
            "flute_count": int(self._flute_count_spin.value()),
            "overhang_mm": float(self._overhang_spin.value()),
            "length_mm": float(self._length_spin.value()),
            "rigidity_factor": float(self._rigidity_spin.value()),
            "cutting_coefficient_factor": float(self._kc_spin.value()),
            "notes": self._notes_edit.text().strip(),
        }

        item = self._tool_list.item(index)
        if item is not None:
            item.setText(self._format_row_text(self._rows[index]))
        self._update_radius_preview()
        self._refresh_summary()

    def _load_row(self, index: int):
        if index < 0 or index >= len(self._rows):
            return

        row = self._rows[index]
        self._loading = True
        self._tool_number_spin.setValue(int(row.get("tool_number", 1)))
        self._diameter_spin.setValue(float(row.get("diameter_mm", 10.0)))
        self._tool_type_combo.setCurrentText(str(row.get("tool_type", "EM")).upper())
        self._flute_count_spin.setValue(int(row.get("flute_count", 0)))
        self._overhang_spin.setValue(float(row.get("overhang_mm", 0.0)))
        self._length_spin.setValue(float(row.get("length_mm", 0.0)))
        self._rigidity_spin.setValue(float(row.get("rigidity_factor", 1.0)))
        self._kc_spin.setValue(float(row.get("cutting_coefficient_factor", 1.0)))
        self._notes_edit.setText(str(row.get("notes", "")))
        self._loading = False
        self._update_radius_preview()

    def _update_radius_preview(self):
        diameter_mm = float(self._diameter_spin.value())
        radius_mm = diameter_mm / 2.0
        tool_type = self._tool_type_combo.currentText().strip().upper() or "EM"

        self._radius_label.setText(f"{radius_mm:.3f} mm")
        self._detail_label.setText(
            f"입력 직경 {diameter_mm:.3f} mm -> 내부 반경 {radius_mm:.3f} mm\n"
            f"T{self._tool_number_spin.value()}는 {tool_type} 타입으로 매핑됩니다."
        )

    def _refresh_summary(self):
        tool_count = len(self._rows)
        type_list = ", ".join(sorted({str(row.get("tool_type", "EM")).upper() for row in self._rows}))
        self._summary_label.setText(
            f"공구 {tool_count}개 | 직경 입력 기준 | 내부 반경 = 직경 / 2 | 타입: {type_list}"
        )

    def _on_form_changed(self):
        if self._loading:
            return
        self._persist_row(self._current_index)

    def _add_tool_row(self):
        self._persist_row(self._current_index)
        next_tool_number = 1
        if self._rows:
            next_tool_number = max(int(row.get("tool_number", 0)) for row in self._rows) + 1

        self._rows.append(self._build_default_row(next_tool_number))
        self._tool_list.addItem(self._format_row_text(self._rows[-1]))
        self._tool_list.setCurrentRow(len(self._rows) - 1)
        self._refresh_summary()

    def _delete_current_row(self):
        if not self._rows:
            return

        index = self._tool_list.currentRow()
        if index < 0:
            index = len(self._rows) - 1

        del self._rows[index]
        if not self._rows:
            self._rows.append(self._build_default_row(1))

        self._loading = True
        self._tool_list.clear()
        for row in self._rows:
            self._tool_list.addItem(self._format_row_text(row))
        self._loading = False

        new_index = min(index, len(self._rows) - 1)
        self._current_index = -1
        self._tool_list.setCurrentRow(new_index)
        self._refresh_summary()

    def build_tools(self) -> tuple[Dict[int, Tool], List[str]]:
        """패널 입력값을 검증한 뒤 `Tool` 사전으로 변환합니다."""

        self._persist_row(self._current_index)

        errors: List[str] = []
        warnings: List[str] = []
        tools: Dict[int, Tool] = {}
        used_numbers = set()

        for row in self._rows:
            tool_number = int(row.get("tool_number", 0))
            diameter_mm = float(row.get("diameter_mm", 0.0))
            tool_type = str(row.get("tool_type", "")).strip().upper()

            if tool_number <= 0:
                errors.append("공구 번호는 1 이상의 정수여야 합니다.")
                continue
            if tool_number in used_numbers:
                errors.append(f"T{tool_number}가 중복 정의되었습니다.")
                continue
            if diameter_mm <= 0.0:
                errors.append(f"T{tool_number} 직경은 0보다 커야 합니다.")
                continue
            if not tool_type:
                errors.append(f"T{tool_number} 공구 타입이 비어 있습니다.")
                continue

            used_numbers.add(tool_number)

            if tool_type not in self._KNOWN_TYPES:
                warnings.append(
                    f"T{tool_number} 타입 '{tool_type}'은 기본 분류에 없어서 사용자 정의(CUSTOM) 가정으로 처리됩니다."
                )

            tool_payload = {
                "tool_number": tool_number,
                "tool_type": tool_type,
                "tool_category": tool_type,
                "diameter_mm": diameter_mm,
                "length_mm": float(row.get("length_mm", 0.0)),
                "flute_count": int(row.get("flute_count", 0)),
                "overhang_mm": float(row.get("overhang_mm", 0.0)),
                "rigidity_factor": float(row.get("rigidity_factor", 1.0)),
                "cutting_coefficient_factor": float(row.get("cutting_coefficient_factor", 1.0)),
                "notes": str(row.get("notes", "")),
                "name": f"{diameter_mm:g}mm {tool_type}",
            }
            tools[tool_number] = Tool.from_dict(tool_payload)

        if errors:
            raise ValueError("\n".join(errors))

        return tools, warnings

    def _emit_apply_requested(self):
        try:
            tools, warnings = self.build_tools()
        except ValueError as exc:
            QMessageBox.warning(self, "공구 입력 오류", str(exc))
            return

        if warnings:
            QMessageBox.warning(self, "공구 타입 안내", "\n".join(warnings))

        self.apply_requested.emit(tools)

    def _emit_save_requested(self):
        try:
            tools, warnings = self.build_tools()
        except ValueError as exc:
            QMessageBox.warning(self, "공구 입력 오류", str(exc))
            return

        if warnings:
            QMessageBox.warning(self, "공구 타입 안내", "\n".join(warnings))

        self.save_requested.emit(tools)
