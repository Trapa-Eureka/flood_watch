"""Spec §6/§8 admin_boundaries: load ADM3/ADM4 reference boundaries.

Shared by Week 3-1 (ADM3, tools/load_adm3_boundaries.py) and Week 3-2 (ADM4) —
both are "read a GeoJSON FeatureCollection, normalize each feature's geometry
to MultiPolygon/WKT, POST in batches" with only the field names and
source/vintage differing.

CLAUDE.md rule (spec.md §13): admin_boundaries always carries source+vintage —
enforced at the DB level too (NOT NULL, see supabase/migrations). This module
requires both as explicit arguments; there is no default that could silently
produce "source unknown" rows.
"""
import json
import os
import time
from pathlib import Path
from typing import Optional

import requests

from pipeline import config

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

BATCH_SIZE = 100  # feature-count cap, but see MAX_BATCH_BYTES — PH coastal
# municipalities vary wildly in geometry complexity (Palawan's Taytay alone is
# ~11MB of WKT text for one feature — verified live while loading ADM3), so a
# fixed feature count alone isn't a safe batch boundary.
MAX_BATCH_BYTES = 3_000_000  # ~3MB of WKT text per POST body, whichever cap hits first


def _headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY not found in .env — see .env.example.")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # bulk load, upsert on (level, psgc_code) — same idempotency pattern as
        # scene_refs.record_scene_ref (Week 1-8): makes a re-run after a
        # transient network error (Cloudflare 502s on a large-payload batch,
        # observed live loading ADM3) safe to just retry from the top instead
        # of needing manual partial-load cleanup.
        "Prefer": "return=minimal,resolution=merge-duplicates",
    }


# Simplification tolerance in degrees (~11m at PH's latitudes) — chosen to
# match Sentinel-2's own 10m pixel resolution, since exposure.compute (Week
# 3-6) intersects these boundaries against a flood polygon that's already
# only as precise as a 10m raster; sub-meter coastline vertices carry no real
# information for that math. Also a practical necessity, not just a nicety:
# discovered live loading ADM3 that a handful of Palawan/Surigao municipalities
# (hundreds of small islands each) produce 5-11MB of *raw* WKT text for a
# single feature, which reliably 502'd through Supabase's edge — simplifying
# at this tolerance cuts Taytay, Palawan (the worst case) from 11.1M to 504K
# characters (22x smaller) for a 0.005% area error, see docs/design-notes.md.
SIMPLIFY_TOLERANCE_DEG = 0.0001


def _to_multipolygon_wkt(geojson_geom: dict, simplify_tolerance: float = SIMPLIFY_TOLERANCE_DEG) -> str:
    from shapely.geometry import MultiPolygon, Polygon, shape

    geom = shape(geojson_geom)
    if simplify_tolerance:
        geom = geom.simplify(simplify_tolerance, preserve_topology=True)
    if isinstance(geom, Polygon):
        geom = MultiPolygon([geom])
    return geom.wkt


def load_boundaries(geojson_path: Path, level: str, name_field: str, pcode_field: Optional[str],
                     source: str, vintage: str, batch_size: int = BATCH_SIZE, max_retries: int = 3) -> int:
    """level: 'adm3_municipality' | 'adm4_barangay' (matches the DB CHECK constraint).
    vintage: 'YYYY-MM-DD' string.
    Returns the number of rows upserted.

    NOTE: on_conflict=(level, psgc_code) upsert only dedupes correctly when
    psgc_code is non-null for every feature (true for ADM3 here — all 1642
    have unique codes, verified against the actual downloaded file, not the
    HDX page's summary). If a future ADM4 load has features with a null
    psgc_code, Postgres treats each NULL as distinct, so upsert alone won't
    prevent duplicates for those specific rows — worth re-checking when 3-2
    actually loads ADM4 data.
    """
    url = f"{config.SUPABASE_URL}/rest/v1/admin_boundaries"
    data = json.loads(Path(geojson_path).read_text())
    features = data["features"]
    print(f"Loaded {len(features)} features from {geojson_path.name}")

    # Build each row + its WKT byte size up front, then group into batches
    # capped by BOTH feature count and cumulative WKT size (see MAX_BATCH_BYTES).
    sized_rows = []
    for f in features:
        props = f["properties"]
        wkt = _to_multipolygon_wkt(f["geometry"])
        row = {
            "level": level,
            "name": props[name_field],
            "psgc_code": props.get(pcode_field) if pcode_field else None,
            "geom": wkt,
            "source": source,
            "vintage": vintage,
        }
        sized_rows.append((row, len(wkt)))

    total = 0
    batch, batch_bytes = [], 0
    batches = []
    for row, wkt_len in sized_rows:
        if batch and (len(batch) >= batch_size or batch_bytes + wkt_len > MAX_BATCH_BYTES):
            batches.append(batch)
            batch, batch_bytes = [], 0
        batch.append(row)
        batch_bytes += wkt_len
    if batch:
        batches.append(batch)

    for rows in batches:
        for attempt in range(1, max_retries + 1):
            resp = requests.post(
                url, headers=_headers(), params={"on_conflict": "level,psgc_code"}, json=rows, timeout=120,
            )
            if resp.status_code < 400:
                break
            if resp.status_code >= 500 and attempt < max_retries:
                wait_s = 2 * attempt
                print(f"  batch of {len(rows)}: {resp.status_code} (attempt {attempt}/{max_retries}), retrying in {wait_s}s...")
                time.sleep(wait_s)
                continue
            raise RuntimeError(f"admin_boundaries batch insert failed ({resp.status_code}): {resp.text[:500]}")

        total += len(rows)
        print(f"  upserted {total}/{len(features)}  (batch size {len(rows)})")

    return total
