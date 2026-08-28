# PH Flood Watch — 기술 스택 정리

> 원본: [ph-flood-watch-launch-spec.md](./ph-flood-watch-launch-spec.md) 정독 후 정리.
> 새 레포 생성 시 `docs/tech-stack.md`(또는 `docs/spec.md`에 병합)로 사용 가능.
> 최종 갱신: 2026-08-28 — 백엔드/DB 아키텍처 결정(2장) 추가.

---

## 1. 스펙에 명시된 기술 스택 (스펙 §5, §8, §14 기반)

### 검증 단계(2–3일 스파이크, 스펙 14장)만 필요한 것
```
rasterio, GDAL, geopandas, pystac-client, torch, terratorch
```
+ Copernicus Data Space Ecosystem 계정/API 키, 마리키나 AOI bbox.

### 5주 스프린트 풀스택

| 레이어 | 선택 | 근거(스펙 위치) |
|---|---|---|
| 프론트엔드 | Next.js + MapLibre GL JS | §5, PH Fuel Watch 재사용 패턴 |
| 오케스트레이션 | Cloudflare Workers Cron | §5 — 트리거·상태폴링만, 무거운 추론은 별도 컨테이너 |
| 추론 서비스 API | Python FastAPI | §5 |
| DB | PostgreSQL + PostGIS (Supabase/Neon) | §5, Bayni와 동일 패턴 |
| 오브젝트 스토리지 | Cloudflare R2 | §5 — 원본 씬 + COG + 타일 |
| 지리공간 처리 | rasterio, GDAL, GeoPandas | §5, §14 |
| STAC 클라이언트 | pystac-client | §14 |
| ML 프레임워크 | PyTorch | §5 |
| 모델 로더 | IBM TerraTorch | §5, §14 |
| 모델 | Prithvi-EO-2.0 + sen1floods11 체크포인트 | §8 |
| 컨테이너 | Docker (추론 서비스) | §5, §9 Week4 |
| 추론 컴퓨트 | 스팟 GPU 또는 CPU 배치 | §5 — 이벤트당 몇 달러 추정 |

### 외부 데이터 소스 (§8)
| 종류 | 소스 |
|---|---|
| SAR(사후) | Sentinel-1 GRD — Copernicus Data Space Ecosystem STAC |
| 광학(베이스라인) | Sentinel-2 L2A — 동일 |
| STAC 대안 | AWS Earth Search |
| 행정경계 | HDX PH ADM3(안정)/ADM4(바랑가이, 커뮤니티 소스) |
| 인구 | WorldPop 격자 |
| 건물 | OSM 건물 풋프린트 / Google Open Buildings |

### 스펙에 없어 보완 필요했던 항목
- SAR 보정/스펙클 필터 구체 라이브러리 (`pyroSAR`/SNAP 바인딩 후보)
- COG 변환 (`rio-cogeo` 후보)
- 폴리곤화: `rasterio.features.shapes` + `shapely`
- PDF 생성기 구체명 미지정 → [[md-to-pdf-pipeline-and-hangul-bold-bug]] 경로(marked→Chrome headless) 재사용 제안
- 인증/인가, CI/CD, 모니터링/에러 트래킹 — 전면 미언급

---

## 2. 백엔드/DB 아키텍처 결정 — Supabase 과금 리스크 검토 (2026-08-28)

사용자 질문: 호스팅은 Vercel 확정, 그러나 Supabase가 사용자 수 증가에 따라 과금이 폭증할 수 있어 자체 서버/DB 운용도 고려 중. 12개 카테고리별 최선 조합 추천 요청.

### 2.1 결론

**MVP는 Supabase로 시작하되, Supabase 전용 기능(Edge Functions, 트리거 로직 등)에 락인되지 않도록 순수 SQL 스키마로 설계 — 이 프로젝트의 실제 트래픽 패턴(B2G/NGO 소수 고정 유저 + 태풍 이벤트 시 버스트)에서는 Supabase 과금이 "폭증"할 시나리오가 생각보다 좁다.** 무거운 페이로드(원본 씬/COG/타일)는 이미 스펙 설계 단계에서 R2로 분리되어 있어 Supabase의 대역폭/스토리지 과금 경로를 타지 않는다. 진짜 비용 리스크는 사용자 수가 아니라 PostGIS 쿼리 컴퓨트(동시 오버레이 연산)이며, 이는 Supabase든 자체 호스팅이든 똑같이 발생한다.

그래도 처음부터 헤지하고 싶다면 자체 호스팅보다 **Neon**이 더 나은 대안이다 — 관리형 이점은 유지하면서 scale-to-zero 컴퓨트 과금 모델이 "평시엔 트래픽 거의 없고 이벤트 시에만 버스트"라는 이 프로젝트의 실제 패턴에 Supabase Pro의 상시가동형 모델보다 더 잘 맞는다.

### 2.2 Supabase 실제 과금 구조 (2026-08-28 supabase.com/pricing 확인)

| 항목 | Free | Pro ($25/mo 기본) | 초과 단가 |
|---|---|---|---|
| DB 용량 | 500MB | 8GB 포함 | $0.125/GB |
| Egress(대역폭) | 5GB | 250GB 포함 | $0.09/GB |
| 캐시 Egress | 5GB | 250GB 포함 | $0.03/GB |
| 파일 스토리지 | 1GB | 100GB 포함 | $0.0213/GB |
| MAU | 50,000 | 100,000 포함 | $0.00325/MAU |
| Compute | 공용 | $10 크레딧(Micro 커버) | Small $15/mo, Medium $60/mo |
| 기타 | 1주 비활성 시 프로젝트 일시정지, 최대 2개 활성 프로젝트 | — | — |

### 2.3 이 프로젝트에 적용했을 때 리스크 평가

- **스토리지/대역폭**: 원본 씬·COG·타일은 R2(Cloudflare, egress 무료)에 있고 Supabase는 벡터 지오메트리·통계 JSON만 다룬다 → Pro 플랜 250GB 포함량을 초과할 시나리오가 거의 없다. **이 R2 분리 결정 자체가 스펙(§5)에 이미 들어있는 가장 중요한 비용 방어선.**
- **MAU**: 역할이 admin(본인)/viewer(LGU DRRMO, NGO)/public(§4)인데, public 열람을 무인증 읽기전용으로 설계하면 MAU가 아예 늘지 않는다. LGU/NGO 유저는 수십~수백 단위지 수만 단위가 아니다 → 100,000 MAU 포함량 초과 가능성 낮음.
- **DB 용량**: `admin_boundaries`에 PH ADM4(바랑가이 전체, 약 42,000개) 풀해상도 폴리곤을 넣으면 수백MB~1GB대까지 갈 수 있으나 이는 유저 수가 아니라 정적 참조데이터 크기 문제 — 심플리파이(geometry simplify)로 통제 가능.
- **진짜 리스크는 컴퓨트**: 태풍 뉴스 노출로 public 트래픽이 순간적으로 몰리면 동시 PostGIS 오버레이 쿼리가 Micro 인스턴스($10 크레딧 포함분)를 넘어 Small/Medium 애드온($15~60/mo)이 필요해질 수 있다. 하지만 이건 "이용자 수에 비례해 무한히 폭증"이 아니라 상한이 있는 애드온 단계이고, 애초에 "언론 노출 1건 이상"이 §11 성공 기준이므로 오히려 바라는 시나리오다.
- 결론적으로 **Supabase가 폭증할 조건("이용자 수 증가")은 이 프로젝트의 실제 유저 구조상 발생 가능성이 낮고, 헤비 데이터는 이미 R2로 우회했다.** 다만 이 판단은 "public 열람을 무인증으로 설계한다"는 전제에 달려있다 — 인증을 강제하면 MAU 계산이 달라지니 설계 시 확정 필요.

### 2.4 12개 카테고리 추천

| # | 카테고리 | 추천 | 근거 |
|---|---|---|---|
| 1 | 백엔드 언어 | **TypeScript + Python (2개 언어 병존)** | 지오공간/ML 파이프라인은 Python 생태계(rasterio/GDAL/PyTorch/TerraTorch)가 대체 불가, 대시보드/오케스트레이션은 Next.js와 통일된 TS |
| 2 | 백엔드 프레임워크/런타임 | **Next.js Route Handlers(Node, Vercel) + FastAPI(Python, Docker) + Cloudflare Workers(Cron)** | FastAPI는 async I/O(STAC 다운로드)와 Pydantic 검증이 ML 추론 서빙에 표준적. **Flask보다 FastAPI 권장** |
| 3 | 관계형 DB | **PostgreSQL + PostGIS** | ST_Intersects/ST_Area 등 오버레이 연산 필수, 대안 없음 |
| 4 | NoSQL DB | **불필요** | 데이터 모델(§6)이 전부 관계형+지오메트리, 반정형 데이터는 JSONB 컬럼(`metrics jsonb` 등)으로 이미 스펙에 반영됨 |
| 5 | 벡터DB/AI DB | **MVP 불필요, 필요시 pgvector(Postgres 확장)로 충분** | 현재 스펙에 임베딩/시맨틱 검색 요구 없음. 별도 벡터DB 서비스는 과설계 |
| 6 | 검색엔진/DB | **불필요, Postgres pg_trgm/tsvector로 충분** | AOI·이벤트·행정경계 이름 검색은 최대 수만 건 규모 — Typesense/Elasticsearch는 이 규모에 과한 인프라 |
| 7 | BaaS/Managed DB | **Supabase로 시작(락인 최소화 설계), 대안 후보 Neon** | 2.1/2.3 참고. 이미 유료 구독 보유([[user-paid-infra-subscriptions]])라 추가비용 0 |
| 8 | ORM/DB Access | **Drizzle ORM(Next.js) + SQLAlchemy+GeoAlchemy2 또는 raw psycopg(Python)** | Drizzle은 Supabase/Neon/자체호스팅에 동일하게 붙어 포터블. Python 쪽은 `pipeline_events` insert-only 감사 요구(§13) 특성상 무거운 ORM보다 명시적 SQL이 재현성에 유리 |
| 9 | Web Server/Reverse Proxy | **Vercel(프론트, 관리 불필요) + Caddy(FastAPI 앞단, 자체호스팅 시)** | GPU 플랫폼이 자체 처리해주면 Caddy도 불필요 |
| 10 | Cache/Queue/Messaging | **MVP 불필요 — `pipeline_events` 테이블 + Workers Cron 폴링으로 상태관리** | §5 자체가 "실시간 지연 불필요, 배치로 충분"이라 명시. 재시도 로직이 복잡해지면 Cloudflare Queues 검토 |
| 11 | API 기술 | **REST** | 리소스 나열/필터형 데이터 모델, GraphQL 불필요 |
| 12 | Server/Cloud/Infra | **Vercel(프론트) + Cloudflare Workers·R2(오케스트레이션·스토리지) + Modal 또는 RunPod(GPU 추론, 서버리스/스팟)** | GPU는 상시가동 대신 이벤트당 배치 실행에 맞는 서버리스 GPU가 §12 리스크("GPU 배포 경험 부재")를 가장 안전하게 완화 |
| — | 테스팅 | **Playwright(E2E) + pytest(파이프라인/추론)** | Selenium은 Playwright와 중복 — 제거 권장 |
| — | CI/CD | **GitHub Actions** | Vercel/Wrangler 배포훅과 직결, 무료 티어로 충분 |

### 2.5 사용자 초안 대비 변경점 요약

사용자 원안:
```
Server/Backend: Node.js, Next.js API Routes, Python, Flask, REST APIs, Cloudflare Workers
Database/Search: PostgreSQL, Supabase, Neon, pgvector, Typesense
Infrastructure: Cloudflare Workers, Vercel, CI/CD
Testing: Playwright, Selenium
```

| 변경 | 이유 |
|---|---|
| Flask → **FastAPI** | 스펙 §5·§14가 이미 FastAPI/TerraTorch 조합을 지정, ML 서빙 표준에도 더 부합 |
| Supabase + Neon 동시 나열 → **Supabase 우선 택1(포터블 설계), Neon은 확정 대안** | 두 개를 동시 프로덕션에 쓸 이유 없음. 스코프 명확화 |
| pgvector → **MVP 제외** (필요시 무료 확장으로 추가) | 현재 임베딩/시맨틱 검색 요구 없음 |
| Typesense → **제외** | 이 데이터 규모(수만 건)에서 Postgres 내장 검색으로 충분, 별도 인프라 비용만 추가 |
| Selenium → **제거** | Playwright와 완전 중복 |
| **누락 추가**: Cloudflare R2, GPU 추론 호스팅(Modal/RunPod), pytest, PostGIS 명시, GitHub Actions | 스펙의 핵심 아키텍처 요소인데 원안에 없었음 |

---

## 3. 결정 대기 항목

- Public 열람을 완전 무인증으로 설계할지 여부 (MAU/과금 계산에 직결, §2.3)
- Modal vs RunPod 실제 단가 비교 (아직 미검증 — 계약 전 조사 필요)
- 자체 호스팅 전환 트리거 기준치 (예: DB 컴퓨트가 Medium 애드온을 3개월 연속 초과하면 전환 검토 등, 아직 미정)
