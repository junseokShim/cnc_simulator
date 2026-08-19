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

import numpy as np

from integrations.machiningfm.config import (
    DEFAULT_CHECKPOINT_PATH,
    BACKBONE_MODE,
    DEVICE,
    MAX_LEN,
    WINDOW_SIZE,
    STRIDE,
)

# Ensure FOUNDATION project is importable
_FOUNDATION_ROOT = Path("/Users/junseokshim/Desktop/workspace/FOUNDATION")
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

    def run(self, signal: np.ndarray) -> dict:
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

        windows = self._sliding_windows(signal)
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

        return {
            "windows": windows,
            "window_embeddings": window_embeddings,
            "embedding_mean": embedding_mean,
            "n_windows": len(windows),
            "signal_shape": (T, C),
            "n_nan": n_nan,
            "wear_score": wear_score,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sliding_windows(self, signal: np.ndarray) -> list[np.ndarray]:
        """
        Slice signal into overlapping windows of shape (window_size, C).

        If T < window_size, return a single padded window.
        """
        T = signal.shape[0]

        if T < self.window_size:
            # Pad with zeros at the beginning
            pad_len = self.window_size - T
            padded = np.zeros((self.window_size, signal.shape[1]), dtype=signal.dtype)
            padded[pad_len:] = signal
            return [padded]

        windows = []
        start = 0
        while start + self.window_size <= T:
            windows.append(signal[start : start + self.window_size].copy())
            start += self.stride

        # Ensure at least one window
        if not windows:
            windows.append(signal[-self.window_size:].copy())

        return windows
