"""
MachiningFM inference runner for cnc_simulator integration.

Takes a (T, 7) signal array from the adapter and runs windowed backbone
inference to produce embeddings, then optionally runs a zero-shot ToolWearRegressor.

Architecture used: GraphTokenizedStemGNNDecoderOnlyMachiningFM (d_model=2048)
loaded via machiningfm.models.encoder.load_backbone().

Windowed inference:
  - Each window is a slice [t : t+window_size] from the signal.
  - Windows are batched through the backbone.
  - Output embeddings are averaged across all windows.
  - If T < window_size, a single padded window is used.

Zero-shot wear estimate:
  - Because we have no VB labels at inference time we cannot call regressor.fit().
  - Instead we project the mean embedding with a randomly initialised Ridge head
    and report the raw (untrained) projection as a relative risk score.
  - The value should be interpreted as a relative scalar, not an absolute VB (mm).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import os

import numpy as np

from integrations.machiningfm.config import (
    DEFAULT_CHECKPOINT_PATH,
    BACKBONE_MODE,
    DEVICE,
    MAX_LEN,
    WINDOW_SIZE,
    STRIDE,
    TAYLOR_C,
    TAYLOR_N,
    TAYLOR_M,
    TAYLOR_P,
)

# Ensure MachiningFM (FOUNDATION) project is importable.
# Resolution order: MACHININGFM_ROOT env var → sibling directory named MachiningFM.
_SELF_ROOT = Path(__file__).parent.parent.parent.resolve()  # cnc_simulator root
_FOUNDATION_ROOT = Path(
    os.environ.get("MACHININGFM_ROOT", str(_SELF_ROOT.parent / "MachiningFM"))
)
if str(_FOUNDATION_ROOT) not in sys.path:
    sys.path.insert(0, str(_FOUNDATION_ROOT))


class MachiningFMInference:
    """
    Wrapper around MachiningFM backbone for windowed embedding extraction.

    Usage:
        runner = MachiningFMInference()
        result = runner.run(signal)   # signal: (T, 7) float32
        print(result['embedding_mean'])  # shape (2048,)
        print(result['wear_score'])      # scalar relative risk
    """

    def __init__(
        self,
        checkpoint_path: Optional[str] = None,
        backbone_mode: str = BACKBONE_MODE,
        device: str = DEVICE,
        window_size: int = WINDOW_SIZE,
        stride: int = STRIDE,
        max_len: int = MAX_LEN,
    ) -> None:
        self.checkpoint_path = checkpoint_path or DEFAULT_CHECKPOINT_PATH
        self.backbone_mode = backbone_mode
        self.device = device
        self.window_size = window_size
        self.stride = stride
        self.max_len = max_len
        self._backbone = None

    # ------------------------------------------------------------------
    # Lazy backbone loading
    # ------------------------------------------------------------------

    def _get_backbone(self):
        if self._backbone is None:
            from machiningfm.models.encoder import load_backbone
            print(f"[MachiningFMInference] Loading backbone from: {self.checkpoint_path}")
            self._backbone = load_backbone(
                checkpoint_path=self.checkpoint_path,
                backbone_mode=self.backbone_mode,
                device=self.device,
            )
        return self._backbone

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _build_physics_features(
        self,
        conditions: dict | None,
        window_indices: list[tuple[int, int]],
    ) -> list | None:
        """
        Compute PhysicsFeatures for each window using Taylor tool-life equation.

        Uses representative (median) machining conditions within each window.
        Returns None if conditions dict is not provided.
        """
        if conditions is None:
            return None

        try:
            from machiningfm.physics.taylor import TaylorParams, compute_tool_life_ratio
            from machiningfm.physics.calibration import PhysicsFeatures
        except ImportError:
            return None

        taylor_params = TaylorParams(
            C=TAYLOR_C, n=TAYLOR_N, m=TAYLOR_M, p=TAYLOR_P
        )

        features = []
        for start, end in window_indices:
            vc = float(np.median(conditions["cutting_speed_m_per_min"][start:end]))
            fz = float(np.median(conditions["feed_per_tooth_mm"][start:end]))
            ap = float(np.median(conditions["axial_depth_mm"][start:end]))
            t  = float(conditions["elapsed_time_min"][end - 1])  # end of window

            pf = PhysicsFeatures()
            try:
                if vc > 0 and fz > 0 and ap > 0:
                    pf.tool_life_ratio = compute_tool_life_ratio(
                        elapsed_time_min=t,
                        cutting_speed_m_per_min=vc,
                        feed_mm_per_rev=fz,
                        axial_depth_mm=ap,
                        params=taylor_params,
                    )
            except Exception:
                pass
            features.append(pf)

        return features

    def run(self, signal: np.ndarray, conditions: dict | None = None) -> dict:
        """
        Run windowed backbone inference on a (T, C) signal.

        Args:
            signal: float32 array of shape (T, C) where C=7.

        Returns:
            dict with keys:
              'windows':          list of (window_size, C) arrays extracted
              'window_embeddings': np.ndarray (n_windows, d_model)
              'embedding_mean':   np.ndarray (d_model,) — mean across windows
              'n_windows':        int
              'signal_shape':     tuple (T, C)
              'n_nan':            int — NaN count in input
              'wear_score':       float — zero-shot relative risk scalar
        """
        from machiningfm.models.encoder import extract_embeddings

        if signal.ndim != 2:
            raise ValueError(f"signal must be 2-D (T, C), got shape {signal.shape}")

        T, C = signal.shape
        n_nan = int(np.isnan(signal).sum())
        if n_nan > 0:
            print(f"[MachiningFMInference] WARNING: {n_nan} NaN values in signal; replacing with 0.")
            signal = np.nan_to_num(signal, nan=0.0)

        windows, window_indices = self._sliding_windows_with_indices(signal)
        backbone = self._get_backbone()

        window_embeddings = extract_embeddings(
            backbone,
            windows,
            device=self.device,
            max_len=self.max_len,
        )  # (n_windows, d_model)

        embedding_mean = window_embeddings.mean(axis=0)  # (d_model,)

        # Zero-shot wear score: L2 norm of mean embedding (relative risk proxy)
        wear_score = float(np.linalg.norm(embedding_mean))

        # Physics features — Taylor tool-life ratio per window
        physics_features = self._build_physics_features(conditions, window_indices)
        tool_life_ratios = None
        if physics_features is not None:
            ratios = [pf.tool_life_ratio for pf in physics_features]
            tool_life_ratios = [r for r in ratios if r is not None]

        return {
            "windows": windows,
            "window_embeddings": window_embeddings,
            "embedding_mean": embedding_mean,
            "n_windows": len(windows),
            "signal_shape": (T, C),
            "n_nan": n_nan,
            "wear_score": wear_score,
            "physics_features": physics_features,
            "tool_life_ratios": tool_life_ratios,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sliding_windows_with_indices(
        self, signal: np.ndarray
    ) -> tuple[list[np.ndarray], list[tuple[int, int]]]:
        """
        Slice signal into overlapping windows. Returns (windows, [(start, end), ...]).

        If T < window_size, returns a single zero-padded window with index (0, T).
        """
        T = signal.shape[0]

        if T < self.window_size:
            pad_len = self.window_size - T
            padded = np.zeros((self.window_size, signal.shape[1]), dtype=signal.dtype)
            padded[pad_len:] = signal
            return [padded], [(0, T)]

        windows = []
        indices = []
        start = 0
        while start + self.window_size <= T:
            windows.append(signal[start : start + self.window_size].copy())
            indices.append((start, start + self.window_size))
            start += self.stride

        # Ensure at least one window
        if not windows:
            windows.append(signal[-self.window_size:].copy())
            indices.append((T - self.window_size, T))

        return windows, indices
