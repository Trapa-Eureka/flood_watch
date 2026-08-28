"""Spec §7 vectorize.extract: raster -> polygon.

Week 2-7 introduces a MINIMAL version of this — just enough for flood_extents
to hold a real geometry so the Week 2 integration test can actually complete
the pipeline end-to-end. The full production version (spec.md §7: "래스터 →
폴리곤, 육지 클립" — land-clipping, simplification, sliver removal, etc.) is
Week 3-5's job per sprint-plan.md; this covers only the core raster->polygon
mechanism (rasterio.features.shapes + shapely union), which is standard,
well-tested library code, not something that needed deferring on its own.
"""
from pathlib import Path

import numpy as np


def vectorize_new_flood(raster_path, water_value: int = 255) -> dict | None:
    """Vectorize pixels == water_value into a single (Multi)Polygon.

    Returns {"geom_wkt": "MULTIPOLYGON(...)" in EPSG:4326, "area_km2": float}
    or None if there are no matching pixels at all (a real, valid outcome —
    not every event has new flood in its AOI).
    """
    import pyproj
    import rasterio
    from rasterio.features import shapes
    from shapely.geometry import MultiPolygon, Polygon, shape
    from shapely.ops import transform as shp_transform
    from shapely.ops import unary_union

    with rasterio.open(raster_path) as src:
        band = src.read(1)
        transform = src.transform
        crs = src.crs

    mask = band == water_value
    if not mask.any():
        return None

    polygons = [
        shape(geom) for geom, val in shapes(mask.astype("uint8"), mask=mask, transform=transform)
        if val == 1
    ]
    if not polygons:
        return None

    # Union in the raster's own (projected, UTM meters) CRS — area comes out
    # directly in m^2 here, no geodesic-area math needed. Computing area on
    # the EPSG:4326 (degrees) version instead would be wrong/approximate.
    merged = unary_union(polygons)
    area_km2 = merged.area / 1e6

    reproject = pyproj.Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    merged_4326 = shp_transform(reproject, merged)

    if isinstance(merged_4326, Polygon):
        merged_4326 = MultiPolygon([merged_4326])

    return {"geom_wkt": merged_4326.wkt, "area_km2": area_km2}
