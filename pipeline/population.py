"""Spec §7/§8 exposure.compute input: WorldPop gridded population, used later
(Week 3-6) as the population layer for zonal population-affected sums.

Unlike JRC's Global Surface Water baseline (pipeline/baseline_diff.py) — a
multi-terabyte global tile mosaic that genuinely needs /vsicurl/ remote
windowed reads to avoid downloading tiles we don't need — WorldPop's whole-
Philippines 100m population raster is a single ~63MB GeoTIFF (verified live
via a HEAD request: Content-Length=63493139, Accept-Ranges: bytes). At that
size a full national download is simpler and more robust than a live network
dependency at zonal-stats time, so this module downloads once and caches
locally (data/raw/population/, gitignored — same convention as
admin_boundaries' raw GeoJSON downloads), then crops/reads out of that local
file.

Source verified live via WorldPop's own hub API (not assumed from memory —
same "don't trust a stale URL pattern" discipline as HDX in boundaries.py):
  https://hub.worldpop.org/rest/data/pop/G2_CN_POP_R25A_100m?iso3=PHL
This is WorldPop's current "Global2" release (R2025A, replaces the older
Global1 2000-2020 wpgp/cic2020 products still served under legacy endpoints),
constrained (building-settlement-informed, WorldPop's recommended product over
unconstrained when available), 100m, one GeoTIFF per calendar year 2015-2030.
Years beyond the data's actual census/survey basis (all of them, to varying
degrees) are model estimates, not fresh counts each year — WorldPop's own
methodology projects forward/backward from census benchmarks — so there is no
strong "more accurate" reason to prefer one year over an adjacent one. Default
picked here is the most recent *fully elapsed* calendar year at the time this
was written (2025, vs. today=2026-08-29); callers computing exposure_stats for
a specific event should pass the year closest to that event's date instead of
relying on this default (Week 3-6 concern — not resolved here, since which
year is "right" is a per-event decision, not a per-dataset one).
"""
from pathlib import Path

import requests

from pipeline import config

WORLDPOP_ISO3 = "PHL"
WORLDPOP_RELEASE = "R2025A"
WORLDPOP_RESOLUTION = "100m"
WORLDPOP_DEFAULT_YEAR = 2025

POPULATION_RAW_DIR = config.DATA_RAW_DIR / "population"


def worldpop_url(year: int = WORLDPOP_DEFAULT_YEAR, iso3: str = WORLDPOP_ISO3) -> str:
    """URL pattern verified live 2026-08-29 against
    https://hub.worldpop.org/rest/data/pop/G2_CN_POP_R25A_100m?iso3=PHL for
    years 2015-2030 — all 16 years share this exact template, only the year
    segment (appearing twice) and the filename's iso3 prefix change."""
    iso3_lower = iso3.lower()
    return (
        f"https://data.worldpop.org/GIS/Population/Global_2015_2030/{WORLDPOP_RELEASE}/"
        f"{year}/{iso3}/v1/{WORLDPOP_RESOLUTION}/constrained/"
        f"{iso3_lower}_pop_{year}_CN_{WORLDPOP_RESOLUTION}_{WORLDPOP_RELEASE}_v1.tif"
    )


def national_raster_path(year: int = WORLDPOP_DEFAULT_YEAR, iso3: str = WORLDPOP_ISO3) -> Path:
    return POPULATION_RAW_DIR / f"{iso3.lower()}_pop_{year}_CN_{WORLDPOP_RESOLUTION}_{WORLDPOP_RELEASE}_v1.tif"


def download_national_population_raster(year: int = WORLDPOP_DEFAULT_YEAR, iso3: str = WORLDPOP_ISO3,
                                          force: bool = False) -> Path:
    """Idempotent — same pattern as boundaries.py's on_conflict upserts and
    scene_refs' band cache: skip the (slow, ~63MB) download if we already have
    it, unless force=True."""
    dest = national_raster_path(year, iso3)
    if dest.exists() and not force:
        print(f"Using cached {dest} ({dest.stat().st_size:,} bytes)")
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    url = worldpop_url(year, iso3)
    print(f"Downloading {url}")
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        written = 0
        tmp = dest.with_suffix(".tif.part")
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                written += len(chunk)
        tmp.rename(dest)
    print(f"Downloaded {dest} ({written:,} bytes" + (f", expected {total:,}" if total else "") + ")")
    return dest


def crop_to_bbox(national_raster_path: Path, bbox, pad_ratio: float = 0.0, dest_path: "Path | None" = None) -> Path:
    """Windowed read + write a GeoTIFF crop covering *bbox* (WGS84
    [west, south, east, north], same convention as config.AOI_BBOX). Kept as
    its own function (not inlined into a one-off script) so Week 3-6's
    exposure.compute can call it directly per-event without re-deriving the
    windowing logic."""
    import rasterio
    from rasterio.windows import from_bounds

    west, south, east, north = bbox
    w, h = east - west, north - south
    west, east = west - w * pad_ratio, east + w * pad_ratio
    south, north = south - h * pad_ratio, north + h * pad_ratio

    with rasterio.open(national_raster_path) as src:
        window = from_bounds(west, south, east, north, transform=src.transform)
        window = window.round_offsets().round_lengths()
        data = src.read(1, window=window)
        out_transform = src.window_transform(window)
        meta = src.meta.copy()
        meta.update(height=data.shape[0], width=data.shape[1], transform=out_transform)

    if dest_path is None:
        dest_path = config.DATA_OUTPUT_DIR / "population" / f"{Path(national_raster_path).stem}_crop.tif"
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dest_path, "w", **meta) as dst:
        dst.write(data, 1)

    return dest_path


def population_sum(raster_path: Path) -> float:
    """Sum of all (non-nodata) pixel values = estimated total population
    covered by the raster — WorldPop's unit is people-per-pixel, not density,
    so a plain sum (excluding nodata) is the correct total, not an average."""
    import numpy as np
    import rasterio

    with rasterio.open(raster_path) as src:
        data = src.read(1, masked=True)
    return float(np.ma.sum(data))


def population_sum_in_geometry(national_raster_path: Path, geometry) -> float:
    """Week 3-6 exposure.compute: zonal sum of population within an arbitrary
    polygon (e.g. flood-polygon ∩ admin-boundary intersection — NOT just a
    bbox, unlike crop_to_bbox above, which is why this is a separate function
    rather than crop_to_bbox + population_sum). *geometry* must be a
    shapely geometry in EPSG:4326 (WorldPop's native CRS, no reprojection
    needed). Reads directly off the already-downloaded national raster —
    no network call.
    """
    import numpy as np
    import rasterio
    import rasterio.mask

    with rasterio.open(national_raster_path) as src:
        try:
            out_image, _ = rasterio.mask.mask(src, [geometry], crop=True, nodata=src.nodata)
        except ValueError:
            # rasterio.mask raises ValueError when the geometry doesn't
            # overlap the raster at all — a legitimate "0 population" outcome
            # (e.g. a flood polygon fragment that turned out to be entirely
            # outside WorldPop's PH raster extent), not a real error.
            return 0.0
        nodata = src.nodata

    data = out_image[0]
    if nodata is not None:
        data = np.ma.masked_equal(data, nodata)
    total = np.ma.sum(data)
    # np.ma.sum returns the `masked` constant (not 0) when EVERY pixel is
    # masked — a real case for a small intersection polygon whose area is
    # smaller than one 100m WorldPop pixel and happens to not contain any
    # pixel *center* (rasterio.mask's default all_touched=False test).
    # That's genuinely "no population grid data available here", not an
    # error — 0.0 is the correct estimate, not NaN.
    return 0.0 if total is np.ma.masked else float(total)
