# PH Flood Watch

위성 기반 홍수·태풍 피해 매핑. 전체 배경/스코프/아키텍처는 [docs/spec.md](docs/spec.md), 기술 스택 선정 근거는 [docs/tech-stack.md](docs/tech-stack.md) 참고.

## 현재 단계: 2–3일 기술검증(go/no-go 스파이크)

전면 개발(5주 스프린트, docs/spec.md §9) 전에 핵심 가설부터 확인 중이다:
**Prithvi + Sentinel-1이 실제 PH 태풍 침수를 잡아내는가.** (docs/spec.md §3)

이 레포의 `scripts/`는 스파이크 전용이며, 5주 스프린트 코드(Next.js 대시보드, FastAPI 추론 서비스, Docker화 등)는 이 검증이 통과된 뒤 별도로 붙는다.

## 환경 설정

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # CDSE_USERNAME/CDSE_PASSWORD 채우기 (dataspace.copernicus.eu 무료 가입)
```

## 스파이크 실행 순서 (docs/spec.md §14와 대응)

```bash
# 1) 설치 확인
python scripts/00_setup_check.py

# 2) STAC 검색(+ .env 있으면 다운로드까지)
python scripts/01_fetch_scenes.py --search-only   # 인증 없이 검색 결과만 먼저 확인
python scripts/01_fetch_scenes.py                 # 실제 다운로드

# 3) 씬 정보 출력 + PNG 시각화
python scripts/02_visualize_scene.py --self-test          # 합성 데이터로 로직만 검증
python scripts/02_visualize_scene.py --input <다운받은 파일>

# 4) Prithvi 모델 로딩
python scripts/03_load_prithvi.py
```

각 단계 실행 결과는 커밋 메시지 또는 별도 노트에 기록하고, 통과/실패 판단은 docs/spec.md §3 기준을 따른다.

## 주의

- AOI bbox(`scripts/config.py`)는 Nominatim 실측값을 기준으로 패딩한 근사치다. 정밀 유역 경계 아님.
- 원본 씬/모델 체크포인트는 `.gitignore`로 제외된다 — 용량이 크고 재다운로드 가능.
- Copernicus 데이터 사용 시 "Contains modified Copernicus Sentinel data" 표기 의무(docs/spec.md §8).
