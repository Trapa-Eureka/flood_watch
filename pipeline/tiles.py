"""Spec §7 tiles.publish: build web-ready Cloud-Optimized GeoTIFFs for the
dashboard's "전후 비교 슬라이더"(pre/post comparison slider, spec.md §Week4)
— an RGB quicklook COG per scene_ref (baseline + post_event) plus a COG of
the flood overlay raster — and upload them to R2's public tiles bucket.

R2 credentials are still not set in this environment (Week 1-4's known gap,
unchanged since) — same graceful-degradation convention as scene_refs.storage_key
and flood_extents.raster_storage_key: build + locally verify every COG (that
part needs no R2 at all), attempt the upload, and continue without one if
credentials are absent rather than blocking. upload_to_r2() itself still
RAISES on missing credentials (mirrors pipeline/stac_client.py's
upload_raw_scene_to_r2 exactly — an upload-only function has no honest
"skip" behavior of its own); publish_event_tiles() is the layer that catches
that and degrades gracefully, matching how every other R2-touching call site
in this project has handled it.
"""
import os
from pathlib import Path
from typing import Optional

import numpy as np

from pipeline import config
from pipeline.preprocess.s2_composite import BAND_ORDER

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# Sentinel-2 L2A surface reflectance DN (BOA_QUANTIFICATION_VALUE=10000, i.e.
# DN/10000 = reflectance) clipped at this point before scaling to uint8 — a
# simple, standard "bright" true-color stretch (most land/water reflectance
# in the visible bands falls well under this even in full sun), NOT a
# radiometrically-calibrated rendering profile. Good enough for a dashboard
# quicklook; a real cartographic product would want per-scene histogram
# stretching instead — noted as a simplification, not fixed here.
RGB_CLIP_DN = 3000


def _rgb_uint8_from_composite(composite_path):
    """BAND_ORDER = [BLUE, GREEN, RED, ...] (pipeline/preprocess/s2_composite.py)
    — bands 1/2/3 in that 1-indexed order. Returns (uint8 (3,H,W) array,
    transform, crs) with composite's own nodata=0 preserved as 0 in the output
    (so a downstream mask/alpha can still tell real-0 from no-data)."""
    import rasterio

    assert BAND_ORDER[:3] == ["BLUE", "GREEN", "RED"]
    with rasterio.open(composite_path) as src:
        blue, green, red = src.read(1), src.read(2), src.read(3)
        transform, crs = src.transform, src.crs

    rgb = np.stack([red, green, blue]).astype("float32")
    nodata_mask = rgb.sum(axis=0) == 0  # composite uses nodata=0 across all bands together
    stretched = np.clip(rgb / RGB_CLIP_DN * 255, 0, 255).astype("uint8")
    stretched[:, nodata_mask] = 0
    return stretched, transform, crs


def build_rgb_cog(composite_path, dst_path) -> Path:
    """RGB quicklook COG (JPEG-compressed — a visual preview, not an analysis
    input, so lossy compression is an acceptable, standard tradeoff for the
    ~3x smaller file it buys for dashboard loading)."""
    import rasterio
    from rasterio.io import MemoryFile
    from rio_cogeo.cogeo import cog_translate
    from rio_cogeo.profiles import cog_profiles

    rgb, transform, crs = _rgb_uint8_from_composite(composite_path)
    dst_path = Path(dst_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    profile = cog_profiles.get("jpeg")
    with MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff", height=rgb.shape[1], width=rgb.shape[2], count=3,
            dtype="uint8", crs=crs, transform=transform, nodata=0,
        ) as mem_ds:
            mem_ds.write(rgb)
        # cog_translate wants a read-only source (rasterio deprecation
        # warning otherwise, will be a hard error in a future rasterio) — the
        # write-mode dataset above must be closed (the `with` block exited)
        # before reopening the same in-memory buffer for reading.
        with memfile.open() as mem_ds:
            cog_translate(mem_ds, dst_path, profile, add_mask=True, web_optimized=True, quiet=True)

    return dst_path


def build_single_band_cog(raster_path, dst_path) -> Path:
    """COG for the flood overlay raster (or any single-band analysis raster) —
    lossless (DEFLATE), unlike build_rgb_cog: this holds WATER_VALUE/
    CLOUD_MASKED_VALUE class codes, not a picture, so exact values matter."""
    from rio_cogeo.cogeo import cog_translate
    from rio_cogeo.profiles import cog_profiles

    dst_path = Path(dst_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    profile = cog_profiles.get("deflate")
    cog_translate(str(raster_path), dst_path, profile, add_mask=True, web_optimized=True, quiet=True)
    return dst_path


def upload_to_r2(local_path, key: str, bucket: Optional[str] = None) -> str:
    """Same pattern as pipeline/stac_client.py's upload_raw_scene_to_r2 —
    fails loudly on missing credentials rather than silently no-op'ing,
    because upload IS this function's entire job."""
    import boto3

    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        raise RuntimeError(
            "R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY not found in .env — mint them from the "
            "Cloudflare dashboard, see .env.example (same gap as scene_refs/flood_extents)."
        )

    bucket = bucket or config.R2_BUCKET_TILES
    s3 = boto3.client(
        "s3", endpoint_url=config.R2_ENDPOINT_URL,
        aws_access_key_id=access_key, aws_secret_access_key=secret_key,
    )
    s3.upload_file(str(local_path), bucket, key)
    return key


def publish_event_tiles(event_id: str, pre_composite_path=None, post_composite_path=None,
                         flood_raster_path=None, out_dir=None) -> dict:
    """Build whatever COGs are available for this event (any subset of
    pre/post/flood — a real event may lack a clean baseline scene, see
    scene_refs.role='baseline' rows with ok=False from Week 1-5/1-8) and
    attempt to publish each to R2. Returns
    {"pre": {"local_path", "r2_key"} | None, "post": {...} | None, "flood": {...} | None}
    — r2_key is None (not an error) whenever R2 credentials are absent.
    """
    out_dir = Path(out_dir) if out_dir else config.DATA_OUTPUT_DIR / "tiles" / event_id
    results = {}

    jobs = [
        ("pre", pre_composite_path, build_rgb_cog, "pre_rgb.tif"),
        ("post", post_composite_path, build_rgb_cog, "post_rgb.tif"),
        ("flood", flood_raster_path, build_single_band_cog, "flood_overlay.tif"),
    ]
    for label, src_path, builder, filename in jobs:
        if src_path is None:
            results[label] = None
            continue
        dst_path = out_dir / filename
        builder(src_path, dst_path)
        size_mb = dst_path.stat().st_size / 1e6
        print(f"  tiles: built {label} COG {dst_path} ({size_mb:.2f}MB)")

        r2_key = None
        try:
            r2_key = upload_to_r2(dst_path, f"{event_id}/{filename}")
            print(f"  tiles: uploaded {label} -> r2://{config.R2_BUCKET_TILES}/{event_id}/{filename}")
        except RuntimeError as e:
            print(f"  tiles: {label} R2 upload skipped ({e})")

        results[label] = {"local_path": str(dst_path), "r2_key": r2_key}

    return results
