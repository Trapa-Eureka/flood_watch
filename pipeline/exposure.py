"""Spec §7 exposure.compute: overlay a flood polygon (flood_extents.geom,
Week 3-5) against admin boundaries (Week 3-1/3-2), WorldPop (Week 3-3), and
building footprints (Week 3-4) to produce exposure_stats rows — spec.md §6:
flooded_area_km2/pct, est_population_affected, est_buildings_affected,
population_source, building_source.

Area math note (relevant to Week 3-7's "UTM 다중 zone 처리" item): all areas
here are computed with pyproj.Geod's ellipsoidal (WGS84) geodesic formula
directly on EPSG:4326 coordinates — no UTM reprojection at all, so which zone
(50N/51N/52N) an AOI happens to sit in never matters for this module
specifically. This sidesteps the multi-zone problem for exposure_stats' own
math, but it does NOT solve Week 3-7's actual scope — the S2 composite/
preprocessing pipeline (pipeline/preprocess/s2_composite.py etc.) still
hardcodes a single UTM zone when *building* the flood raster/polygon in the
first place, which is a separate, earlier-in-the-pipeline problem this module
doesn't touch.
"""
import warnings
from pathlib import Path

from pyproj import Geod
from shapely import wkt
from shapely.geometry import shape

from pipeline import population
from pipeline.boundaries import fetch_near_bbox
from pipeline.buildings import DEFAULT_MIN_CONFIDENCE, fetch_buildings_in_bbox
from pipeline.population import WORLDPOP_DEFAULT_YEAR

_GEOD = Geod(ellps="WGS84")


def geodesic_area_km2(geom) -> float:
    """abs() because geometry_area_perimeter's sign follows ring winding
    order, which we don't control (came from rasterio.features.shapes /
    PostgREST's GeoJSON, not hand-authored) — only magnitude matters here."""
    area, _ = _GEOD.geometry_area_perimeter(geom)
    return abs(area) / 1e6


def compute_exposure_stats(flood_geom_wkt: str, level: str = "adm3_municipality",
                            population_year: int = WORLDPOP_DEFAULT_YEAR,
                            building_min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> list:
    """For each admin_boundaries row (at *level*) that the flood polygon
    actually intersects, compute one exposure_stats row (as a plain dict —
    NOT written to DB here, same separation-of-concerns as
    vectorize.vectorize_new_flood: compute returns data, the caller decides
    whether/how to persist it via repository.upsert_exposure_stat).

    "affected population" = zonal sum of WorldPop pixels within the
    flood-polygon ∩ admin-boundary intersection (not the whole boundary).
    "affected buildings" = count of building footprints whose CENTROID falls
    within that same intersection (the standard convention — an any-overlap
    rule would over-count buildings that only clip the flood edge).
    """
    flood_geom = wkt.loads(flood_geom_wkt)
    if flood_geom.is_empty:
        return []

    candidates = fetch_near_bbox(flood_geom.bounds, level=level, pad_ratio=0.02)
    national_pop_path = population.download_national_population_raster(year=population_year)

    population_source = f"WorldPop {population_year} (R2025A, constrained, 100m)"
    building_source = f"Google Open Buildings v3 + Microsoft GlobalMLBuildingFootprints (VIDA merge), confidence>={building_min_confidence}"

    results = []
    for row in candidates:
        boundary_geom = shape(row["geom"])
        if not flood_geom.intersects(boundary_geom):
            continue
        intersection = flood_geom.intersection(boundary_geom)
        if intersection.is_empty:
            continue

        flooded_area_km2 = geodesic_area_km2(intersection)
        boundary_area_km2 = geodesic_area_km2(boundary_geom)
        flooded_area_pct = min(100.0, 100 * flooded_area_km2 / boundary_area_km2) if boundary_area_km2 > 0 else 0.0

        try:
            est_population = population.population_sum_in_geometry(national_pop_path, intersection)
        except Exception as e:
            print(f"  exposure: population zonal sum failed for {row['name']!r}: {e}")
            est_population = None

        try:
            gdf = fetch_buildings_in_bbox(intersection.bounds, min_confidence=building_min_confidence)
            if len(gdf):
                # geopandas warns that centroid on a geographic (lon/lat) CRS
                # is inaccurate — true in general, but irrelevant at building
                # scale (a few meters to a few tens of meters): the planar
                # vs. geodesic centroid difference there is far below the
                # footprint's own positional uncertainty, and this is only
                # used for a boolean within() test, not an area/distance
                # measurement. Reprojecting per-call would need a UTM zone
                # decision anyway (exactly what this module avoids elsewhere).
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=UserWarning)
                    est_buildings = int(gdf.geometry.centroid.within(intersection).sum())
            else:
                est_buildings = 0
        except Exception as e:
            print(f"  exposure: building count failed for {row['name']!r}: {e}")
            est_buildings = None

        results.append({
            "admin_boundary_id": row["id"],
            "name": row["name"],
            "flooded_area_km2": round(flooded_area_km2, 4),
            "flooded_area_pct": round(flooded_area_pct, 2),
            "est_population_affected": round(est_population) if est_population is not None else None,
            "est_buildings_affected": est_buildings,
            "population_source": population_source if est_population is not None else None,
            "building_source": building_source if est_buildings is not None else None,
        })

    return results
