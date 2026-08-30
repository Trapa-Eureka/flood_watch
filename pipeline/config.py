"""Shared configuration for the PH Flood Watch spike.

Collects the AOI bbox, event date windows, and STAC/model endpoints in one place.
(Anticipates spec §13's rule: "model/preprocessing parameters live only in config" —
in the 5-week sprint this file's counterpart on the Next.js side is config/model.ts.)
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Week 4-8: this module now reads MODAL_ENVIRONMENT from the environment at
# IMPORT time (a plain module-level constant, not a lazy per-call os.environ
# read like db.py's _supabase_headers() uses for secrets) — so .env has to
# be loaded before that line runs. Every caller so far has relied on
# *its own* later `from dotenv import load_dotenv; load_dotenv()` call, which
# is too late if that caller imports `pipeline.config` first (several do).
# load_dotenv() is safe to call more than once, so doing it here too — before
# anything below reads os.environ — makes config.py self-sufficient
# regardless of import order, instead of silently depending on whichever
# other module happened to load .env first.
load_dotenv()

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

# --- Modal (spec.md §5 serverless GPU deployment, Week 4-8 formalization) -----
# pipeline/inference/modal_app.py's app name — same name in both environments
# below, Modal's "environment" concept (not the app name) is what separates
# staging from production, matching the CLI's own model (`modal environment
# create/list`, `modal deploy --env <name>`). Real deploy history:
#   modal deploy pipeline/inference/modal_app.py --env staging     (verified)
#   modal deploy pipeline/inference/modal_app.py --env main        (verified)
# "main" is Modal's own default environment name (already existed pre-Week4-8,
# `modal environment list` showed it as the only one) — used as production
# here rather than creating a redundant third env just to rename it.
MODAL_APP_NAME = "ph-flood-watch-inference"
# Defaults to staging — a real production run must opt in explicitly
# (MODAL_ENVIRONMENT=main in .env), same "don't default to spending real
# money/hitting the real environment" caution this project already applies
# elsewhere (e.g. Week4-6's GPU-cost-conscious kill of a runaway test run).
MODAL_ENVIRONMENT = os.environ.get("MODAL_ENVIRONMENT", "staging")

# --- Supabase (spec.md §5/§6 PostGIS DB) --------------------------------------
# project created 2026-08-28 (Week 1-3, docs/design-notes.md), Singapore region.
# URL/project ref aren't secrets (same reasoning as R2's account id below) —
# only the DB password and anon/service_role keys live in .env.
SUPABASE_PROJECT_REF = "xaljckiwksyjtasvjagg"
SUPABASE_URL = f"https://{SUPABASE_PROJECT_REF}.supabase.co"

# --- Cloudflare R2 (spec.md §5 storage) ---------------------------------------
# Two buckets, not one, because access patterns differ: raw scenes are
# backend-only (never served publicly — can always be re-fetched from CDSE for
# free anyway), while tiles/COGs are the actual dashboard-facing product and
# need public read access. A single bucket would need Worker-level path
# gatekeeping to enforce that split; two buckets get it for free.
# Bucket names/account id aren't secrets (shown as-is by `wrangler whoami` /
# `wrangler r2 bucket list`) — only the R2 API access key/secret are, and those
# live in .env (R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY), never here.
R2_ACCOUNT_ID = "985db8cc8abf6312655aa8fa00a5d65d"
R2_ENDPOINT_URL = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
R2_BUCKET_RAW = "ph-flood-watch-raw"       # scenes.fetch: original S1/S2 scenes, private
R2_BUCKET_TILES = "ph-flood-watch-tiles"   # tiles.publish: COG/tiles for the dashboard
# Public serving strategy (custom domain vs. a Worker read-proxy in front of
# ph-flood-watch-tiles) is a Week 4 decision — see docs/design-notes.md.
# Region: buckets created with the `apac` location hint to match the Supabase
# project's ap-southeast-1 (Singapore) — see docs/design-notes.md Week 1-3.
