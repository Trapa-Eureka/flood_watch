"""스펙 §14 2단계: Copernicus Data Space Ecosystem STAC에서
마리키나 AOI의 Sentinel-1 GRD 씬을 Kristine/Trami(2024-10) 전후로 검색·다운로드.

동작 방식:
  1) STAC 카탈로그 검색은 인증 없이도 가능(공개 카탈로그) — 결과 메타데이터만 볼 땐 .env 불필요.
  2) 실제 자산(.SAFE) 다운로드는 CDSE 계정(OAuth2 password grant)이 필요 —
     .env에 CDSE_USERNAME/CDSE_PASSWORD가 없으면 검색까지만 하고 다운로드는 건너뛴다.

사용:
  python scripts/01_fetch_scenes.py --search-only   # 인증 없이 검색 결과만 확인
  python scripts/01_fetch_scenes.py                 # .env 자격증명으로 실제 다운로드
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def search_items(pre_start, pre_end, post_start, post_end, bbox, collection, max_items):
    """STAC 검색. 인증 불필요(공개 카탈로그 read)."""
    from pystac_client import Client

    catalog = Client.open(config.CDSE_STAC_URL)

    def _search(dt_start, dt_end, role):
        search = catalog.search(
            collections=[collection],
            bbox=bbox,
            datetime=f"{dt_start}T00:00:00Z/{dt_end}T23:59:59Z",
            max_items=max_items,
        )
        items = list(search.items())
        print(f"[{role}] {dt_start} ~ {dt_end}: {len(items)}개 씬")
        for it in items:
            print(f"  - {it.id}  acquired={it.datetime}  bbox={it.bbox}")
        return items

    pre_items = _search(pre_start, pre_end, "baseline(사전)")
    post_items = _search(post_start, post_end, "post_event(사후)")
    return pre_items, post_items


def get_access_token() -> str | None:
    username = os.environ.get("CDSE_USERNAME")
    password = os.environ.get("CDSE_PASSWORD")
    if not username or not password:
        return None

    import requests

    resp = requests.post(
        config.CDSE_TOKEN_URL,
        data={
            "client_id": config.CDSE_PUBLIC_CLIENT_ID,
            "username": username,
            "password": password,
            "grant_type": "password",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def download_item(item, token: str, out_dir: Path) -> Path | None:
    """STAC item의 assets['Product'] href(OData zipper, 전체 .SAFE zip)로 다운로드.

    실측 결과 CDSE STAC(_COG 컬렉션)의 item.assets에는 이미 완성된 다운로드 URL이
    'Product' 키로 들어있다(도메인은 download.dataspace.copernicus.eu — 처음에 zipper.*로
    잘못 짐작했던 것을 실제 STAC 응답 보고 수정함). 이게 없는 경우에만 이름 기반 OData 검색으로 폴백.
    """
    import requests

    product_name = item.id
    download_url = None

    product_asset = item.assets.get("Product") if hasattr(item, "assets") else None
    if product_asset is not None:
        download_url = product_asset.href
        print(f"  STAC asset에서 다운로드 URL 확보: {download_url}")

    if download_url is None:
        # 폴백: 이름 기반 OData 검색 (구버전 STAC이나 Product asset이 없는 경우)
        filter_name = product_name if product_name.endswith(".SAFE") else f"{product_name}.SAFE"
        odata_search = (
            f"{config.CDSE_ODATA_URL}/Products?$filter=Name eq '{filter_name}'&$top=1"
        )
        r = requests.get(odata_search, timeout=30)
        r.raise_for_status()
        values = r.json().get("value", [])
        if not values:
            print(f"  ! OData에서 {filter_name} 를 찾지 못함 — 건너뜀")
            return None
        product_id = values[0]["Id"]
        download_url = f"{config.CDSE_ZIPPER_URL}/Products({product_id})/$value"

    out_path = out_dir / f"{product_name}.zip"
    out_dir.mkdir(parents=True, exist_ok=True)

    headers = {"Authorization": f"Bearer {token}"}
    with requests.get(download_url, headers=headers, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        written = 0
        with open(out_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                written += len(chunk)
        print(f"  ✓ {out_path.name} ({written/1e6:.1f}MB / 예상 {total/1e6:.1f}MB)")
    return out_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pre-start", default=config.PRE_EVENT_START)
    parser.add_argument("--pre-end", default=config.PRE_EVENT_END)
    parser.add_argument("--post-start", default=config.POST_EVENT_START)
    parser.add_argument("--post-end", default=config.POST_EVENT_END)
    parser.add_argument("--collection", default=config.SENTINEL1_COLLECTION)
    parser.add_argument("--max-items", type=int, default=5)
    parser.add_argument("--search-only", action="store_true", help="다운로드 없이 검색만")
    parser.add_argument("--out-dir", default=str(config.DATA_RAW_DIR))
    args = parser.parse_args()

    print(f"AOI bbox: {config.AOI_BBOX}  (근사치 — config.py 주석 참고)")

    pre_items, post_items = search_items(
        args.pre_start, args.pre_end, args.post_start, args.post_end,
        config.AOI_BBOX, args.collection, args.max_items,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "search_results.json"
    meta_path.write_text(
        json.dumps(
            {
                "baseline": [it.to_dict() for it in pre_items],
                "post_event": [it.to_dict() for it in post_items],
            },
            indent=2,
            default=str,
        )
    )
    print(f"검색 결과 메타데이터 저장: {meta_path}")

    if args.search_only:
        print("--search-only 지정됨 — 다운로드는 건너뜀.")
        return 0

    token = get_access_token()
    if not token:
        print(
            "\n! CDSE_USERNAME/CDSE_PASSWORD가 .env에 없어 다운로드를 건너뜁니다.\n"
            "  .env.example을 .env로 복사하고 https://dataspace.copernicus.eu 계정으로 채운 뒤 재실행하세요."
        )
        return 0

    for role, items in (("baseline", pre_items), ("post_event", post_items)):
        role_dir = out_dir / role
        for item in items[: args.max_items]:
            print(f"다운로드 중: [{role}] {item.id}")
            try:
                download_item(item, token, role_dir)
            except Exception as e:  # noqa: BLE001
                print(f"  ! 다운로드 실패: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
