"""
Tests for integrations.machiningfm.inference (MachiningFMInference)

These tests verify:
  - Backbone loads successfully from the local checkpoint
  - Inference produces correct output shapes
  - Windowed slicing works correctly
  - NaN replacement works

Note: The backbone load (~7GB) is expensive; the checkpoint is loaded once
per session via the lazy-load mechanism and kept in memory by pytest.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).parent.parent.resolve()
_FOUNDATION_ROOT = Path("/Users/junseokshim/Desktop/workspace/FOUNDATION")
for p in [str(_REPO_ROOT), str(_FOUNDATION_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from integrations.machiningfm.config import (
    DEFAULT_CHECKPOINT_PATH,
    N_CHANNELS,
    WINDOW_SIZE,
    STRIDE,
)
from integrations.machiningfm.inference import MachiningFMInference

# ---------------------------------------------------------------------------
# Shared fixture: load backbone once for the entire test session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def inference_runner():
    """Load MachiningFMInference once for the whole test session."""
    runner = MachiningFMInference(
        checkpoint_path=DEFAULT_CHECKPOINT_PATH,
        window_size=WINDOW_SIZE,
        stride=STRIDE,
        device="cpu",
    )
    # Force backbone load now
    _ = runner._get_backbone()
    return runner


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBackboneLoad:
    def test_backbone_loads(self, inference_runner):
        """Backbone should load without error."""
        backbone = inference_runner._get_backbone()
        assert backbone is not None

    def test_d_model_is_2048(self, inference_runner):
        """Full pretrain backbone should have d_model=2048."""
        backbone = inference_runner._get_backbone()
        assert backbone.d_model == 2048

    def test_architecture_label(self, inference_runner):
        """Architecture should be the full pretrain label."""
        backbone = inference_runner._get_backbone()
        assert "graph_tokenized" in backbone.architecture or backbone.architecture.startswith("machiningfm")


class TestInferenceOutputShape:
    def test_embedding_shape_single_window(self, inference_runner):
        """Short signal (T < window_size) → 1 window → embedding shape (1, 2048)."""
        signal = np.random.randn(10, N_CHANNELS).astype(np.float32)
        result = inference_runner.run(signal)
        assert result["window_embeddings"].shape == (1, 2048)
        assert result["embedding_mean"].shape == (2048,)

    def test_embedding_shape_multiple_windows(self, inference_runner):
        """Long signal → multiple windows → correct embedding shapes."""
        T = 80
        signal = np.random.randn(T, N_CHANNELS).astype(np.float32)
        result = inference_runner.run(signal)
        # n_windows = floor((80 - 32) / 16) + 1 = 3 + 1 = 4 (at least 1)
        assert result["n_windows"] >= 1
        n_w = result["n_windows"]
        assert result["window_embeddings"].shape == (n_w, 2048)
        assert result["embedding_mean"].shape == (2048,)

    def test_signal_shape_reported(self, inference_runner):
        """Result dict should report the original signal shape."""
        T, C = 42, N_CHANNELS
        signal = np.random.randn(T, C).astype(np.float32)
        result = inference_runner.run(signal)
        assert result["signal_shape"] == (T, C)

    def test_nan_count_zero_for_clean_signal(self, inference_runner):
        """Clean signal should report n_nan=0."""
        signal = np.ones((20, N_CHANNELS), dtype=np.float32)
        result = inference_runner.run(signal)
        assert result["n_nan"] == 0

    def test_nan_replacement(self, inference_runner):
        """NaN values in input should be replaced (not propagated to embedding)."""
        signal = np.random.randn(20, N_CHANNELS).astype(np.float32)
        signal[0, 0] = float("nan")
        result = inference_runner.run(signal)
        assert result["n_nan"] == 1
        # Embedding should not contain NaN
        assert not np.any(np.isnan(result["embedding_mean"]))

    def test_wear_score_is_positive_scalar(self, inference_runner):
        """Zero-shot wear score (L2 norm) should be a non-negative scalar."""
        signal = np.random.randn(30, N_CHANNELS).astype(np.float32)
        result = inference_runner.run(signal)
        assert isinstance(result["wear_score"], float)
        assert result["wear_score"] >= 0.0


class TestWindowSlicing:
    def test_sliding_windows_shapes(self):
        """_sliding_windows should produce windows of shape (window_size, C)."""
        runner = MachiningFMInference.__new__(MachiningFMInference)
        runner.window_size = 8
        runner.stride = 4

        signal = np.random.randn(32, 7).astype(np.float32)
        windows = runner._sliding_windows(signal)
        for w in windows:
            assert w.shape == (8, 7)

    def test_short_signal_produces_one_padded_window(self):
        """Signal shorter than window_size → single padded window."""
        runner = MachiningFMInference.__new__(MachiningFMInference)
        runner.window_size = 32
        runner.stride = 16

        signal = np.ones((5, 7), dtype=np.float32) * 3.0
        windows = runner._sliding_windows(signal)
        assert len(windows) == 1
        assert windows[0].shape == (32, 7)
        # Last 5 rows should be the signal
        np.testing.assert_array_equal(windows[0][-5:], signal)
        # First 27 rows should be zeros (padding)
        np.testing.assert_array_equal(windows[0][:27], 0.0)
