"""
보고서/CSV 저장 서비스 테스트
"""
import csv
import shutil
from pathlib import Path
from uuid import uuid4

import numpy as np

from app.geometry.stock_model import StockModel
from app.models.machine import create_default_machine
from app.models.tool import Tool, ToolType
from app.parser.gcode_parser import GCodeParser
from app.services.report_service import ReportService
from app.simulation.machining_model import MachiningModel


def make_tool() -> Tool:
    return Tool(
        tool_number=1,
        name="테스트 엔드밀",
        tool_type=ToolType.END_MILL,
        diameter=10.0,
        length=75.0,
        flute_length=25.0,
        corner_radius=0.0,
        flute_count=4,
    )


def make_stock() -> StockModel:
    return StockModel(
        np.array([-30.0, -30.0, -20.0]),
        np.array([60.0, 30.0, 0.0]),
        resolution=1.0,
    )


def test_save_analysis_csv_bundle_creates_expected_files():
    """세그먼트/요약/공구/경고 CSV가 모두 생성되어야 한다."""
    code = """
G21 G90
T1 M6
S3000 M3
G0 X0 Y0 Z5
G1 Z-5.0 F200
G1 X20.0 F800
G0 Z5
"""
    parser = GCodeParser()
    toolpath = parser.parse_string(code)
    tool = make_tool()
    machine = create_default_machine()
    analysis = MachiningModel().analyze_toolpath(toolpath, {1: tool}, make_stock())

    temp_root = Path("tests") / f"_tmp_report_service_{uuid4().hex}"
    temp_root.mkdir(parents=True, exist_ok=True)
    try:
        service = ReportService()
        saved = service.save_analysis_csv_bundle(
            str(temp_root / "nc_analysis.csv"),
            toolpath,
            [],
            machine,
            {1: tool},
            None,
            analysis,
        )

        for path in saved.values():
            assert Path(path).exists()

        with open(saved["segments"], "r", encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))

        assert len(rows) == len(toolpath.segments)
        assert "segment_id" in rows[0]
        assert "start_x_mm" in rows[0]
        assert "radial_depth_ae_mm" in rows[0]
        assert "axial_depth_ap_mm" in rows[0]
        assert "vibration_z_um" in rows[0]
        assert "machining_state" in rows[0]
        assert "motion_vibration_um" in rows[0]
        assert "cutting_vibration_um" in rows[0]
        assert "chatter_raw_score" in rows[0]
        assert "baseline_load_pct" in rows[0]
        assert "material_ktc" in rows[0]

        with open(saved["summary"], "r", encoding="utf-8-sig", newline="") as file:
            summary_rows = list(csv.DictReader(file))

        keys = {row["key"] for row in summary_rows}
        assert "total_segments" in keys
        assert "max_spindle_load_pct" in keys
        assert "max_motion_vibration_um" in keys
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
