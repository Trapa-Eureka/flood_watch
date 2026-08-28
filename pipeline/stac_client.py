"""Spec §14 step 2: search and download Sentinel-1 GRD scenes for the Marikina AOI
from the Copernicus Data Space Ecosystem STAC, before/after Kristine/Trami (2024-10).

How it works:
  1) STAC catalog search works without authentication (public catalog) — no .env
     needed if you only want to inspect result metadata.
  2) Downloading the actual asset (.SAFE) requires a CDSE account (OAuth2 password
     grant) — if CDSE_USERNAME/CDSE_PASSWORD aren't in .env, only the search runs
     and the download is skipped.

Usage:
  python -m pipeline.stac_client --search-only   # inspect search results only, no auth needed
  python -m pipeline.stac_client                 # actually download, using .env credentials
"""
import argparse
import json
import os
from pathlib import Path

from pipeline import config

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def search_items(pre_start, pre_end, post_start, post_end, bbox, collection, max_items):
    """STAC search. No authentication required (public catalog read)."""
    from pystac_client import Client

    catalog = Client.open(config.CDSE_STAC_URL)

    def _search(dt_start, dt_end, role):
        search = catalog.search(
            collections=[collection],
            bbox=bbox,
            datetime=f"{dt_start}T00:00:00Z/{dt_end}T23:59:59Z",
            max_items=max_items,
        )
        items = list(search.items())
        print(f"[{role}] {dt_start} ~ {dt_end}: {len(items)} scene(s)")
        for it in items:
            print(f"  - {it.id}  acquired={it.datetime}  bbox={it.bbox}")
        return items

    pre_items = _search(pre_start, pre_end, "baseline(pre)")
    post_items = _search(post_start, post_end, "post_event")
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
    args = parser.parse_args()

    print(f"AOI bbox: {config.AOI_BBOX}  (approximate — see config.py comments)")

    pre_items, post_items = search_items(
        args.pre_start, args.pre_end, args.post_start, args.post_end,
        config.AOI_BBOX, args.collection, args.max_items,
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
