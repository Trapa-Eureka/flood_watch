"""Spec §14 step 4: load the Prithvi-EO-2.0 + sen1floods11 checkpoint via TerraTorch.

The TerraTorch API changes frequently across versions, so this script tries two
loading paths in order:
  A) standard loading via terratorch.tasks / BACKBONE_REGISTRY
  B) direct HuggingFace `from_pretrained` loading (fallback)
If both fail, the raw error is printed as-is — that's the actual point of the §3
technical validation (whether it loads at all is the signal).

Usage:
  python scripts/03_load_prithvi.py
  python scripts/03_load_prithvi.py --checkpoint ibm-nasa-geospatial/Prithvi-EO-1.0-100M-sen1floods11
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def try_terratorch_registry(checkpoint: str):
    import terratorch  # noqa: F401
    from terratorch.registry import BACKBONE_REGISTRY

    print(f"[path A] trying to load via terratorch.registry.BACKBONE_REGISTRY: {checkpoint}")
    print(f"  sample of registered backbones: {list(BACKBONE_REGISTRY)[:10]} ...")

    # terratorch typically loads via a backbone name like 'prithvi_eo_v2_300_tl' with
    # pretrained=True, and the sen1floods11 finetuned head is assembled separately
    # from a task config (yaml). Here we only confirm the backbone itself
    # instantiates correctly — sufficient for the spike's purpose.
    backbone_name = "prithvi_eo_v2_300_tl" if "300M" in checkpoint else "prithvi_eo_v1_100"
    model = BACKBONE_REGISTRY.build(backbone_name, pretrained=True)
    return model


def try_huggingface_direct(checkpoint: str):
    from huggingface_hub import hf_hub_download

    print(f"[path B] trying a direct HuggingFace Hub download: {checkpoint}")
    # Checkpoint filenames can differ per repo, so ideally we'd check config.json/README
    # first — but at the spike stage we only confirm that a download succeeds at all.
    path = hf_hub_download(repo_id=checkpoint, filename="config.json")
    print(f"  config.json downloaded successfully: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", default=config.PRITHVI_CHECKPOINT_PRIMARY)
    parser.add_argument("--fallback", default=config.PRITHVI_CHECKPOINT_FALLBACK)
    args = parser.parse_args()

    for checkpoint in (args.checkpoint, args.fallback):
        print("=" * 60)
        print(f"checkpoint: {checkpoint}")
        try:
            model = try_terratorch_registry(checkpoint)
            n_params = sum(p.numel() for p in model.parameters())
            print(f"  ✓ path A succeeded — parameter count: {n_params:,}")
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ path A failed: {type(e).__name__}: {e}")

        try:
            try_huggingface_direct(checkpoint)
            print("  ✓ path B succeeded (config file confirmed) — full weight loading still needs implementing")
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ path B failed: {type(e).__name__}: {e}")

    print("\nBoth checkpoints failed on both paths. Review the error messages to decide next steps")
    print("(spec §3 fallback plan: Sentinel-2 optical assist / compare against the Clay model).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
