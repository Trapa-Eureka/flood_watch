"""PH Flood Watch 스파이크 공통 설정.

AOI bbox, 이벤트 날짜 윈도우, STAC/모델 엔드포인트를 한 곳에 모은다.
(스펙 §13 규칙 선반영: "모델/전처리 파라미터는 config에만 둔다" — 5주 스프린트에서는
Next.js 쪽 config/model.ts와 이 파일을 대응시킨다.)
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_RAW_DIR = REPO_ROOT / "data" / "raw"
DATA_OUTPUT_DIR = REPO_ROOT / "data" / "output"

# --- AOI: 마리키나 강 유역 ---------------------------------------------------
# 마리키나 시티 자체는 Nominatim(OpenStreetMap)으로 실측 확인한 bbox.
# [west(lon_min), south(lat_min), east(lon_max), north(lat_max)] — STAC bbox 순서
MARIKINA_CITY_BBOX = [121.0743718, 14.6177381, 121.1350232, 14.6757895]

# 강 유역 감시용으로는 시티 경계보다 넓어야 한다(상류 몬탈반/산마테오 ~ 하류 파식강 합류부).
# 아래는 위 실측 bbox를 사방으로 약 0.08도(~9km) 패딩한 근사치이며,
# 정밀 유역 경계(HydroSHEDS 등)가 아니다 — 2-3일 스파이크용 "대략적" bbox(스펙 §14).
# 5주 스프린트 진입 시 실제 유역 폴리곤으로 교체할 것.
MARIKINA_BASIN_BBOX_APPROX = [120.9944, 14.5377, 121.2150, 14.7558]

AOI_BBOX = MARIKINA_BASIN_BBOX_APPROX

# --- 이벤트: 2024년 10월 Kristine(Trami) ------------------------------------
# 대략적 전후 윈도우. 실제 STAC 검색 결과(구름/궤도 주기)에 따라 스크립트 실행 시 조정.
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
CDSE_ZIPPER_URL = "https://zipper.dataspace.copernicus.eu/odata/v1"
CDSE_PUBLIC_CLIENT_ID = "cdse-public"

SENTINEL1_COLLECTION = "sentinel-1-grd"
SENTINEL2_COLLECTION = "sentinel-2-l2a"

# --- Prithvi 모델 ------------------------------------------------------------
# 참고: ibm-nasa-geospatial/Prithvi-EO-1.0-100M-sen1floods11 (100M, S1+S2 6밴드 파인튜닝)
#       ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11 (300M, 최신)
# 3단계에서 둘 다 시도 — 300M이 실패하면 100M으로 폴백.
PRITHVI_CHECKPOINT_PRIMARY = "ibm-nasa-geospatial/Prithvi-EO-2.0-300M-TL-Sen1Floods11"
PRITHVI_CHECKPOINT_FALLBACK = "ibm-nasa-geospatial/Prithvi-EO-1.0-100M-sen1floods11"
