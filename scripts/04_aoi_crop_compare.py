"""스펙 §3 실제 목적: 마리키나 AOI로 크롭해서 전후 SAR 영상을 육안 대조.

원본 Sentinel-1 GRD는 아핀 변환이 아니라 GCP(지상기준점)로만 지리참조되어 있어
(scripts/02_visualize_scene.py가 확인한 그대로), 정확한 재투영(gdalwarp -geoloc 등,
스펙 §7 preprocess.run 몫)을 하기 전엔 bbox 크롭이 원칙적으로 안 된다.

이 스크립트는 그 정식 재투영 대신 GCP로부터 근사 아핀 변환을 추정(rasterio.transform.from_gcps)해서
AOI 근처 픽셀 윈도우만 빠르게 잘라보는 **근사치**다 — SAR의 range/azimuth 왜곡을 보정하지 않으므로
경계가 몇 픽셀~수십 픽셀 어긋날 수 있다. 스파이크 단계에서 "육안으로 신호가 보이는가"를 빨리
확인하는 용도로만 쓰고, 정밀 비교는 실제 preprocess.run 구현 후 다시 할 것.

사용:
  python scripts/04_aoi_crop_compare.py --baseline <tif> --post <tif>
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402


def crop_to_aoi_approx(tif_path: Path, bbox, pad_ratio: float = 0.15):
    """GCP 기반 근사 아핀 변환으로 bbox 근처 윈도우를 읽는다. (src, array, approx_transform) 반환."""
    import rasterio
    from rasterio.transform import from_gcps
    from rasterio.windows import Window

    src = rasterio.open(tif_path)
    gcps, gcp_crs = src.gcps
    if not gcps:
        raise RuntimeError(f"{tif_path.name}: GCP가 없어 근사 크롭 불가")

    approx_transform = from_gcps(gcps)

    west, south, east, north = bbox
    w = east - west
    h = north - south
    west -= w * pad_ratio
    east += w * pad_ratio
    south -= h * pad_ratio
    north += h * pad_ratio

    # SAR 궤도 방향에 따라 transform의 행/열 진행 부호가 달라질 수 있어
    # from_bounds()의 방향 가정을 못 믿는다 — 네 모서리를 직접 역변환해서 min/max로 윈도우를 구성.
    inv = ~approx_transform
    corners = [(west, south), (west, north), (east, south), (east, north)]
    cols, rows = zip(*(inv * (lon, lat) for lon, lat in corners))
    col_off, row_off = min(cols), min(rows)
    col_end, row_end = max(cols), max(rows)

    window = Window(
        col_off=col_off, row_off=row_off,
        width=col_end - col_off, height=row_end - row_off,
    ).round_lengths().round_offsets()
    # 이미지 범위 밖으로 나가면 클립
    window = window.intersection(Window(0, 0, src.width, src.height))

    if window.width <= 0 or window.height <= 0:
        raise RuntimeError(
            f"{tif_path.name}: AOI가 이 씬의 GCP 범위 밖으로 계산됨 — "
            f"근사 변환 오차이거나 씬이 AOI를 실제로 안 덮을 수 있음"
        )

    arr = src.read(1, window=window)
    print(f"{tif_path.name}: 크롭 윈도우 {window.width}x{window.height}px @ ({window.col_off},{window.row_off})")
    return src, arr, approx_transform


def save_side_by_side(arr_a, arr_b, label_a, label_b, out_path: Path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def stretch(a):
        a = a.astype("float64")
        a = np.where(a > 0, a, np.nan)  # 0 = nodata
        lo, hi = np.nanpercentile(a, [2, 98])
        return np.clip(a, lo, hi)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    for ax, arr, label in zip(axes, [arr_a, arr_b], [label_a, label_b]):
        ax.imshow(stretch(arr), cmap="gray")
        ax.set_title(label)
        ax.axis("off")
    # matplotlib 기본 폰트(DejaVu Sans)가 한글 글리프가 없어 제목은 영문으로 고정.
    fig.suptitle("Marikina AOI approx crop — left: baseline(pre) / right: post_event")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"비교 PNG 저장: {out_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--post", required=True)
    parser.add_argument("--output", default=str(config.DATA_OUTPUT_DIR / "aoi_compare.png"))
    args = parser.parse_args()

    print(f"AOI bbox(근사): {config.AOI_BBOX}")

    src_a, arr_a, _ = crop_to_aoi_approx(Path(args.baseline), config.AOI_BBOX)
    src_b, arr_b, _ = crop_to_aoi_approx(Path(args.post), config.AOI_BBOX)

    save_side_by_side(arr_a, arr_b, "baseline (10/14)", "post_event (10/26)", Path(args.output))

    src_a.close()
    src_b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
