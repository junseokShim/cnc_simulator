"""
Tests for integrations.machiningfm.adapter

Verifies that the adapter converts mock simulator data into correctly-shaped
numpy arrays with the expected dtype, NaN count, and channel count.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Ensure repo root is importable
_REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.models.machining_result import (
    ChatterRiskLevel,
    MachiningAnalysis,
    SegmentMachiningResult,
)
from integrations.machiningfm.adapter import SimulatorToMachiningFMAdapter
from integrations.machiningfm.config import N_CHANNELS, CHANNEL_NAMES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_segment(
    segment_id: int = 0,
    is_cutting: bool = True,
    fx: float = 100.0,
    fy: float = -80.0,
    fz: float = 40.0,
    vx: float = 5.0,
    vy: float = 4.0,
    vz: float = 1.0,
    load: float = 30.0,
) -> SegmentMachiningResult:
    return SegmentMachiningResult(
        segment_id=segment_id,
        spindle_speed=3000.0,
        feedrate=800.0,
        tool_diameter=10.0,
        flute_count=4,
        cutting_speed=94.2,
        feed_per_tooth=0.067,
        axial_depth_ap=5.0,
        radial_depth_ae=5.0,
        radial_ratio=0.5,
        engagement_ratio=0.25,
        material_removal_rate=5000.0,
        estimated_cutting_force=150.0,
        estimated_spindle_power=500.0,
        spindle_load_pct=load,
        aggressiveness_score=0.4,
        estimated_force_x=fx,
        estimated_force_y=fy,
        estimated_force_z=fz,
        vibration_x_um=vx,
        vibration_y_um=vy,
        vibration_z_um=vz,
        resultant_vibration_um=(vx**2 + vy**2 + vz**2) ** 0.5,
        chatter_risk_score=0.2,
        chatter_risk_level=ChatterRiskLevel.LOW,
        direction_change_angle=0.0,
        is_plunge=False,
        is_ramp=False,
        is_cutting=is_cutting,
        machining_state="CUTTING" if is_cutting else "AIR_FEED",
    )


def _make_analysis(
    n_cutting: int = 10,
    n_rapid: int = 3,
) -> MachiningAnalysis:
    results = (
        [_make_segment(i, is_cutting=True) for i in range(n_cutting)]
        + [_make_segment(n_cutting + i, is_cutting=False) for i in range(n_rapid)]
    )
    analysis = MachiningAnalysis(results=results)
    analysis.compute_statistics()
    return analysis


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAdapterShape:
    def test_output_shape_correct(self):
        """Adapter should return (T, 7) where T = n_cutting_segments."""
        analysis = _make_analysis(n_cutting=10, n_rapid=3)
        adapter = SimulatorToMachiningFMAdapter(normalise=False)
        signal, meta = adapter.convert(analysis)

        assert signal.shape == (10, N_CHANNELS), f"Expected (10, 7), got {signal.shape}"

    def test_output_dtype_float32(self):
        """Output must be float32 for PyTorch compatibility."""
        analysis = _make_analysis(n_cutting=5)
        adapter = SimulatorToMachiningFMAdapter(normalise=False)
        signal, _ = adapter.convert(analysis)
        assert signal.dtype == np.float32

    def test_no_nan_in_output(self):
        """No NaN values should appear in adapter output."""
        analysis = _make_analysis(n_cutting=15)
        adapter = SimulatorToMachiningFMAdapter(normalise=True)
        signal, _ = adapter.convert(analysis)
        assert not np.any(np.isnan(signal)), "NaN values found in adapter output"

    def test_seven_channels(self):
        """Output must have exactly 7 channels regardless of input."""
        for n in [1, 5, 50]:
            analysis = _make_analysis(n_cutting=n)
            adapter = SimulatorToMachiningFMAdapter(normalise=False)
            signal, _ = adapter.convert(analysis)
            assert signal.shape[1] == N_CHANNELS, f"Expected 7 channels, got {signal.shape[1]}"


class TestAdapterChannelMapping:
    def test_force_x_mapped_to_ch0(self):
        """force_x should appear in channel 0."""
        seg = _make_segment(fx=999.0, is_cutting=True)
        adapter = SimulatorToMachiningFMAdapter(normalise=False)
        signal = adapter.convert_results([seg, _make_segment(fx=0.0)])
        assert signal[0, 0] == pytest.approx(999.0, rel=1e-4)

    def test_ae_proxy_is_load_div_100(self):
        """Channel 6 should be spindle_load_pct / 100."""
        seg = _make_segment(load=60.0, is_cutting=True)
        adapter = SimulatorToMachiningFMAdapter(normalise=False)
        signal = adapter.convert_results([seg])
        assert signal[0, 6] == pytest.approx(0.6, rel=1e-5)

    def test_channel_names_correct(self):
        """Adapter meta should return the correct channel names."""
        analysis = _make_analysis(n_cutting=5)
        adapter = SimulatorToMachiningFMAdapter()
        _, meta = adapter.convert(analysis)
        assert meta["channel_names"] == CHANNEL_NAMES


class TestAdapterFallback:
    def test_empty_analysis_returns_zero_array(self):
        """Empty analysis should return (1, 7) zero array without crashing."""
        analysis = MachiningAnalysis(results=[])
        adapter = SimulatorToMachiningFMAdapter()
        signal, meta = adapter.convert(analysis)
        assert signal.shape == (1, N_CHANNELS)
        assert np.all(signal == 0.0)
        assert meta["n_segments_used"] == 0

    def test_all_rapid_falls_back_to_all_segments(self):
        """If no cutting segments, adapter falls back to all segments."""
        analysis = _make_analysis(n_cutting=0, n_rapid=5)
        adapter = SimulatorToMachiningFMAdapter(normalise=False)
        signal, meta = adapter.convert(analysis)
        assert signal.shape[0] == 5
        assert meta["mode"] == "all (fallback: <2 cutting segs)"

    def test_one_cutting_segment_falls_back(self):
        """Only 1 cutting segment triggers fallback to all segments."""
        analysis = _make_analysis(n_cutting=1, n_rapid=4)
        adapter = SimulatorToMachiningFMAdapter(normalise=False)
        signal, meta = adapter.convert(analysis)
        # 1 cutting + 4 rapid = 5 total
        assert signal.shape[0] == 5
        assert "fallback" in meta["mode"]


class TestAdapterNormalisation:
    def test_normalised_mean_near_zero(self):
        """After z-score normalisation, channel means should be near zero."""
        analysis = _make_analysis(n_cutting=20)
        adapter = SimulatorToMachiningFMAdapter(normalise=True)
        signal, _ = adapter.convert(analysis)
        channel_means = signal.mean(axis=0)
        np.testing.assert_allclose(channel_means, 0.0, atol=1e-5)

    def test_constant_channel_does_not_nan(self):
        """Constant-value channels (std=0) should not produce NaN after normalisation."""
        # All segments have identical values → std = 0
        segs = [_make_segment(vz=0.0, is_cutting=True) for _ in range(10)]
        adapter = SimulatorToMachiningFMAdapter(normalise=True)
        signal = adapter.convert_results(segs)
        assert not np.any(np.isnan(signal))
