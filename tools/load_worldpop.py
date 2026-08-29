"""Week 3-3: WorldPop national population raster (PHL, R2025A constrained
100m) — download once, crop to a real AOI, and sanity-check the zonal sum
against a real, live-looked-up population figure (Wikidata, sourced from PSA
census releases) before calling this "loaded" (same discipline as 3-1/3-2's
DB spot-checks).

Note the sanity check is a bounding-box crop (config.MARIKINA_CITY_BBOX), not
the actual city polygon (that's admin_boundaries' `City of Marikina` MultiPolygon,
loaded in 3-1) — a rectangular bbox necessarily includes slivers of neighboring
cities/municipalities, so the crop's sum is expected to run somewhat *above*
Marikina's own census figure, not equal to it. Exact zonal sums against the
real polygon are Week 3-6's job (exposure.compute), once flood_extents /
admin_boundaries geometries are what's being intersected against.

Usage:
  python -m tools.load_worldpop
"""
import sys

sys.path.insert(0, ".")
from pipeline import config
from pipeline.population import (
    WORLDPOP_DEFAULT_YEAR,
    crop_to_bbox,
    download_national_population_raster,
    national_raster_path,
    population_sum,
)

# Live-looked-up 2020-05-01 PSA census figure for City of Marikina (Wikidata
# Q17175, P1082, sourced from PSA releases) — 2026-08-29. Not from memory: the
# same standing rule (verify real data, don't trust recall) applied to this
# sanity-check benchmark too. Wikidata also carries a 2024-07-01 estimate
# (471,323) — closer to our raster's 2025 vintage, used as the comparison
# point below since both are post-census growth estimates for a similar year.
MARIKINA_CENSUS_2020 = 456_059
MARIKINA_ESTIMATE_2024 = 471_323


def main():
    national_path = download_national_population_raster(year=WORLDPOP_DEFAULT_YEAR)
    print(f"National raster: {national_path} ({national_path.stat().st_size:,} bytes)")

    crop_path = crop_to_bbox(national_path, config.MARIKINA_CITY_BBOX)
    print(f"Cropped to Marikina city bbox: {crop_path}")

    total = population_sum(crop_path)
    print(f"\nZonal sum (bbox crop, {WORLDPOP_DEFAULT_YEAR}): {total:,.0f}")
    print(f"Marikina PSA census 2020:  {MARIKINA_CENSUS_2020:,}  (ratio: {total / MARIKINA_CENSUS_2020:.2f}x)")
    print(f"Marikina PSA estimate 2024: {MARIKINA_ESTIMATE_2024:,}  (ratio: {total / MARIKINA_ESTIMATE_2024:.2f}x)")
    # Expected ratio re-derived from the bbox's actual area, not guessed: bbox
    # is ~42.2 km^2 (measured from config.MARIKINA_CITY_BBOX) vs. Marikina's
    # own official land area of 21.52 km^2 (Wikidata P2046, live-looked-up) —
    # i.e. the bbox is genuinely ~2.0x the city's area, so a population ratio
    # anywhere up to ~2.0x is plain geometry, not a bug. A ratio *above* that
    # (or a ratio near 1.0x, which would mean the bbox picked up almost no
    # extra population despite covering 2x the area) is what would actually
    # need investigating (wrong band/units/CRS).
    print(
        "\nBbox area ~42.2 km^2 vs. Marikina's own land area 21.52 km^2 (~1.96x) — "
        "a population ratio up to ~2.0x is expected from geometry alone, not a bug."
    )


if __name__ == "__main__":
    main()
