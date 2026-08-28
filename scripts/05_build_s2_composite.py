"""Build a 6-band Sentinel-2 L2A composite over the Marikina AOI, in the exact
band order Prithvi's sen1floods11 checkpoint expects: BLUE, GREEN, RED,
NIR_NARROW, SWIR_1, SWIR_2 (see scripts/03_load_prithvi's discovery that this
checkpoint is optical, not SAR).

Unlike Sentinel-1 GRD, Sentinel-2 L2A tiles already carry a real CRS + affine
transform (UTM, orthorectified) — so a plain bbox crop is valid here, no GCP
approximation needed like in scripts/04_aoi_crop_compare.py.

Downloads each band via the STAC item's assets[band].extra_fields['alternate']
['https']['href'] (an OAuth2-authenticated HTTPS mirror of the S3 object,
confirmed to exist on CDSE's Sentinel-2 STAC responses), crops each band to the
AOI window, resamples the 20m bands up to the 10m grid, and stacks them.

Usage:
  python scripts/05_build_s2_composite.py --item-id <stac_item_id> --output out.tif
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# Model's expected band order -> STAC asset key
BAND_ASSET_MAP = {
    "BLUE": "B02_10m",
    "GREEN": "B03_10m",
    "RED": "B04_10m",
    "NIR_NARROW": "B8A_20m",
    "SWIR_1": "B11_20m",
    "SWIR_2": "B12_20m",
}
BAND_ORDER = ["BLUE", "GREEN", "RED", "NIR_NARROW", "SWIR_1", "SWIR_2"]


def get_access_token() -> str:
    import requests

    username = os.environ.get("CDSE_USERNAME")
    password = os.environ.get("CDSE_PASSWORD")
    if not username or not password:
        raise RuntimeError("CDSE_USERNAME/CDSE_PASSWORD not set in .env")
    resp = requests.post(
        config.CDSE_TOKEN_URL,
        data={
            "client_id": config.CDSE_PUBLIC_CLIENT_ID,
            "username": username,
            "password": password,
            "grant_type": "password",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_item(item_id: str):
    from pystac_client import Client

    catalog = Client.open(config.CDSE_STAC_URL)
    items = list(catalog.search(collections=[config.SENTINEL2_COLLECTION], ids=[item_id]).items())
    if not items:
        raise RuntimeError(f"STAC item not found: {item_id}")
    return items[0]


def download_band(item, band_key: str, token: str, out_dir: Path) -> Path:
    import requests

    asset = item.assets[band_key]
    https_href = asset.extra_fields.get("alternate", {}).get("https", {}).get("href")
    if not https_href:
        raise RuntimeError(f"No HTTPS alternate href for asset {band_key}")

    out_path = out_dir / f"{item.id}_{band_key}.jp2"
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  {band_key}: already downloaded, skipping")
        return out_path

    out_dir.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"}
    with requests.get(https_href, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        written = 0
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                written += len(chunk)
        print(f"  {band_key}: downloaded {written/1e6:.1f}MB")
    return out_path


def compute_aoi_window(ref_band_path: Path, bbox, pad_ratio: float):
    """Compute the target grid (transform, height, width, crs) for an AOI bbox,
    anchored to *ref_band_path*'s own resolution/grid. Shared by the composite
    builder and scripts/06_apply_cloud_mask.py so both align to the identical
    pixel grid — pass the same ref band, bbox, and pad_ratio in both places.
    """
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    with rasterio.open(ref_band_path) as ref:
        target_crs = ref.crs
        west, south, east, north = bbox
        w, h = east - west, north - south
        west, east = west - w * pad_ratio, east + w * pad_ratio
        south, north = south - h * pad_ratio, north + h * pad_ratio
        proj_bounds = transform_bounds("EPSG:4326", target_crs, west, south, east, north)
        window = from_bounds(*proj_bounds, transform=ref.transform).round_lengths().round_offsets()
        window = window.intersection(rasterio.windows.Window(0, 0, ref.width, ref.height))
        target_transform = ref.window_transform(window)
        target_h, target_w = int(window.height), int(window.width)
    return target_transform, target_h, target_w, target_crs


def read_band_at_target(band_path: Path, target_transform, target_h: int, target_w: int, resampling):
    """Read *band_path* resampled onto the (target_transform, target_h, target_w) grid,
    regardless of the band's own native resolution/grid offset."""
    import rasterio
    from rasterio.windows import from_bounds

    with rasterio.open(band_path) as src:
        corner_a = target_transform * (0, 0)
        corner_b = target_transform * (target_w, target_h)
        win = from_bounds(
            min(corner_a[0], corner_b[0]), min(corner_a[1], corner_b[1]),
            max(corner_a[0], corner_b[0]), max(corner_a[1], corner_b[1]),
            transform=src.transform,
        )
        return src.read(1, window=win, out_shape=(target_h, target_w), resampling=resampling)


def build_composite(band_paths: dict, bbox, pad_ratio: float, out_path: Path):
    from rasterio.enums import Resampling

    # Use the 10m BLUE band to define the target grid (highest resolution we have).
    target_transform, target_h, target_w, target_crs = compute_aoi_window(
        band_paths["BLUE"], bbox, pad_ratio
    )

    stack = np.zeros((len(BAND_ORDER), target_h, target_w), dtype="uint16")
    for i, band_name in enumerate(BAND_ORDER):
        # 20m bands are resampled (bilinear) onto the shared 10m target grid.
        stack[i] = read_band_at_target(
            band_paths[band_name], target_transform, target_h, target_w, Resampling.bilinear
        )
        print(f"  stacked {band_name} ({band_paths[band_name].name})")

    import rasterio

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        out_path, "w", driver="GTiff", height=target_h, width=target_w, count=len(BAND_ORDER),
        dtype="uint16", crs=target_crs, transform=target_transform, nodata=0,
    ) as dst:
        dst.write(stack)
        for i, name in enumerate(BAND_ORDER, start=1):
            dst.set_band_description(i, name)
    print(f"Saved composite: {out_path}  ({target_w}x{target_h}, {len(BAND_ORDER)} bands)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pad-ratio", type=float, default=0.0)
    parser.add_argument("--band-cache-dir", default=str(config.DATA_RAW_DIR / "s2_bands"))
    args = parser.parse_args()

    item = fetch_item(args.item_id)
    print(f"Item: {item.id}  acquired={item.datetime}  cloud_cover={item.properties.get('eo:cloud_cover')}")

    token = get_access_token()
    band_cache = Path(args.band_cache_dir)

    band_paths = {}
    for band_name, asset_key in BAND_ASSET_MAP.items():
        print(f"Downloading {band_name} ({asset_key})...")
        band_paths[band_name] = download_band(item, asset_key, token, band_cache)

    build_composite(band_paths, config.AOI_BBOX, args.pad_ratio, Path(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
