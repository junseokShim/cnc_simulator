"""Export parsed CNC data for the bundled Unreal Engine 5 viewer plugin."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

import numpy as np

from app.models.machining_result import MachiningAnalysis
from app.models.tool import Tool
from app.models.toolpath import MotionSegment, MotionType, Toolpath


class UnrealSceneExporter:
    """Serialize a toolpath using a stable, engine-neutral JSON schema.

    Coordinates stay in CNC millimetres. The Unreal plugin applies the mm-to-cm
    conversion so the exported data remains useful to other consumers too.
    """

    SCHEMA_VERSION = 1

    def __init__(self, arc_chord_mm: float = 1.0):
        if arc_chord_mm <= 0:
            raise ValueError("arc_chord_mm must be greater than zero")
        self.arc_chord_mm = float(arc_chord_mm)

    def export(
        self,
        toolpath: Toolpath,
        output_file: str | Path,
        stock_min: Iterable[float] = (-60.0, -60.0, -30.0),
        stock_max: Iterable[float] = (60.0, 60.0, 0.0),
        analysis: MachiningAnalysis | None = None,
        tools: dict[int, Tool] | None = None,
    ) -> Path:
        output = Path(output_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = self.build_scene(toolpath, stock_min, stock_max, analysis, tools)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return output

    def build_scene(
        self,
        toolpath: Toolpath,
        stock_min: Iterable[float] = (-60.0, -60.0, -30.0),
        stock_max: Iterable[float] = (60.0, 60.0, 0.0),
        analysis: MachiningAnalysis | None = None,
        tools: dict[int, Tool] | None = None,
    ) -> dict:
        minimum = np.asarray(tuple(stock_min), dtype=float)
        maximum = np.asarray(tuple(stock_max), dtype=float)
        if minimum.shape != (3,) or maximum.shape != (3,) or np.any(maximum <= minimum):
            raise ValueError("stock bounds must be valid three-dimensional min/max values")

        result_by_id = {
            result.segment_id: result for result in (analysis.results if analysis else [])
        }
        segments = []
        for segment in toolpath.segments:
            points = self._segment_points(segment)
            record = {
                "id": segment.segment_id,
                "line": segment.line_number,
                "motion": segment.motion_type.value,
                "cutting": segment.is_cutting_move,
                "feedrate_mm_min": segment.feedrate,
                "spindle_rpm": segment.spindle_speed,
                "tool": segment.tool_number,
                "points_mm": [[round(float(v), 6) for v in point] for point in points],
            }
            result = result_by_id.get(segment.segment_id)
            if result is not None:
                record["physics"] = {
                    "state": result.machining_state,
                    "force_n": [result.estimated_force_x, result.estimated_force_y, result.estimated_force_z],
                    "cutting_force_n": result.estimated_cutting_force,
                    "spindle_power_w": result.estimated_spindle_power,
                    "spindle_load_pct": result.spindle_load_pct,
                    "mrr_mm3_min": result.material_removal_rate,
                    "ap_mm": result.axial_depth_ap,
                    "ae_mm": result.radial_depth_ae,
                    "vibration_um": [result.vibration_x_um, result.vibration_y_um, result.vibration_z_um],
                    "chatter_risk": result.chatter_risk_score,
                }
            segments.append(record)

        return {
            "schema": "vericut.unreal.scene",
            "version": self.SCHEMA_VERSION,
            "units": "mm",
            "source": toolpath.source_file,
            "stock": {"min_mm": minimum.tolist(), "max_mm": maximum.tolist()},
            "tools": [tool.to_dict() for tool in (tools or {}).values()],
            "physics_model": analysis.model_params if analysis else {},
            "stats": {
                "segment_count": len(toolpath.segments),
                "total_distance_mm": toolpath.total_distance,
                "cutting_distance_mm": toolpath.cutting_distance,
                "estimated_time_s": toolpath.estimated_time,
            },
            "segments": segments,
        }

    def _segment_points(self, segment: MotionSegment) -> list[np.ndarray]:
        if not segment.is_arc or segment.arc_center is None:
            return [segment.start_pos, segment.end_pos]

        center = segment.arc_center
        start_delta = segment.start_pos[:2] - center[:2]
        end_delta = segment.end_pos[:2] - center[:2]
        start_angle = math.atan2(start_delta[1], start_delta[0])
        end_angle = math.atan2(end_delta[1], end_delta[0])
        clockwise = segment.motion_type == MotionType.ARC_CW
        sweep = end_angle - start_angle
        if clockwise and sweep >= 0:
            sweep -= 2 * math.pi
        elif not clockwise and sweep <= 0:
            sweep += 2 * math.pi

        radius = float(np.linalg.norm(start_delta))
        count = max(2, int(math.ceil(abs(sweep) * radius / self.arc_chord_mm)) + 1)
        points = []
        for index in range(count):
            t = index / (count - 1)
            angle = start_angle + sweep * t
            z = segment.start_pos[2] + (segment.end_pos[2] - segment.start_pos[2]) * t
            points.append(np.array([
                center[0] + radius * math.cos(angle),
                center[1] + radius * math.sin(angle),
                z,
            ]))
        points[-1] = segment.end_pos.copy()
        return points
