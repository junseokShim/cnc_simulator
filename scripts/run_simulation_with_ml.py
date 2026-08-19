"""
End-to-end CNC simulation + MachiningFM inference script.

Usage:
    python scripts/run_simulation_with_ml.py [NC_FILE] [--no-ml] [--output-dir DIR]

Example:
    python scripts/run_simulation_with_ml.py examples/simple_pocket.nc
    python scripts/run_simulation_with_ml.py examples/contour_example.nc --output-dir /tmp/myrun

Steps:
  1. Parse NC file with GCodeParser
  2. Verify NC code
  3. Run MachiningModel analysis (physics-based)
  4. Convert result to MachiningFM input via adapter
  5. Run backbone inference (windowed)
  6. Save all outputs to outputs/run_TIMESTAMP/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Path setup: ensure cnc_simulator root and FOUNDATION are importable
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).parent.parent.resolve()
_FOUNDATION_ROOT = Path("/Users/junseokshim/Desktop/workspace/FOUNDATION")

for p in [str(_REPO_ROOT), str(_FOUNDATION_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CNC Simulation + MachiningFM Inference Pipeline"
    )
    parser.add_argument(
        "nc_file",
        nargs="?",
        default=str(_REPO_ROOT / "examples" / "simple_pocket.nc"),
        help="NC file to simulate (default: examples/simple_pocket.nc)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: outputs/run_TIMESTAMP/)",
    )
    parser.add_argument(
        "--no-ml",
        action="store_true",
        help="Skip MachiningFM inference (simulation only)",
    )
    parser.add_argument(
        "--material",
        default="aluminum",
        help="Workpiece material (default: aluminum)",
    )
    return parser.parse_args()


def setup_output_dir(base: str | None) -> Path:
    if base is not None:
        out_dir = Path(base)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = _REPO_ROOT / "outputs" / f"run_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def step_simulate(nc_file: str, material: str):
    """Parse NC, run physics analysis, return (toolpath, analysis, tools, machine)."""
    print("\n[Step 1/4] Parsing NC file ...")
    from app.parser.gcode_parser import GCodeParser
    from app.models.machine import create_default_machine
    from app.simulation.machining_model import MachiningModel, MachiningModelConfig
    from app.geometry.stock_model import StockModel
    from app.verification.checker import VerificationChecker
    from app.models.project import ProjectConfig

    parser = GCodeParser()
    toolpath = parser.parse_file(nc_file)
    print(f"  Parsed: {len(toolpath.segments)} segments, "
          f"cutting dist={toolpath.cutting_distance:.1f} mm, "
          f"total dist={toolpath.total_distance:.1f} mm, "
          f"parse warnings={len(toolpath.warnings)}")

    print("[Step 2/4] Running verification ...")
    machine = create_default_machine()
    stock = StockModel(
        np.array([-60.0, -60.0, -30.0]),
        np.array([60.0, 60.0, 0.0]),
        resolution=5.0,
    )
    checker = VerificationChecker()
    warnings = checker.run_all_checks(toolpath, stock, machine, {})
    errors = sum(1 for w in warnings if w.severity == "ERROR")
    warns = sum(1 for w in warnings if w.severity == "WARNING")
    print(f"  Verification: {errors} errors, {warns} warnings")

    print(f"[Step 3/4] Running physics analysis (material={material}) ...")
    config = MachiningModelConfig({"material": material})
    model = MachiningModel(config=config)
    analysis = model.analyze_toolpath(toolpath, toolpath.tools if hasattr(toolpath, 'tools') and toolpath.tools else {})

    cutting = [r for r in analysis.results if r.is_cutting]
    print(f"  Analysis done: {len(analysis.results)} total segments, "
          f"{len(cutting)} cutting, "
          f"max load={analysis.max_spindle_load_pct:.1f}%, "
          f"max chatter={analysis.max_chatter_risk*100:.1f}%")

    return toolpath, analysis, machine, warnings


def step_adapt(analysis):
    """Convert analysis to MachiningFM input signal."""
    print("[Step 4a/4] Adapting simulator output to MachiningFM input ...")
    from integrations.machiningfm.adapter import SimulatorToMachiningFMAdapter

    adapter = SimulatorToMachiningFMAdapter(normalise=True)
    signal, meta = adapter.convert(analysis)

    n_nan = int(np.isnan(signal).sum())
    print(f"  Signal shape: {signal.shape}, dtype={signal.dtype}, NaN count={n_nan}")
    print(f"  Segments used: {meta['n_segments_used']} ({meta['mode']})")
    print(f"  Channel min: {signal.min(axis=0).round(4)}")
    print(f"  Channel max: {signal.max(axis=0).round(4)}")
    print(f"  Channel mean: {signal.mean(axis=0).round(4)}")
    return signal, meta


def step_infer(signal: np.ndarray):
    """Run MachiningFM backbone inference."""
    print("[Step 4b/4] Running MachiningFM backbone inference ...")
    from integrations.machiningfm.inference import MachiningFMInference

    runner = MachiningFMInference()
    t0 = time.time()
    result = runner.run(signal)
    elapsed = time.time() - t0

    emb = result["embedding_mean"]
    print(f"  Inference done in {elapsed:.2f}s")
    print(f"  Windows processed: {result['n_windows']}")
    print(f"  Embedding shape: {emb.shape}")
    print(f"  Embedding min={emb.min():.6f}, max={emb.max():.6f}, mean={emb.mean():.6f}")
    print(f"  Zero-shot wear score (L2 norm): {result['wear_score']:.4f}")
    return result


def save_outputs(
    out_dir: Path,
    nc_file: str,
    toolpath,
    analysis,
    machine,
    sim_warnings,
    signal: np.ndarray | None,
    adapter_meta: dict | None,
    ml_result: dict | None,
):
    """Save all outputs to out_dir."""
    print(f"\n[Saving outputs to {out_dir}] ...")
    saved = []

    # 1. Simulation segments CSV
    from app.services.report_service import ReportService
    from app.models.machine import create_default_machine

    rpt = ReportService()

    seg_csv = str(out_dir / "segments")
    paths = rpt.save_analysis_csv_bundle(
        filepath=seg_csv,
        toolpath=toolpath,
        warnings=sim_warnings,
        machine=machine,
        tools={},
        machining_analysis=analysis,
    )
    for k, v in paths.items():
        saved.append(v)
        print(f"  Saved {k}: {v}")

    # 2. Signal array
    if signal is not None:
        signal_path = out_dir / "machiningfm_signal.npy"
        np.save(str(signal_path), signal)
        saved.append(str(signal_path))
        print(f"  Saved signal: {signal_path}")

    # 3. Embeddings
    if ml_result is not None:
        emb_path = out_dir / "embeddings.npy"
        np.save(str(emb_path), ml_result["window_embeddings"])
        saved.append(str(emb_path))
        print(f"  Saved embeddings: {emb_path}")

        mean_emb_path = out_dir / "embedding_mean.npy"
        np.save(str(mean_emb_path), ml_result["embedding_mean"])
        saved.append(str(mean_emb_path))
        print(f"  Saved mean embedding: {mean_emb_path}")

    # 4. Summary JSON
    summary = {
        "nc_file": nc_file,
        "timestamp": datetime.now().isoformat(),
        "simulation": {
            "total_segments": len(toolpath.segments),
            "cutting_segments": len([r for r in analysis.results if r.is_cutting]),
            "max_spindle_load_pct": round(analysis.max_spindle_load_pct, 4),
            "avg_spindle_load_pct": round(analysis.avg_spindle_load_pct, 4),
            "max_chatter_risk_pct": round(analysis.max_chatter_risk * 100, 4),
            "max_resultant_vibration_um": round(analysis.max_resultant_vibration_um, 4),
        },
        "adapter": adapter_meta,
        "inference": None if ml_result is None else {
            "n_windows": ml_result["n_windows"],
            "signal_shape": list(ml_result["signal_shape"]),
            "n_nan": ml_result["n_nan"],
            "embedding_shape": list(ml_result["embedding_mean"].shape),
            "embedding_min": float(ml_result["embedding_mean"].min()),
            "embedding_max": float(ml_result["embedding_mean"].max()),
            "embedding_mean": float(ml_result["embedding_mean"].mean()),
            "wear_score": ml_result["wear_score"],
        },
    }
    summary_path = out_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    saved.append(str(summary_path))
    print(f"  Saved summary: {summary_path}")

    return saved


def main():
    args = parse_args()

    nc_file = args.nc_file
    if not os.path.exists(nc_file):
        print(f"ERROR: NC file not found: {nc_file}")
        sys.exit(1)

    out_dir = setup_output_dir(args.output_dir)
    print("=" * 70)
    print("CNC Simulator + MachiningFM Inference Pipeline")
    print(f"  NC file:    {nc_file}")
    print(f"  Output dir: {out_dir}")
    print(f"  Material:   {args.material}")
    print(f"  ML enabled: {not args.no_ml}")
    print("=" * 70)

    # --- Simulation ---
    toolpath, analysis, machine, sim_warnings = step_simulate(nc_file, args.material)

    # --- Adapter ---
    signal, adapter_meta = step_adapt(analysis)

    # --- Inference ---
    ml_result = None
    if not args.no_ml:
        try:
            ml_result = step_infer(signal)
        except Exception as exc:
            print(f"  WARNING: MachiningFM inference failed: {exc}")
            print("  Continuing without ML output.")

    # --- Save outputs ---
    saved = save_outputs(
        out_dir, nc_file, toolpath, analysis, machine, sim_warnings,
        signal, adapter_meta, ml_result,
    )

    print("\n" + "=" * 70)
    print("Pipeline complete.")
    print(f"  Output directory: {out_dir}")
    print(f"  Files saved: {len(saved)}")
    if ml_result is not None:
        emb = ml_result["embedding_mean"]
        print(f"  Embedding: shape={emb.shape}, min={emb.min():.6f}, max={emb.max():.6f}, mean={emb.mean():.6f}")
        print(f"  Zero-shot wear score: {ml_result['wear_score']:.4f}")
    print("=" * 70)


if __name__ == "__main__":
    main()
