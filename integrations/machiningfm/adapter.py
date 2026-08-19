"""
Adapter: cnc_simulator SegmentMachiningResult list → MachiningFM numpy input.

The simulator produces one SegmentMachiningResult per NC segment.  This adapter:
  1. Filters to cutting-only segments (is_cutting=True) to avoid air-feed noise.
  2. Extracts the 7 channels that MachiningFM expects (force_x/y/z, vib_x/y/z, ae_proxy).
  3. Normalises each channel independently (z-score), falling back to raw values
     when std == 0 (constant channel).
  4. Returns a single (T, 7) float32 numpy array where T = number of cutting segments.

If fewer than 2 cutting segments exist (e.g. all rapid moves), the adapter
returns all segments (including non-cutting) to avoid an empty array.

Channel mapping (explicit, no fabrication):
  Ch0  force_x       ← SegmentMachiningResult.estimated_force_x   [N]
  Ch1  force_y       ← SegmentMachiningResult.estimated_force_y   [N]
  Ch2  force_z       ← SegmentMachiningResult.estimated_force_z   [N]
  Ch3  vibration_x   ← SegmentMachiningResult.vibration_x_um      [um]
  Ch4  vibration_y   ← SegmentMachiningResult.vibration_y_um      [um]
  Ch5  vibration_z   ← SegmentMachiningResult.vibration_z_um      [um]
  Ch6  ae_proxy      ← SegmentMachiningResult.spindle_load_pct / 100   [0-1]
"""
from __future__ import annotations

from typing import List

import numpy as np

from app.models.machining_result import MachiningAnalysis, SegmentMachiningResult
from integrations.machiningfm.config import N_CHANNELS, CHANNEL_NAMES


class SimulatorToMachiningFMAdapter:
    """
    Convert cnc_simulator analysis output to MachiningFM-compatible numpy arrays.

    Usage:
        adapter = SimulatorToMachiningFMAdapter()
        signal, meta = adapter.convert(analysis)
        # signal: np.ndarray shape (T, 7), dtype float32
        # meta:   dict with channel info and segment indices used
    """

    def __init__(self, normalise: bool = True) -> None:
        """
        Args:
            normalise: If True, z-score each channel independently.
                       Set False for unit-testing with known values.
        """
        self.normalise = normalise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def convert(
        self,
        analysis: MachiningAnalysis,
    ) -> tuple[np.ndarray, dict]:
        """
        Convert a MachiningAnalysis to a single (T, C) float32 array.

        Args:
            analysis: Result from MachiningModel.analyze_toolpath().

        Returns:
            signal: np.ndarray of shape (T, 7), dtype float32.
            meta:   dict with keys:
                      'n_segments_total', 'n_cutting_segments',
                      'n_segments_used', 'channel_names', 'normalised'
        """
        results = analysis.results
        cutting_results = [r for r in results if r.is_cutting]

        # Fall back to all segments if fewer than 2 cutting segments
        if len(cutting_results) < 2:
            used_results = results
            used_label = "all (fallback: <2 cutting segs)"
        else:
            used_results = cutting_results
            used_label = "cutting_only"

        if not used_results:
            # Return a zero array with 1 time step so downstream code never
            # crashes on empty input.
            signal = np.zeros((1, N_CHANNELS), dtype=np.float32)
            meta = {
                "n_segments_total": len(results),
                "n_cutting_segments": 0,
                "n_segments_used": 0,
                "channel_names": CHANNEL_NAMES,
                "normalised": False,
                "mode": "empty_fallback",
            }
            return signal, meta

        raw = self._extract_raw(used_results)        # (T, 7)
        signal = self._normalise(raw) if self.normalise else raw.astype(np.float32)

        meta = {
            "n_segments_total": len(results),
            "n_cutting_segments": len(cutting_results),
            "n_segments_used": len(used_results),
            "channel_names": CHANNEL_NAMES,
            "normalised": self.normalise,
            "mode": used_label,
        }
        return signal, meta

    def convert_results(
        self,
        results: List[SegmentMachiningResult],
    ) -> np.ndarray:
        """
        Convert a raw list of SegmentMachiningResult objects.

        Useful for unit-testing without a full MachiningAnalysis container.

        Returns:
            np.ndarray of shape (T, 7), dtype float32 (normalised).
        """
        if not results:
            return np.zeros((1, N_CHANNELS), dtype=np.float32)
        raw = self._extract_raw(results)
        return self._normalise(raw) if self.normalise else raw.astype(np.float32)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_raw(results: List[SegmentMachiningResult]) -> np.ndarray:
        """Extract raw values into (T, 7) float64 array before normalisation."""
        T = len(results)
        arr = np.zeros((T, N_CHANNELS), dtype=np.float64)

        for i, r in enumerate(results):
            arr[i, 0] = r.estimated_force_x            # force_x [N]
            arr[i, 1] = r.estimated_force_y            # force_y [N]
            arr[i, 2] = r.estimated_force_z            # force_z [N]
            arr[i, 3] = r.vibration_x_um               # vib_x   [um]
            arr[i, 4] = r.vibration_y_um               # vib_y   [um]
            arr[i, 5] = r.vibration_z_um               # vib_z   [um]
            arr[i, 6] = r.spindle_load_pct / 100.0     # ae_proxy [0-1]

        return arr

    @staticmethod
    def _normalise(arr: np.ndarray) -> np.ndarray:
        """Z-score normalise each channel independently; skip channels with std=0."""
        result = arr.copy().astype(np.float32)
        for c in range(arr.shape[1]):
            col = arr[:, c]
            mu = col.mean()
            sigma = col.std()
            if sigma > 1e-9:
                result[:, c] = ((col - mu) / sigma).astype(np.float32)
            else:
                result[:, c] = (col - mu).astype(np.float32)  # zero if constant
        return result
