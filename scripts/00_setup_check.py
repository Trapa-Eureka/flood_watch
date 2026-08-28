"""스펙 §14 1단계: Python 환경 스캐폴드 확인.

rasterio, GDAL, geopandas, pystac-client, torch, terratorch가 실제로
import 가능한지, 버전은 무엇인지, GPU(MPS/CUDA)를 쓸 수 있는지 확인한다.
설치만 하고 끝나는 게 아니라 "정말 동작하는가"를 찍어본다.
"""
import importlib
import sys

CHECKS = [
    ("rasterio", None),
    ("geopandas", None),
    ("shapely", None),
    ("pyproj", None),
    ("pystac_client", "pystac-client"),
    ("torch", None),
    ("terratorch", None),
]


def check(module_name: str, display_name: str | None = None) -> tuple[bool, str]:
    display_name = display_name or module_name
    try:
        mod = importlib.import_module(module_name)
        version = getattr(mod, "__version__", "버전 정보 없음")
        return True, f"OK  {display_name:<16} {version}"
    except Exception as e:  # noqa: BLE001 — 스파이크 단계에선 원인 그대로 노출이 유용
        return False, f"FAIL {display_name:<16} {type(e).__name__}: {e}"


def main() -> int:
    print(f"Python: {sys.version}")
    print("-" * 60)
    results = [check(m, d) for m, d in CHECKS]
    for ok, msg in results:
        print(msg)
    print("-" * 60)

    # rasterio가 실제로 GDAL을 잡고 있는지 별도 확인 (import 성공 != 드라이버 정상)
    try:
        import rasterio

        print(f"rasterio가 링크한 GDAL 버전: {rasterio.__gdal_version__}")
    except Exception as e:  # noqa: BLE001
        print(f"rasterio GDAL 링크 확인 실패: {e}")

    # torch 디바이스 확인 (Apple Silicon이면 MPS, 아니면 CPU)
    try:
        import torch

        if torch.backends.mps.is_available():
            device = "mps (Apple Silicon GPU)"
        elif torch.cuda.is_available():
            device = f"cuda ({torch.cuda.get_device_name(0)})"
        else:
            device = "cpu"
        print(f"torch 사용 가능 디바이스: {device}")
    except Exception as e:  # noqa: BLE001
        print(f"torch 디바이스 확인 실패: {e}")

    n_fail = sum(1 for ok, _ in results if not ok)
    print("-" * 60)
    if n_fail:
        print(f"{n_fail}개 실패 — 위 에러 메시지 확인 후 재설치 필요.")
        return 1
    print("전체 설치 확인 완료.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
