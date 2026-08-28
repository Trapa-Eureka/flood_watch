"""Spec §14 step 4: load the real Prithvi-EO-2.0 + sen1floods11 fine-tuned
segmentation checkpoint (backbone + UperNet decoder + head), not just the
foundation backbone.

Earlier version of this script only proved the generic pretrained *backbone*
loads via BACKBONE_REGISTRY — it silently ignored the actual sen1floods11
fine-tuned weights. Fixed here after finding IBM/NASA's own inference.py and
config.yaml in the checkpoint's HuggingFace repo: the correct, working approach
is `terratorch.cli_tools.LightningInferenceModel.from_config(config, checkpoint)`,
which builds the exact architecture (EncoderDecoderFactory + prithvi_eo_v2_300_tl
backbone + UperNetDecoder, see the downloaded config.yaml) and loads the
fine-tuned weights into it.

IMPORTANT finding: this checkpoint expects Sentinel-2 **optical** input (BLUE,
GREEN, RED, NIR_NARROW, SWIR_1, SWIR_2 — 6 bands), not Sentinel-1 SAR. Prithvi's
foundation pretraining corpus (HLS) is optical-only, so despite the "Sen1Floods11"
dataset name, the publicly released Prithvi checkpoints for it were fine-tuned on
that dataset's Sentinel-2 branch. See scripts/05_build_s2_composite.py for
building compatible input from real Marikina imagery.

Usage:
  python scripts/03_load_prithvi.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

CHECKPOINT_REPO = "ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11"
CHECKPOINT_FILE = "Prithvi-EO-V2-300M-TL-Sen1Floods11.pt"
CONFIG_FILE = "config.yaml"


def main() -> int:
    from huggingface_hub import hf_hub_download
    from terratorch.cli_tools import LightningInferenceModel

    cache_dir = config.REPO_ROOT / ".cache" / "prithvi_checkpoint"
    print(f"Downloading {CONFIG_FILE} and {CHECKPOINT_FILE} from {CHECKPOINT_REPO}...")
    config_path = hf_hub_download(repo_id=CHECKPOINT_REPO, filename=CONFIG_FILE, local_dir=cache_dir)
    checkpoint_path = hf_hub_download(repo_id=CHECKPOINT_REPO, filename=CHECKPOINT_FILE, local_dir=cache_dir)

    print("Loading the full fine-tuned segmentation model (backbone + decoder + head)...")
    lightning_model = LightningInferenceModel.from_config(config_path, checkpoint_path)
    n_params = sum(p.numel() for p in lightning_model.model.parameters())
    print(f"✓ Loaded successfully — parameter count: {n_params:,}")
    print("This is the real sen1floods11 fine-tuned model, ready for inference.")
    print("Next: scripts/05_build_s2_composite.py + scripts/prithvi_inference.py")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:  # noqa: BLE001
        print(f"✗ Failed: {type(e).__name__}: {e}")
        raise SystemExit(1)
