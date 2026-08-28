"""Week 2-2: Prithvi+sen1floods11 inference.run as a Modal serverless GPU
service (spec.md §5: "Modal 서버리스 GPU").

Deliberately does NOT modify pipeline/inference/prithvi_inference.py (that
file's own header explains why it's kept vendored/as-is). Instead this wraps
its individual functions (load_example/run_model/save_geotiff) directly,
rather than calling its main() as one unit — main() couples model-loading +
inference + file-saving into a single call, which would reload the ~300M-
param model on *every* request. That's wasteful and, more importantly, would
make Week 2-4's cost/latency measurements meaningless (they're supposed to
measure real per-request inference cost, not "cost of reloading a model plus
running inference"). Modal's @modal.enter() lifecycle hook loads the model
once per container and @modal.method() reuses it across requests — the
standard pattern for this exact problem.

Checkpoint (config.yaml + .pt, ~1.2GB) is cached in a Modal Volume so cold
starts after the first one don't re-download from HuggingFace every time.

Usage (local test entrypoint — runs the *remote* Modal function):
  modal run pipeline/inference/modal_app.py \
      --composite-path data/output/some_composite.tif --output-path data/output/pred.tiff

Usage (as a library, from pipeline.db.pipeline_step-wrapped orchestration code):
  from pipeline.inference.modal_app import PrithviInference
  pred_bytes = PrithviInference().run.remote(composite_bytes, input_indices=[0, 1, 2, 3, 4, 5])
"""
import modal

app = modal.App("ph-flood-watch-inference")

# Checkpoint cache — survives across container restarts/redeploys, not just
# within one container's lifetime (a modal.Volume, not local container disk).
checkpoint_volume = modal.Volume.from_name("ph-flood-watch-prithvi-checkpoint", create_if_missing=True)
CHECKPOINT_DIR = "/cache/prithvi_checkpoint"

CHECKPOINT_REPO = "ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11"
CHECKPOINT_FILE = "Prithvi-EO-V2-300M-TL-Sen1Floods11.pt"
CONFIG_FILE = "config.yaml"

# rasterio's Linux (manylinux) wheels bundle GDAL statically, same as the
# macOS wheels this repo already relies on (see requirements.txt's comment on
# this) — no system libgdal apt_install needed, confirmed by this image
# actually building/running below.
inference_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch>=2.4", "terratorch>=1.0", "einops>=0.8", "rasterio>=1.4,<2.0",
        "pyyaml", "huggingface_hub", "numpy>=1.26,<2.0",
    )
    .add_local_python_source("pipeline")
)


@app.cls(image=inference_image, gpu="T4", volumes={CHECKPOINT_DIR: checkpoint_volume}, timeout=600)
class PrithviInference:
    @modal.enter()
    def load(self):
        from huggingface_hub import hf_hub_download
        from terratorch.cli_tools import LightningInferenceModel
        import yaml

        config_path = hf_hub_download(repo_id=CHECKPOINT_REPO, filename=CONFIG_FILE, local_dir=CHECKPOINT_DIR)
        checkpoint_path = hf_hub_download(repo_id=CHECKPOINT_REPO, filename=CHECKPOINT_FILE, local_dir=CHECKPOINT_DIR)
        checkpoint_volume.commit()  # persist this container's download for the next one

        self.lightning_model = LightningInferenceModel.from_config(config_path, checkpoint_path)
        self.lightning_model.model.eval()
        with open(config_path) as f:
            self.config_dict = yaml.safe_load(f)
        self.img_size = 512  # sen1floods11 training tile size — see prithvi_inference.py

    @modal.method()
    def run(self, composite_bytes: bytes, input_indices=None) -> bytes:
        """composite_bytes: a 6-band GeoTIFF from pipeline.preprocess.s2_composite,
        in [BLUE, GREEN, RED, NIR_NARROW, SWIR_1, SWIR_2] order (pass
        input_indices=[0,1,2,3,4,5] — that composite already has exactly those
        6 bands, same convention prithvi_inference.py's own header documents).
        Returns the prediction GeoTIFF's raw bytes (uint8, single band)."""
        import tempfile
        from pathlib import Path

        from pipeline.inference.prithvi_inference import (
            _convert_np_uint8,
            load_example,
            run_model,
            save_geotiff,
        )

        with tempfile.TemporaryDirectory() as tmp:
            in_path = Path(tmp) / "composite.tif"
            in_path.write_bytes(composite_bytes)

            input_data, temporal_coords, location_coords, meta_data = load_example(
                file_paths=[str(in_path)], indices=input_indices,
            )
            meta_data = meta_data[0]
            if input_data.mean() > 1:
                input_data = input_data / 10000

            pred = run_model(
                input_data, temporal_coords, location_coords,
                self.lightning_model.model, self.lightning_model.datamodule, self.img_size,
            )

            meta_data.update(count=1, dtype="uint8", compress="lzw", nodata=0)
            out_path = Path(tmp) / "pred.tiff"
            save_geotiff(_convert_np_uint8(pred), str(out_path), meta_data)
            return out_path.read_bytes()


@app.local_entrypoint()
def main(composite_path: str, output_path: str):
    """Local test entrypoint — invokes the *remote* Modal GPU function."""
    from pathlib import Path

    composite_bytes = Path(composite_path).read_bytes()
    print(f"Sending {len(composite_bytes)/1e6:.1f}MB composite to Modal for inference...")
    pred_bytes = PrithviInference().run.remote(composite_bytes, input_indices=[0, 1, 2, 3, 4, 5])
    Path(output_path).write_bytes(pred_bytes)
    print(f"Saved: {output_path} ({len(pred_bytes)/1e6:.2f}MB)")
