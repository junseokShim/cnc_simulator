"""
소재 설정 패널 모듈

사용자가 소재 크기와 원점을 직접 바꾸고,
즉시 시뮬레이션 스톡 경계에 반영할 수 있게 해줍니다.
"""
from __future__ import annotations

from typing import Dict

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models.project import (
    compute_stock_bounds_from_origin,
    compute_stock_origin_from_bounds,
    normalize_stock_origin_mode,
)


class StockSettingsPanel(QWidget):
    """소재 크기/원점 설정 패널"""

    apply_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(6)

        group = QGroupBox("소재 설정")
        form = QFormLayout(group)
        form.setSpacing(4)

        self._origin_mode_combo = QComboBox()
        self._origin_mode_combo.addItem("상면 중심", "top_center")
        self._origin_mode_combo.addItem("상면 최소 코너", "top_min_corner")
        self._origin_mode_combo.addItem("바닥 중심", "bottom_center")
        self._origin_mode_combo.addItem("바닥 최소 코너", "bottom_min_corner")
        self._origin_mode_combo.addItem("소재 중심", "center")

        self._origin_x = self._make_spinbox(-5000.0, 5000.0, 0.0, 0.1)
        self._origin_y = self._make_spinbox(-5000.0, 5000.0, 0.0, 0.1)
        self._origin_z = self._make_spinbox(-5000.0, 5000.0, 0.0, 0.1)

        self._size_x = self._make_spinbox(1.0, 5000.0, 120.0, 0.5)
        self._size_y = self._make_spinbox(1.0, 5000.0, 120.0, 0.5)
        self._size_z = self._make_spinbox(0.1, 2000.0, 30.0, 0.5)
        self._resolution = self._make_spinbox(0.1, 20.0, 2.0, 0.1)

        form.addRow("원점 기준:", self._origin_mode_combo)
        form.addRow("원점 X:", self._origin_x)
        form.addRow("원점 Y:", self._origin_y)
        form.addRow("원점 Z:", self._origin_z)
        form.addRow("크기 X:", self._size_x)
        form.addRow("크기 Y:", self._size_y)
        form.addRow("크기 Z:", self._size_z)
        form.addRow("격자 해상도:", self._resolution)

        self._preview_label = QLabel("-")
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(
            "QLabel { font-family: monospace; font-size: 11px; color: #cccccc; "
            "background: #1a1a1a; padding: 5px; border-radius: 3px; }"
        )
        form.addRow("계산된 범위:", self._preview_label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        self._apply_button = QPushButton("소재 적용")
        button_row.addWidget(self._apply_button)

        main_layout.addWidget(group)
        main_layout.addLayout(button_row)

        self._origin_mode_combo.currentIndexChanged.connect(self._update_preview)
        for widget in (
            self._origin_x,
            self._origin_y,
            self._origin_z,
            self._size_x,
            self._size_y,
            self._size_z,
            self._resolution,
        ):
            widget.valueChanged.connect(self._update_preview)

        self._apply_button.clicked.connect(self._emit_apply_requested)
        self._update_preview()

    def _make_spinbox(
        self,
        minimum: float,
        maximum: float,
        value: float,
        step: float,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(3 if step < 0.5 else 2)
        spin.setSingleStep(step)
        spin.setValue(value)
        spin.setSuffix(" mm")
        return spin

    def set_stock_config(
        self,
        stock_min: np.ndarray,
        stock_max: np.ndarray,
        resolution: float,
        origin_mode: str = "top_center",
    ):
        """현재 소재 설정을 패널에 반영합니다."""

        normalized_mode = normalize_stock_origin_mode(origin_mode)
        origin = compute_stock_origin_from_bounds(stock_min, stock_max, normalized_mode)
        size = np.asarray(stock_max, dtype=float) - np.asarray(stock_min, dtype=float)

        combo_index = self._origin_mode_combo.findData(normalized_mode)
        if combo_index >= 0:
            self._origin_mode_combo.setCurrentIndex(combo_index)

        self._origin_x.setValue(float(origin[0]))
        self._origin_y.setValue(float(origin[1]))
        self._origin_z.setValue(float(origin[2]))
        self._size_x.setValue(float(size[0]))
        self._size_y.setValue(float(size[1]))
        self._size_z.setValue(float(size[2]))
        self._resolution.setValue(float(resolution))
        self._update_preview()

    def get_stock_settings(self) -> Dict:
        """패널의 현재 입력값을 공통 설정 딕셔너리로 반환합니다."""

        origin_mode = normalize_stock_origin_mode(self._origin_mode_combo.currentData())
        origin = np.array(
            [
                self._origin_x.value(),
                self._origin_y.value(),
                self._origin_z.value(),
            ],
            dtype=float,
        )
        size = np.array(
            [
                self._size_x.value(),
                self._size_y.value(),
                self._size_z.value(),
            ],
            dtype=float,
        )
        stock_min, stock_max = compute_stock_bounds_from_origin(origin, size, origin_mode)

        return {
            "origin_mode": origin_mode,
            "origin": origin,
            "size": size,
            "min": stock_min,
            "max": stock_max,
            "resolution": float(self._resolution.value()),
        }

    def _update_preview(self):
        """입력값으로 계산한 stock 범위를 미리 보여줍니다."""

        try:
            settings = self.get_stock_settings()
        except ValueError as exc:
            self._preview_label.setText(f"입력 오류: {exc}")
            return

        stock_min = settings["min"]
        stock_max = settings["max"]
        self._preview_label.setText(
            f"min = [{stock_min[0]:.2f}, {stock_min[1]:.2f}, {stock_min[2]:.2f}]\n"
            f"max = [{stock_max[0]:.2f}, {stock_max[1]:.2f}, {stock_max[2]:.2f}]\n"
            f"resolution = {settings['resolution']:.2f} mm"
        )

    def _emit_apply_requested(self):
        """사용자가 적용 버튼을 누르면 현재 설정을 전달합니다."""

        self.apply_requested.emit(self.get_stock_settings())
