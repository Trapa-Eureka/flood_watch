"""Spec §14 step 1: verify the Python environment scaffold.

Checks whether rasterio, GDAL, geopandas, pystac-client, torch, and terratorch
actually import, what version each is, and whether GPU (MPS/CUDA) is usable.
This isn't just "did it install" — it checks "does it actually work".
"""
import importlib
import sys

CHECKS = [
    ("rasterio", None),
    ("geopandas", None),
    ("shapely", None),
    ("pyproj", None),
    ("pystac_client", "pystac-client"),
    ("torch", None),
    ("terratorch", None),
]


def check(module_name: str, display_name: str | None = None) -> tuple[bool, str]:
    display_name = display_name or module_name
    try:
        mod = importlib.import_module(module_name)
        version = getattr(mod, "__version__", "no version info")
        return True, f"OK  {display_name:<16} {version}"
    except Exception as e:  # noqa: BLE001 — during the spike, surfacing the raw cause is useful
        return False, f"FAIL {display_name:<16} {type(e).__name__}: {e}"


def main() -> int:
    print(f"Python: {sys.version}")
    print("-" * 60)
    results = [check(m, d) for m, d in CHECKS]
    for ok, msg in results:
        print(msg)
    print("-" * 60)

    # Separately confirm rasterio actually has GDAL wired up (import success != driver is sane)
    try:
        import rasterio

        print(f"GDAL version linked by rasterio: {rasterio.__gdal_version__}")
    except Exception as e:  # noqa: BLE001
        print(f"Failed to confirm rasterio's GDAL link: {e}")

    # Confirm torch device (MPS on Apple Silicon, otherwise CPU)
    try:
        import torch

        if torch.backends.mps.is_available():
            device = "mps (Apple Silicon GPU)"
        elif torch.cuda.is_available():
            device = f"cuda ({torch.cuda.get_device_name(0)})"
        else:
            device = "cpu"
        print(f"torch device available: {device}")
    except Exception as e:  # noqa: BLE001
        print(f"Failed to confirm torch device: {e}")

    n_fail = sum(1 for ok, _ in results if not ok)
    print("-" * 60)
    if n_fail:
        print(f"{n_fail} failed — check the error messages above and reinstall.")
        return 1
    print("All installs verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
