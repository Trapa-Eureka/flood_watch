"""Week 2-1: confirm Modal auth + actual deployment/execution work (not just
`modal setup`'s token handshake) — a plain function first, then a GPU-attached
one, since GPU access is the entire point of using Modal here (spec.md §5:
Prithvi inference needs a real GPU).

This is deliberately NOT part of the production pipeline (kept in tools/, not
pipeline/) — 2-2 builds the real Prithvi-on-Modal app; this is just a smoke
test to point at when something about the Modal setup itself looks broken.

Usage:
  modal run tools/modal_smoke_test.py
"""
import modal

app = modal.App("ph-flood-watch-smoke-test")

# The default Modal image is minimal Python — torch has to be installed
# explicitly for the GPU check below (2-2's real Prithvi image will need a lot
# more than this: terratorch, rasterio, the checkpoint itself, etc.).
torch_image = modal.Image.debian_slim().pip_install("torch")


@app.function()
def hello() -> str:
    return "hello from a Modal container (CPU)"


@app.function(gpu="T4", image=torch_image)
def gpu_check() -> dict:
    import torch

    return {
        "cuda_available": torch.cuda.is_available(),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "torch_version": torch.__version__,
    }


@app.local_entrypoint()
def main():
    print(hello.remote())
    print(gpu_check.remote())
