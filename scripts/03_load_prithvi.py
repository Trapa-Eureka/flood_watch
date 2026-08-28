"""스펙 §14 4단계: Prithvi-EO-2.0 + sen1floods11 체크포인트를 TerraTorch로 로드.

TerraTorch API는 버전 간 변경이 잦으므로, 이 스크립트는 두 가지 로딩 경로를 순서대로 시도한다:
  A) terratorch.tasks / BACKBONE_REGISTRY 를 통한 표준 로딩
  B) HuggingFace `from_pretrained` 직접 로딩 (fallback)
둘 다 실패하면 실제 에러를 그대로 출력한다 — 이게 3장 기술검증의 진짜 목적(로드되는가 자체가 신호).

사용:
  python scripts/03_load_prithvi.py
  python scripts/03_load_prithvi.py --checkpoint ibm-nasa-geospatial/Prithvi-EO-1.0-100M-sen1floods11
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

from dotenv import load_dotenv  # noqa: E402

load_dotenv()


def try_terratorch_registry(checkpoint: str):
    import terratorch  # noqa: F401
    from terratorch.registry import BACKBONE_REGISTRY

    print(f"[경로 A] terratorch.registry.BACKBONE_REGISTRY로 로딩 시도: {checkpoint}")
    print(f"  등록된 백본 일부: {list(BACKBONE_REGISTRY)[:10]} ...")

    # terratorch는 보통 'prithvi_eo_v2_300_tl' 같은 백본 이름 + pretrained=True로 로드하고,
    # sen1floods11 파인튜닝 헤드는 별도 태스크 config(yaml)로 조립한다.
    # 여기서는 백본 자체가 정상적으로 인스턴스화되는지만 확인한다(스파이크 목적에 충분).
    backbone_name = "prithvi_eo_v2_300_tl" if "300M" in checkpoint else "prithvi_eo_v1_100"
    model = BACKBONE_REGISTRY.build(backbone_name, pretrained=True)
    return model


def try_huggingface_direct(checkpoint: str):
    from huggingface_hub import hf_hub_download

    print(f"[경로 B] HuggingFace Hub 직접 다운로드 시도: {checkpoint}")
    # 체크포인트 파일명은 저장소마다 다를 수 있어 config.json/README를 먼저 확인해야 하지만,
    # 스파이크 단계에서는 "다운로드 자체가 되는가"만 확인한다.
    path = hf_hub_download(repo_id=checkpoint, filename="config.json")
    print(f"  config.json 다운로드 성공: {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", default=config.PRITHVI_CHECKPOINT_PRIMARY)
    parser.add_argument("--fallback", default=config.PRITHVI_CHECKPOINT_FALLBACK)
    args = parser.parse_args()

    for checkpoint in (args.checkpoint, args.fallback):
        print("=" * 60)
        print(f"체크포인트: {checkpoint}")
        try:
            model = try_terratorch_registry(checkpoint)
            n_params = sum(p.numel() for p in model.parameters())
            print(f"  ✓ 경로 A 성공 — 파라미터 수: {n_params:,}")
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ 경로 A 실패: {type(e).__name__}: {e}")

        try:
            try_huggingface_direct(checkpoint)
            print("  ✓ 경로 B 성공(설정 파일 확인) — 전체 가중치 로딩은 별도 구현 필요")
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ 경로 B 실패: {type(e).__name__}: {e}")

    print("\n두 체크포인트 모두, 두 경로 모두 실패. 에러 메시지를 보고 다음 단계 결정 필요")
    print("(스펙 §3 실패 시 대응: Sentinel-2 광학 보조 / Clay 모델 병행 비교 검토).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
