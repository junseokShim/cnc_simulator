#!/usr/bin/env python3
"""
Download MachiningFM pretrained checkpoint from HuggingFace.

Usage:
    python scripts/download_checkpoint.py
    python scripts/download_checkpoint.py --output-dir ../MachiningFM/outputs/checkpoints

The checkpoint is saved to:
    <output_dir>/full_pretrain_graph_tokenized_stemgnn_decoder_only_5070_nc_e4b_zeroshot_boost_oomsafe/
    machiningfm_full_pretrain_best.pt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ID = "Junseok2/MachiningFM2.0"
FILENAME = "machiningfm_full_pretrain_best.pt"
SUBDIR = (
    "full_pretrain_graph_tokenized_stemgnn_decoder_only_5070_nc_e4b_zeroshot_boost_oomsafe"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download MachiningFM checkpoint.")
    parser.add_argument(
        "--output-dir",
        default=str(Path(__file__).parent.parent.parent / "MachiningFM" / "outputs" / "checkpoints"),
        help="Directory to save the checkpoint (default: ../MachiningFM/outputs/checkpoints)",
    )
    args = parser.parse_args()

    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("ERROR: huggingface_hub not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    dest_dir = Path(args.output_dir) / SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / FILENAME

    if dest_path.exists():
        print(f"Checkpoint already exists: {dest_path}")
        return

    print(f"Downloading {REPO_ID}/{FILENAME} ...")
    print(f"Destination: {dest_path}")
    print("(File is ~7.4 GB — this may take a while)\n")

    downloaded = hf_hub_download(
        repo_id=REPO_ID,
        filename=FILENAME,
        local_dir=str(dest_dir),
    )
    print(f"\nSaved to: {downloaded}")


if __name__ == "__main__":
    main()
