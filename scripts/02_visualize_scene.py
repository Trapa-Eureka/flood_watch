"""스펙 §14 3단계: 다운로드한 씬을 rasterio로 열어 기본 정보 출력 + PNG 시각화.

사용:
  python scripts/02_visualize_scene.py --input path/to/scene.tif --output out.png
  python scripts/02_visualize_scene.py --self-test   # 실제 씬 없이 스크립트 로직만 검증
"""
import argparse
from pathlib import Path

import numpy as np


def print_scene_info(src) -> None:
    print("-" * 60)
    print(f"밴드 수(count):     {src.count}")
    print(f"해상도(width x height): {src.width} x {src.height}")
    print(f"해상도(pixel size):  {src.res}")
    print(f"좌표계(CRS):        {src.crs}")
    print(f"경계(bounds):       {src.bounds}")
    print(f"dtype:              {src.dtypes}")
    print(f"nodata:             {src.nodata}")
    print("-" * 60)


def save_png(array: np.ndarray, out_path: Path, is_sar_db: bool = False) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    arr = array.astype("float64")
    arr = np.where(np.isfinite(arr), arr, np.nan)

    # SAR 진폭/dB는 동적범위가 커서 2~98 퍼센타일로 스트레치해야 눈으로 보인다.
    lo, hi = np.nanpercentile(arr, [2, 98])
    arr = np.clip(arr, lo, hi)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(arr, cmap="gray")
    ax.set_title(out_path.stem)
    ax.axis("off")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"PNG 저장: {out_path}")


def run_self_test() -> int:
    """실제 위성 씬 없이도 밴드 읽기/스트레치/PNG 저장 로직이 동작하는지 확인."""
    import tempfile

    import rasterio
    from rasterio.transform import from_origin

    print("self-test: 합성 래스터로 파이프라인 로직 검증 중...")
    h, w = 256, 256
    data = (np.random.default_rng(0).random((1, h, w)) * 40 - 25).astype("float32")  # 가짜 SAR dB
    transform = from_origin(121.08, 14.68, 0.0001, 0.0001)

    with tempfile.TemporaryDirectory() as tmp:
        tif_path = Path(tmp) / "synthetic.tif"
        with rasterio.open(
            tif_path, "w", driver="GTiff", height=h, width=w, count=1,
            dtype="float32", crs="EPSG:4326", transform=transform,
        ) as dst:
            dst.write(data)

        with rasterio.open(tif_path) as src:
            print_scene_info(src)
            band1 = src.read(1)
            save_png(band1, Path(tmp) / "synthetic.png", is_sar_db=True)

    print("self-test 통과 — 실제 씬으로 --input 지정해서 재실행할 것.")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=str, default=None, help="rasterio가 열 수 있는 래스터 경로")
    parser.add_argument("--output", type=str, default=None, help="저장할 PNG 경로")
    parser.add_argument("--band", type=int, default=1)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test or not args.input:
        return run_self_test()

    import rasterio

    in_path = Path(args.input)
    out_path = Path(args.output) if args.output else in_path.with_suffix(".png")

    with rasterio.open(in_path) as src:
        print_scene_info(src)
        band = src.read(args.band)
        save_png(band, out_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
