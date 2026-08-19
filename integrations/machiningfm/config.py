"""
MachiningFM integration configuration.

Channel mapping between cnc_simulator outputs and MachiningFM's 7-channel input.

The simulator (SegmentMachiningResult) produces per-segment physics estimates:
  - estimated_force_x  (force_x_n in risk_factors) [N]
  - estimated_force_y  (force_y_n in risk_factors) [N]
  - estimated_force_z  (force_z_n in risk_factors) [N]
  - vibration_x_um     [um]
  - vibration_y_um     [um]
  - vibration_z_um     [um]
  - spindle_load_pct   [%] (used as acoustic_emission_rms proxy)

MachiningFM expects 7 channels:
  Ch0: force_x          [N]
  Ch1: force_y          [N]
  Ch2: force_z          [N]
  Ch3: vibration_x      [m/s^2 or um] — sim provides um, kept as-is after norm
  Ch4: vibration_y      [m/s^2 or um]
  Ch5: vibration_z      [m/s^2 or um]
  Ch6: acoustic_emission_rms — proxied from spindle_load_pct (0-100 -> 0-1)

Channel mapping is explicit; no fabrication of unmeasured channels.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_FOUNDATION_ROOT = Path(
    os.environ.get(
        "MACHININGFM_ROOT",
        "/Users/junseokshim/Desktop/workspace/FOUNDATION",
    )
)

DEFAULT_CHECKPOINT_PATH: str = str(
    _FOUNDATION_ROOT
    / "outputs/checkpoints"
    / "full_pretrain_graph_tokenized_stemgnn_decoder_only_5070_nc_e4b_zeroshot_boost_oomsafe"
    / "machiningfm_full_pretrain_best.pt"
)

# ---------------------------------------------------------------------------
# Windowing
# ---------------------------------------------------------------------------
# Each NC segment maps to one "sample" in the time series.
# A pocket operation typically has 30-60 cutting segments; a window of 32
# captures a meaningful pass. Stride=16 gives 50% overlap.
# max_len=512 matches the encoder's default truncation (encoder.py DEFAULT_MAX_LEN).
WINDOW_SIZE: int = 32   # time steps per window (each step = 1 NC segment)
STRIDE: int = 16        # stride between windows
MAX_LEN: int = 512      # max sequence length for backbone (longer → truncate tail kept)

# ---------------------------------------------------------------------------
# Channel ordering (index → simulator field)
# ---------------------------------------------------------------------------
N_CHANNELS: int = 7

CHANNEL_NAMES: list[str] = [
    "force_x",           # Ch0  [N]
    "force_y",           # Ch1  [N]
    "force_z",           # Ch2  [N]
    "vibration_x_um",    # Ch3  [um]
    "vibration_y_um",    # Ch4  [um]
    "vibration_z_um",    # Ch5  [um]
    "ae_proxy",          # Ch6  spindle_load_pct / 100  → dimensionless ~AE RMS
]

# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------
DEVICE: str = os.environ.get("MACHININGFM_DEVICE", "cpu")
BACKBONE_MODE: str = "frozen"
