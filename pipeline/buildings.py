"""Spec §7/§8 exposure.compute input: building footprints, used (Week 3-6) to
estimate est_buildings_affected. Source decision (OSM vs. Google Open
Buildings, spec.md §Week3 3-4) below — verified live against real data for
two very different AOIs before deciding, not from memory/reputation.

## Decision: Google Open Buildings (via VIDA's merged GeoParquet), not OSM

Both sources were live-queried for the *same two real AOIs already used
throughout this project* — Marikina (dense Metro Manila, config.MARIKINA_CITY_BBOX,
~42.2 km^2) and the Cagayan Valley backtest AOI (rural/riverine,
data/output/cagayan_inference/*.tiff bounds, ~1431 km^2) — 2026-08-29:

| AOI              | OSM (Overpass, building ways) | Google+MS (VIDA parquet)     | G+MS / OSM |
|-------------------|-------------------------------|-------------------------------|------------|
| Marikina (urban)  | 100,063  (2,371/km^2)         | 156,939  (3,719/km^2)         | 1.57x      |
| Cagayan (rural)    | 120,722  (84/km^2)             | 245,141  (171/km^2)           | 2.03x      |

The gap between the two sources is NOT constant — it roughly DOUBLES in the
rural/riverine AOI vs. the dense urban one. That is exactly the pattern you'd
expect if OSM's completeness depends on local community mapping activity
(high in Metro Manila, much lower in rural Cagayan Valley) while an ML
detection model gives more geographically uniform coverage. Since this
project's whole premise is flood monitoring anywhere in the Philippines (spec
§1: AOI is freely assignable, not fixed to well-mapped cities) and flood risk
skews toward exactly the kind of rural/riverine areas where OSM is sparsest,
uniform national coverage matters more here than OSM's per-feature curation.

Practical factors that also favored this choice:
- VIDA's dataset (https://source.coop/vida/google-microsoft-open-buildings)
  merges Google's V3 Open Buildings *and* Microsoft's GlobalMLBuildingFootprints,
  deduplicated, one GeoParquet per country (`country_iso=PHL/PHL.parquet`,
  verified live: 4.80GB, HTTP Accept-Ranges: bytes). A DuckDB httpfs+spatial
  bbox-pushdown query (below) reads only the needed row groups — verified live
  at ~16-33s for AOIs from 42 km^2 to 1431 km^2, no local download of the
  4.8GB file needed. Same "remote windowed read" pattern as JRC
  (pipeline/baseline_diff.py), just via Parquet row-group stats instead of
  /vsicurl/ GeoTIFF windows.
- `confidence` (Google detections only; null for Microsoft's) lets false
  positives be filtered down — OSM has no per-feature confidence signal.
- Not stored in Postgres: unlike admin_boundaries, there is no `buildings`
  table in spec.md §6's schema — exposure_stats only needs an aggregate count/
  area per event, so persisting millions of individual footprints nationwide
  would be schema-inconsistent AND unnecessary. This module fetches on demand
  per-AOI (Week 3-6 call site), the same way baseline_diff.py fetches JRC.

Honest caveats (documented, not hidden — same discipline as JRC's Week 2-5
"only partially explains false positives" writeup):
- No building type/use attribute (can't distinguish residential/commercial/
  government) — OSM tags can carry this where mapped, this dataset can't.
- ML-detection vintage: Google V3 trained on imagery "in 2021/2022/2023"
  (per Google's own page), Microsoft's "collected between 2014 and 2023" (per
  VIDA's README) — construction from 2023 onward will be systematically
  under-counted. No fix planned; flagged for whoever revisits this dataset.
- `confidence` threshold used here (0.5, DEFAULT_MIN_CONFIDENCE below) is a
  single flat cutoff. Google publishes region-specific recommended thresholds
  (score_thresholds_s2_level_4.csv) since detector calibration varies by
  region/imagery quality — using a flat 0.5 for the whole country is a known
  simplification, not re-derived per-region here.
"""
from pathlib import Path

from pipeline import config

VIDA_BUILDINGS_URL = (
    "https://data.source.coop/vida/google-microsoft-open-buildings/"
    "geoparquet/by_country/country_iso=PHL/PHL.parquet"
)

DEFAULT_MIN_CONFIDENCE = 0.5  # applies to bf_source='google' rows only; Microsoft rows have confidence=NULL (kept as-is, not source-filtered out)


def _connect():
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    return con


def fetch_buildings_in_bbox(bbox, min_confidence: float = DEFAULT_MIN_CONFIDENCE):
    """bbox: WGS84 [west, south, east, north] (config.AOI_BBOX convention).
    Returns a geopandas.GeoDataFrame (EPSG:4326) with columns bf_source,
    confidence, area_in_meters, geometry — one row per building footprint.

    Filters on the parquet's own `bbox` STRUCT column (xmin/ymin/xmax/ymax) —
    this is what makes DuckDB's row-group pruning actually skip most of the
    4.8GB file instead of scanning it end to end (verified live: ~16-33s
    for real AOIs, not the ~1hr+ a naive full scan would take).
    """
    import geopandas as gpd
    from shapely import wkb

    west, south, east, north = bbox
    con = _connect()
    query = f"""
        SELECT bf_source, confidence, area_in_meters, geometry
        FROM read_parquet('{VIDA_BUILDINGS_URL}')
        WHERE bbox.xmin >= {west} AND bbox.xmax <= {east}
          AND bbox.ymin >= {south} AND bbox.ymax <= {north}
          AND (confidence IS NULL OR confidence >= {min_confidence})
    """
    df = con.execute(query).fetchdf()
    df["geometry"] = df["geometry"].apply(lambda b: wkb.loads(bytes(b)))
    return gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")


def building_count_in_bbox(bbox, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> int:
    """Cheaper than fetch_buildings_in_bbox when only a count is needed
    (Week 3-6's est_buildings_affected doesn't need the geometries kept in
    memory for a plain bbox count — only for an actual polygon intersection)."""
    west, south, east, north = bbox
    con = _connect()
    query = f"""
        SELECT count(*)
        FROM read_parquet('{VIDA_BUILDINGS_URL}')
        WHERE bbox.xmin >= {west} AND bbox.xmax <= {east}
          AND bbox.ymin >= {south} AND bbox.ymax <= {north}
          AND (confidence IS NULL OR confidence >= {min_confidence})
    """
    return con.execute(query).fetchone()[0]
