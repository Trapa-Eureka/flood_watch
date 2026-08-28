"""Shared configuration for the PH Flood Watch spike.

Collects the AOI bbox, event date windows, and STAC/model endpoints in one place.
(Anticipates spec §13's rule: "model/preprocessing parameters live only in config" —
in the 5-week sprint this file's counterpart on the Next.js side is config/model.ts.)
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
DATA_OUTPUT_DIR = REPO_ROOT / "data" / "output"

# --- AOI: Marikina river basin ----------------------------------------------
# Marikina City itself: bbox measured against Nominatim (OpenStreetMap).
# [west(lon_min), south(lat_min), east(lon_max), north(lat_max)] — STAC bbox order
MARIKINA_CITY_BBOX = [121.0743718, 14.6177381, 121.1350232, 14.6757895]

# For basin-scale monitoring we need more than the city boundary (from upstream
# Montalban/San Mateo down to the confluence with the Pasig River).
# Below is the measured bbox above padded ~0.08 degrees (~9km) on each side —
# an approximation, not a precise basin boundary (e.g. HydroSHEDS) — a "rough"
# bbox good enough for the 2-3 day spike (spec §14).
# Replace with an actual basin polygon before entering the 5-week sprint.
MARIKINA_BASIN_BBOX_APPROX = [120.9944, 14.5377, 121.2150, 14.7558]

AOI_BBOX = MARIKINA_BASIN_BBOX_APPROX

# --- Event: Kristine (Trami), October 2024 ----------------------------------
# Rough pre/post windows. Adjust at run time based on actual STAC search
# results (cloud cover, orbit repeat cycle).
PRE_EVENT_START = "2024-10-01"
PRE_EVENT_END = "2024-10-20"
POST_EVENT_START = "2024-10-24"
POST_EVENT_END = "2024-11-05"

# --- Copernicus Data Space Ecosystem ----------------------------------------
CDSE_STAC_URL = "https://stac.dataspace.copernicus.eu/v1"
CDSE_TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
CDSE_ODATA_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1"
# Verified 2026-08-28: the domain actually used by STAC item.assets['Product'].href
# is download.* (an earlier guess of zipper.* was wrong). Only the fallback path
# uses this constant — the normal path uses the href STAC hands back directly,
# so it doesn't depend on this value.
CDSE_ZIPPER_URL = "https://download.dataspace.copernicus.eu/odata/v1"
CDSE_PUBLIC_CLIENT_ID = "cdse-public"

SENTINEL1_COLLECTION = "sentinel-1-grd"
SENTINEL2_COLLECTION = "sentinel-2-l2a"

# --- Prithvi model ------------------------------------------------------------
# Reference: ibm-nasa-geospatial/Prithvi-EO-1.0-100M-sen1floods11 (100M, S1+S2 6-band finetune)
#            ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11 (300M, latest)
# Step 4 tries both — falls back to 100M if 300M fails.
PRITHVI_CHECKPOINT_PRIMARY = "ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11"
PRITHVI_CHECKPOINT_FALLBACK = "ibm-nasa-geospatial/Prithvi-EO-1.0-100M-sen1floods11"
