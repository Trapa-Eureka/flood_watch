"""Spec §7 vectorize.extract: raster -> polygon, "육지 클립"(land clip).

Week 2-7 introduced a MINIMAL version — just the core raster->polygon
mechanism (rasterio.features.shapes + shapely union), enough for flood_extents
to hold a real geometry so that integration test could complete end to end.

Week 3-5 (this file, full production version) adds the three things spec.md
§7 actually asks for beyond that core:
  1. Sliver removal — drop single/few-pixel classification-noise polygons
     before unioning (empirically justified below, not an arbitrary cutoff).
  2. Land clip — intersect against the real Philippine land boundary (reusing
     admin_boundaries/ADM3 from Week 3-1, via the new admin_boundaries_near_bbox
     RPC) so coastal misclassification can't produce "new flood" polygons out
     in open sea.
  3. Simplification — same 0.0001 deg (~11m) tolerance as admin_boundaries
     (Week 3-1), matched to Sentinel-2's own 10m pixel resolution for the same
     reason: sub-pixel-scale vertices carry no real information here either.
"""
from dotenv import load_dotenv

from pipeline.boundaries import fetch_near_bbox

load_dotenv()

WATER_VALUE = 255  # matches pipeline/preprocess/cloud_mask.py and baseline_diff.py

# Empirically justified 2026-08-29 against the two real backtest rasters this
# project already has (Marikina Kristine/Trami, Cagayan Aug-2025 monsoon):
# keeping only polygons >= 3 pixels (i.e. dropping 1-2 pixel specks below
# this) removes a large chunk of polygon COUNT at both sites (Marikina 18/89
# = 20.2%, Cagayan 532/1510 = 35.2% — genuinely a lot of isolated noise) while
# costing almost no total flood AREA (Marikina 0.52%, Cagayan 0.50% — strikingly
# consistent between two very different sites). See docs/design-notes.md.
MIN_POLYGON_AREA_M2 = 300  # keep polygons >= 3 Sentinel-2 pixels (10m x 10m each); drop 1-2px specks

SIMPLIFY_TOLERANCE_DEG = 0.0001  # matches pipeline/boundaries.py's SIMPLIFY_TOLERANCE_DEG


def fetch_land_union(bbox, pad_ratio: float = 0.1, level: str = "adm3_municipality"):
    """Union of admin_boundaries geometries near *bbox* (via
    pipeline.boundaries.fetch_near_bbox, Week 3-5's admin_boundaries_near_bbox
    RPC) — a local land-mask polygon for clipping. Returns a shapely
    (Multi)Polygon in EPSG:4326, or None if no municipalities are found nearby
    — a legitimate outcome for an AOI that's genuinely outside PH's land
    territory (open sea), not an error.
    """
    from shapely.geometry import shape
    from shapely.ops import unary_union

    rows = fetch_near_bbox(bbox, level=level, pad_ratio=pad_ratio)
    if not rows:
        return None
    return unary_union([shape(r["geom"]) for r in rows])


def vectorize_new_flood(raster_path, water_value: int = WATER_VALUE,
                         min_polygon_area_m2: float = MIN_POLYGON_AREA_M2,
                         simplify_tolerance_deg: float = SIMPLIFY_TOLERANCE_DEG,
                         clip_to_land: bool = True, land_union=None) -> "dict | None":
    """Vectorize pixels == water_value into a single (Multi)Polygon, with
    sliver removal + optional land-clip + simplification.

    land_union: pass a pre-fetched shapely geometry (from fetch_land_union) to
    skip re-fetching per call — useful when vectorizing multiple rasters for
    the same AOI. Left None to fetch automatically from the raster's own bbox.

    Returns {"geom_wkt": "MULTIPOLYGON(...)" in EPSG:4326, "area_km2": float}
    or None if there's no matching (post sliver-removal, post land-clip) area
    at all — a real, valid outcome, not every event has new flood in its AOI
    (and land-clipping a purely-offshore false-positive down to nothing is
    exactly the case this exists to handle).
    """
    import pyproj
    import rasterio
    from rasterio.features import shapes
    from rasterio.warp import transform_bounds
    from shapely.geometry import MultiPolygon, Polygon, shape
    from shapely.ops import transform as shp_transform
    from shapely.ops import unary_union

    with rasterio.open(raster_path) as src:
        band = src.read(1)
        transform = src.transform
        crs = src.crs
        raster_bounds = src.bounds

    mask = band == water_value
    if not mask.any():
        return None

    polygons = [
        shape(geom) for geom, val in shapes(mask.astype("uint8"), mask=mask, transform=transform)
        if val == 1
    ]
    if not polygons:
        return None

    # Sliver removal BEFORE union — shapes() already returns one polygon per
    # contiguous pixel group, exactly the unit we want to filter on. Doing
    # this after union would require re-decomposing a merged multipolygon.
    n_before = len(polygons)
    polygons = [p for p in polygons if p.area >= min_polygon_area_m2]
    if not polygons:
        print(f"  vectorize: all {n_before} polygon(s) were slivers (< {min_polygon_area_m2}m^2) — no flood after cleanup")
        return None

    # Union + area in the raster's own (projected, UTM meters) CRS — area
    # comes out directly in m^2 here, no geodesic-area math needed.
    merged = unary_union(polygons)

    to_4326 = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    from_4326 = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform

    if clip_to_land:
        if land_union is None:
            bbox_4326 = transform_bounds(crs, "EPSG:4326", *raster_bounds)
            land_union = fetch_land_union(bbox_4326)
        if land_union is None:
            print("  vectorize: no admin_boundaries found near this AOI (fully offshore?) — land-clip removes all flood area")
            return None
        # Reproject the (4326) land mask into the raster's own projected CRS
        # so the intersection — and the area we measure right after it — both
        # happen in meters, not degrees (never compute area in EPSG:4326).
        land_union_proj = shp_transform(from_4326, land_union)
        before_km2 = merged.area / 1e6
        merged = merged.intersection(land_union_proj)
        after_km2 = merged.area / 1e6
        if before_km2 > 0:
            print(f"  vectorize: land-clip {before_km2:.4f} -> {after_km2:.4f} km^2 "
                  f"({100 * (1 - after_km2 / before_km2):.2f}% removed as offshore/sea)")
        if merged.is_empty:
            return None

    area_km2 = merged.area / 1e6

    merged_4326 = shp_transform(to_4326, merged)
    if simplify_tolerance_deg:
        merged_4326 = merged_4326.simplify(simplify_tolerance_deg, preserve_topology=True)

    if isinstance(merged_4326, Polygon):
        merged_4326 = MultiPolygon([merged_4326])
    elif merged_4326.geom_type == "GeometryCollection":
        # intersection() with a MultiPolygon land mask can occasionally yield
        # a GeometryCollection with degenerate (Point/LineString) leftovers
        # at touching boundaries — keep only the polygonal parts.
        polys = [g for g in merged_4326.geoms if isinstance(g, (Polygon, MultiPolygon))]
        if not polys:
            return None
        merged_4326 = unary_union(polys)
        if isinstance(merged_4326, Polygon):
            merged_4326 = MultiPolygon([merged_4326])

    return {"geom_wkt": merged_4326.wkt, "area_km2": area_km2}
