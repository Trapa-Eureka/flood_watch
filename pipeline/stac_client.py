"""Spec §7 scenes.fetch: STAC search for an event's AOI, done two ways.

Sentinel-2 L2A (PRIMARY — spec.md §2/§8): candidate search over a date window,
then pick the best scene by *AOI-local* cloud cover (the SCL band, read only
over the AOI window) — not the STAC item's tile-wide `eo:cloud_cover`, which
the 2026-08-28 backtests (docs/design-notes.md) proved unreliable at AOI scale:
a tile can be mostly clear while the one AOI corner you actually care about is
completely clouded over, or vice versa. See fetch_best_s2_scenes().

Sentinel-1 GRD (secondary — spec.md §2/§8, kept for future SAR use): plain
search + download, unchanged from the original spike. SAR doesn't need cloud
selection at all (that's the whole point of radar). See search_items()/
download_item().

AOI is a plain bbox parameter throughout, not hardcoded — any function here
works for any event's AOI (2026-08-28 "AOI is free-form per event" decision,
docs/design-notes.md), including the 4 watch_priority basins as a special case.

Usage:
  python -m pipeline.stac_client --search-only                        # S1: inspect results only
  python -m pipeline.stac_client                                      # S1: search + download
  python -m pipeline.stac_client --collection sentinel-2-l2a          # S2: search + local-cloud select
  python -m pipeline.stac_client --collection sentinel-2-l2a --upload-r2   # ...+ upload winners to R2
"""
import argparse
import json
import os
from pathlib import Path

from pipeline import config

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

DEFAULT_MAX_LOCAL_CLOUD_PCT = 30.0


def search_window(bbox, date_start, date_end, collection, max_items, role_label=None):
    """One STAC search over [date_start, date_end] for *collection*. No
    authentication required (public catalog read). Shared by both the S1 and
    S2 paths below."""
    from pystac_client import Client

    catalog = Client.open(config.CDSE_STAC_URL)
    search = catalog.search(
        collections=[collection],
        bbox=bbox,
        datetime=f"{date_start}T00:00:00Z/{date_end}T23:59:59Z",
        max_items=max_items,
    )
    items = list(search.items())
    label = f"[{role_label}] " if role_label else ""
    print(f"{label}{date_start} ~ {date_end}: {len(items)} scene(s)")
    for it in items:
        print(f"  - {it.id}  acquired={it.datetime}  tile_cloud={it.properties.get('eo:cloud_cover')}%  bbox={it.bbox}")
    return items


def search_items(pre_start, pre_end, post_start, post_end, bbox, collection, max_items):
    """Sentinel-1 path: search baseline + post_event windows. No cloud
    selection — SAR sees through clouds, so the first candidate(s) are fine."""
    pre_items = search_window(bbox, pre_start, pre_end, collection, max_items, "baseline(pre)")
    post_items = search_window(bbox, post_start, post_end, collection, max_items, "post_event")
    return pre_items, post_items


def get_access_token() -> str | None:
    username = os.environ.get("CDSE_USERNAME")
    password = os.environ.get("CDSE_PASSWORD")
    if not username or not password:
        return None

    import requests

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


def download_item(item, token: str, out_dir: Path) -> Path | None:
    """Download via the STAC item's assets['Product'] href (OData zipper, full .SAFE zip).

    Confirmed by testing: for the CDSE STAC's `_COG` collection, item.assets already
    contains a ready-to-use download URL under the 'Product' key (domain is
    download.dataspace.copernicus.eu — an earlier guess of zipper.* was wrong, fixed
    after seeing the actual STAC response). Only fall back to a name-based OData
    search when this asset is absent.
    """
    import requests

    product_name = item.id
    download_url = None

    product_asset = item.assets.get("Product") if hasattr(item, "assets") else None
    if product_asset is not None:
        download_url = product_asset.href
        print(f"  Got download URL from STAC asset: {download_url}")

    if download_url is None:
        # Fallback: name-based OData search (older STAC responses, or no Product asset)
        filter_name = product_name if product_name.endswith(".SAFE") else f"{product_name}.SAFE"
        odata_search = (
            f"{config.CDSE_ODATA_URL}/Products?$filter=Name eq '{filter_name}'&$top=1"
        )
        r = requests.get(odata_search, timeout=30)
        r.raise_for_status()
        values = r.json().get("value", [])
        if not values:
            print(f"  ! Could not find {filter_name} in OData — skipping")
            return None
        product_id = values[0]["Id"]
        download_url = f"{config.CDSE_ZIPPER_URL}/Products({product_id})/$value"

    out_path = out_dir / f"{product_name}.zip"
    out_dir.mkdir(parents=True, exist_ok=True)

    headers = {"Authorization": f"Bearer {token}"}
    with requests.get(download_url, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        written = 0
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                written += len(chunk)
        print(f"  ✓ {out_path.name} ({written/1e6:.1f}MB / expected {total/1e6:.1f}MB)")
    return out_path


# ---------------------------------------------------------------------------
# Sentinel-2 L2A: candidate search + AOI-local cloud selection (primary path)
# ---------------------------------------------------------------------------

def local_cloud_cover_pct(item, bbox, pad_ratio=0.05, band_cache_dir=None) -> float:
    """AOI-local cloud fraction (0-100) via the SCL band, cropped to *bbox* —
    downloads only the SCL asset (smallest band, 20m), not the full 6-band set,
    so checking a losing candidate is cheap. Reuses
    pipeline.preprocess.s2_composite's band-download/grid-alignment helpers and
    pipeline.preprocess.cloud_mask's SCL class definitions, so this number is
    computed the exact same way preprocess.run will mask the final prediction —
    no risk of the selection criterion drifting from the actual masking logic.
    """
    import numpy as np
    from rasterio.enums import Resampling

    from pipeline.preprocess import cloud_mask, s2_composite

    band_cache_dir = Path(band_cache_dir) if band_cache_dir else config.DATA_RAW_DIR / "s2_bands"
    token = s2_composite.get_access_token()
    scl_path = s2_composite.download_band(item, cloud_mask.SCL_ASSET_KEY, token, band_cache_dir)

    # SCL itself is a valid georeferenced raster, so it can serve as its own
    # grid reference here — no need for the 10m BLUE band just for a cloud check.
    target_transform, target_h, target_w, _ = s2_composite.compute_aoi_window(scl_path, bbox, pad_ratio)
    scl = s2_composite.read_band_at_target(scl_path, target_transform, target_h, target_w, Resampling.nearest)

    cloudy = np.isin(scl, list(cloud_mask.CLOUD_SCL_CLASSES))
    return 100.0 * cloudy.sum() / cloudy.size


def select_best_scene(candidates, bbox, pad_ratio=0.05,
                       max_local_cloud_pct=DEFAULT_MAX_LOCAL_CLOUD_PCT, band_cache_dir=None) -> dict:
    """Check candidates' AOI-local cloud cover, cheapest-looking first (sorted
    by the STAC item's own tile-wide eo:cloud_cover ascending, as a heuristic
    to minimize wasted SCL downloads — not trusted as the actual answer, see
    local_cloud_cover_pct's docstring). Returns the first one under threshold.

    If none qualify, returns the least-cloudy one anyway with ok=False — the
    caller decides whether to widen the date window and retry (this function
    stays a pure "evaluate what I was given" step, no networking-retry logic
    baked in, so it composes cleanly either way).
    """
    ranked = sorted(candidates, key=lambda it: it.properties.get("eo:cloud_cover", 100))
    checked = []
    for item in ranked:
        pct = local_cloud_cover_pct(item, bbox, pad_ratio, band_cache_dir)
        print(f"  {item.id}  tile_cloud={item.properties.get('eo:cloud_cover')}%  AOI_local_cloud={pct:.1f}%")
        checked.append((item, pct))
        if pct <= max_local_cloud_pct:
            return {"item": item, "local_cloud_pct": pct, "ok": True}

    if not checked:
        return {"item": None, "local_cloud_pct": None, "ok": False}
    best_item, best_pct = min(checked, key=lambda pair: pair[1])
    print(f"  ! No candidate under {max_local_cloud_pct}% AOI-local cloud — "
          f"best available: {best_item.id} ({best_pct:.1f}%)")
    return {"item": best_item, "local_cloud_pct": best_pct, "ok": False}


def fetch_best_s2_scenes(bbox, pre_start, pre_end, post_start, post_end,
                          max_local_cloud_pct=DEFAULT_MAX_LOCAL_CLOUD_PCT,
                          max_items=10, band_cache_dir=None) -> dict:
    """The scenes.fetch entry point for S2 (spec.md §7): search + select the
    best baseline and post_event scene independently. Returns
    {"baseline": select_best_scene()'s dict | None, "post_event": ...} —
    None only when the search itself returned zero candidates."""
    out = {}
    for role, (d_start, d_end) in (("baseline", (pre_start, pre_end)), ("post_event", (post_start, post_end))):
        candidates = search_window(bbox, d_start, d_end, config.SENTINEL2_COLLECTION, max_items, role)
        if not candidates:
            out[role] = None
            continue
        out[role] = select_best_scene(
            candidates, bbox, max_local_cloud_pct=max_local_cloud_pct, band_cache_dir=band_cache_dir
        )
    return out


def download_scene_bands(item, band_cache_dir=None) -> dict:
    """Download the winning scene's 6 model bands (spec.md §7 scenes.fetch —
    the SCL band is usually already cached from local_cloud_cover_pct's check).
    Thin wrapper around preprocess.s2_composite.download_all_bands (Week 1-6:
    that's now the one place that knows "the 6 bands", not two copies)."""
    from pipeline.preprocess import s2_composite

    band_cache_dir = Path(band_cache_dir) if band_cache_dir else config.DATA_RAW_DIR / "s2_bands"
    return s2_composite.download_all_bands(item, band_cache_dir)


def upload_raw_scene_to_r2(item, band_paths: dict, bucket: str | None = None) -> dict:
    """Upload the downloaded raw band files to the R2 raw-scenes bucket (spec.md
    §5 architecture: 'R2 원본 저장' immediately follows scene selection). Returns
    {band_name: r2_object_key}.

    Needs R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY in .env — these can only be
    minted from the Cloudflare dashboard (Week 1-4, docs/design-notes.md), not
    via any CLI, so this raises a clear, actionable error rather than silently
    skipping (unlike the CDSE download path, which degrades gracefully since
    search-only is a legitimate mode — there's no equivalent "upload-only
    doesn't matter" mode here, so failing loudly is more honest).
    """
    import boto3

    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        raise RuntimeError(
            "R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY not found in .env — mint them from the "
            "Cloudflare dashboard (R2 -> Manage API Tokens -> Create API Token, scoped to "
            f"{config.R2_BUCKET_RAW} + {config.R2_BUCKET_TILES}, Object Read & Write), see .env.example."
        )

    bucket = bucket or config.R2_BUCKET_RAW
    s3 = boto3.client(
        "s3",
        endpoint_url=config.R2_ENDPOINT_URL,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    uploaded = {}
    for band_name, path in band_paths.items():
        path = Path(path)
        key = f"{item.id}/{path.name}"
        s3.upload_file(str(path), bucket, key)
        uploaded[band_name] = key
        print(f"  uploaded {band_name} -> r2://{bucket}/{key}")
    return uploaded


def _run_s2(args, bbox):
    """S2 L2A path: search + AOI-local-cloud select, optionally download the
    winners' bands and/or upload them to R2."""
    result = fetch_best_s2_scenes(
        bbox, args.pre_start, args.pre_end, args.post_start, args.post_end,
        max_local_cloud_pct=args.max_local_cloud_pct, max_items=args.max_items,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        role: (
            None if r is None else
            {"item_id": r["item"].id if r["item"] else None,
             "acquired": str(r["item"].datetime) if r["item"] else None,
             "local_cloud_pct": r["local_cloud_pct"], "ok": r["ok"]}
        )
        for role, r in result.items()
    }
    meta_path = out_dir / "s2_selection_result.json"
    meta_path.write_text(json.dumps(summary, indent=2))
    print(f"Saved selection result: {meta_path}")
    for role, r in summary.items():
        print(f"[{role}] {r}")

    if args.search_only:
        print("--search-only set — skipping band download.")
        return 0

    for role, r in result.items():
        if r is None or r["item"] is None:
            print(f"[{role}] no usable scene — skipping download")
            continue
        print(f"[{role}] downloading bands for {r['item'].id}...")
        band_paths = download_scene_bands(r["item"])
        if args.upload_r2:
            upload_raw_scene_to_r2(r["item"], band_paths)

    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-start", default=config.PRE_EVENT_START)
    parser.add_argument("--pre-end", default=config.PRE_EVENT_END)
    parser.add_argument("--post-start", default=config.POST_EVENT_START)
    parser.add_argument("--post-end", default=config.POST_EVENT_END)
    parser.add_argument("--collection", default=config.SENTINEL1_COLLECTION)
    parser.add_argument("--max-items", type=int, default=5)
    parser.add_argument("--search-only", action="store_true", help="search only, no download")
    parser.add_argument("--out-dir", default=str(config.DATA_RAW_DIR))
    parser.add_argument(
        "--bbox", type=float, nargs=4, default=None, metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        help="AOI override, EPSG:4326. Defaults to config.AOI_BBOX (per the 2026-08-28 "
             "'AOI is free-form per event' decision — see docs/design-notes.md).",
    )
    parser.add_argument(
        "--max-local-cloud-pct", type=float, default=DEFAULT_MAX_LOCAL_CLOUD_PCT,
        help="S2 only: max acceptable AOI-local cloud %% before falling back to 'best available'.",
    )
    parser.add_argument(
        "--upload-r2", action="store_true",
        help="S2 only: after downloading the winning scenes' bands, upload them to "
             f"the {config.R2_BUCKET_RAW!r} R2 bucket (needs R2_ACCESS_KEY_ID/SECRET in .env).",
    )
    args = parser.parse_args()
    bbox = tuple(args.bbox) if args.bbox else config.AOI_BBOX

    print(f"AOI bbox: {bbox}")

    if args.collection == config.SENTINEL2_COLLECTION:
        return _run_s2(args, bbox)

    pre_items, post_items = search_items(
        args.pre_start, args.pre_end, args.post_start, args.post_end,
        bbox, args.collection, args.max_items,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "search_results.json"
    meta_path.write_text(
        json.dumps(
            {
                "baseline": [it.to_dict() for it in pre_items],
                "post_event": [it.to_dict() for it in post_items],
            },
            indent=2,
            default=str,
        )
    )
    print(f"Saved search result metadata: {meta_path}")

    if args.search_only:
        print("--search-only set — skipping download.")
        return 0

    token = get_access_token()
    if not token:
        print(
            "\n! CDSE_USERNAME/CDSE_PASSWORD not found in .env — skipping download.\n"
            "  Copy .env.example to .env and fill it in with your https://dataspace.copernicus.eu "
            "account, then re-run."
        )
        return 0

    for role, items in (("baseline", pre_items), ("post_event", post_items)):
        role_dir = out_dir / role
        for item in items[: args.max_items]:
            print(f"Downloading: [{role}] {item.id}")
            try:
                download_item(item, token, role_dir)
            except Exception as e:  # noqa: BLE001
                print(f"  ! Download failed: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
