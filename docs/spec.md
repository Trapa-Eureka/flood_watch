# PH Flood/Typhoon Watch — 위성 기반 홍수·태풍 피해 매핑 — 착수 스펙

> `docs/spec.md`로 새 레포(가칭 `ph-flood-watch`, Trapa-Eureka 조직)에 넣고 16장 프롬프트로 Claude Code 시작.
> 이 프로젝트는 세무/에이전트 계열과 완전히 다른 축이다: PH Fuel Watch의 파이프라인 구조(Workers Cron + 수집 + MapLibre)를 그대로 재사용하되, OCR 대신 위성 이미지 추론이 들어간다.

## 0. 한 줄 요약

Sentinel-1/2 위성 데이터를 자동 수집 → Prithvi 파운데이션 모델로 침수 영역을 추출 → 행정경계·인구·건물 데이터와 겹쳐 "어디가, 얼마나, 몇 명이" 피해를 입었는지 근실시간으로 계산 → 지도 대시보드와 리포트로 제공한다. 동시에 이 파이프라인의 STAC 수집기·모델 추론 서비스는 Solafune 대회 참가와 불법 채굴 탐지 트랙에 그대로 재사용된다.

## 1. 왜 이것부터인가

- Solafune 채용공고가 요구하는 기술(위성 이미지 CNN/세그멘테이션, GDAL/rasterio/GeoPandas, 지도 시각화, 풀스택 배포)을 실제로 구현한 결과물이 곧 지원 증거가 된다.
- Solafune 자신이 홍수 분석·피해 평가·재난 대응을 사업 영역으로 삼고 있어, 이 프로젝트는 "그 회사가 하는 일을 개인이 얼마나 재현할 수 있는가"를 직접 보여준다.
- PH의 기존 홍수 시스템(Project NOAH, PAGASA FFWS)은 우량계·수문 모델 기반의 **사전** 위험지도이지, 태풍이 지나간 뒤 실제 침수 범위를 위성으로 근실시간 확인하는 **사후** 레이어가 아니다 — 이 틈이 화이트스페이스다.
- Sentinel 데이터는 상업적 이용을 포함해 완전 무료이고, Prithvi 같은 오픈 파운데이션 모델에 이미 홍수 매핑용 파인튜닝 체크포인트가 있어 "몇 년 경력의 리모트센싱 전문가"가 아니어도 엔지니어링으로 접근 가능하다.
- 기존 스택(PostGIS는 Bayni, MapLibre·Workers Cron은 PH Fuel Watch에서 이미 검증됨)을 그대로 재사용하면서 새 스킬(PyTorch, GDAL, Docker, 클라우드 GPU)을 붙일 수 있다.
- PH는 매년 반복적으로 태풍 피해를 입는다 — 한 번 만들면 수요가 계속 재발생한다.

## 2. 범위

### In (MVP)

1. 감시 대상 AOI(강 유역) 수동 등록: 마리키나, 카가얀, 비콜/나가, 팜팡가.
2. 이벤트 수동 등록(태풍/모니터링 날짜 지정) → STAC에서 Sentinel-1 GRD(사후, SAR) + Sentinel-2 L2A(사전 베이스라인) 자동 수집.
3. 전처리: 재투영, 타일링, SAR 보정/스펙클 필터, 구름마스크.
4. Prithvi-EO-2.0 + 홍수 파인튜닝 체크포인트로 침수 확률 래스터 생성.
5. 상시 수역 마스크와 차분해 "이번 이벤트로 인한 신규 침수"만 추출, 폴리곤화.
6. 시군(ADM3) 경계와 오버레이해 침수 면적/비율 계산. 바랑가이(ADM4)는 데이터 품질에 따라 가능한 곳만.
7. WorldPop 인구격자 + 건물 풋프린트(OSM/Open Buildings)로 추정 피해 인구·건물 수 계산.
8. Next.js + MapLibre 대시보드: AOI/이벤트 선택, 전후 비교 슬라이더, 침수 오버레이, 피해 통계 패널.
9. 이벤트별 PDF 리포트 생성(기존 PDF 생성기 재사용).
10. Docker로 패키징된 추론 서비스 + 클라우드 GPU/CPU 배포.

### Out (지금 안 함)

- 실시간 자동 트리거(PAGASA 태풍 특보 파싱) — v2. MVP는 관리자가 수동으로 이벤트 등록.
- 산사태·해일 피해 모델링 — 홍수만.
- 전국 전체 AOI — 4개 유역으로 시작.
- 보험사 API 연동, 자동 파라메트릭 트리거 — 데이터 검증 후 별도 트랙.
- 공식 재해 판정/경보 대체 — 항상 "AI 추정치"로 표기, PAGASA/LGU 공식 정보 확인을 안내.

## 3. 2–3일 기술 검증 (go/no-go, 5주 스프린트 전에 먼저)

전면 개발 전에 핵심 가설부터 확인한다: **Prithvi + Sentinel-1이 실제 PH 태풍 침수를 잡아내는가.**

- 검증 대상 이벤트: 2024년 10월 Kristine(Trami) — 비콜·마리키나 대규모 침수(잘 기록됨, 마리키나 강 경보 2단계). 필요시 2025년 7월 몬순 홍수(Wipha/Co-may, 마리키나·카가얀), 2025년 8월 케손시티 홍수도 백테스트 후보.
- 절차: 마리키나 AOI로 이벤트 전후 Sentinel-1 GRD 다운로드(Copernicus Data Space Ecosystem STAC) → Prithvi sen1floods11 체크포인트로 추론 → 뉴스에 보도된 침수 지역(말라본, 마리키나 강변 등)과 육안 대조.
- 통과 기준: 보도된 침수 지역의 대략적 위치·규모가 모델 출력과 방향이 맞아야 한다(픽셀 단위 정밀도 아님, "이 동네가 잠겼다"는 신호를 잡는지가 관건).
- 실패 시: SAR 단독 대신 Sentinel-2 광학(구름 없는 날짜 한정) 보조, 또는 Clay 모델 병행 비교, 또는 도시 지역(레이더 음영·다중경로 문제)은 제외하고 농촌·하천 유역만 우선 타겟으로 축소.

## 4. 사용자/역할

| 역할 | 설명 |
|---|---|
| admin (본인) | AOI/이벤트 등록, 파이프라인 실행, 품질 검수 |
| viewer (LGU DRRMO, NGO) | 대시보드 열람, 리포트 다운로드 |
| public | 공개 이벤트에 한해 열람 가능(신뢰 구축용 무료 티어) |

## 5. 아키텍처

```
[관리자] 이벤트 등록(AOI + 날짜)
   → STAC 수집기(Copernicus Data Space / AWS Earth Search)
   → R2 원본 저장
   → 전처리(rasterio/GDAL: 재투영·타일링·SAR 보정·구름마스크)
   → Prithvi-EO-2.0 추론 서비스(FastAPI + PyTorch + TerraTorch, Docker)
   → 침수 확률 래스터 → 상시수역 차분 → 폴리곤화
   → 행정경계/인구/건물 오버레이 → exposure_stats
   → COG/타일 R2 업로드 → PostGIS 저장
   → Next.js + MapLibre 대시보드 / PDF 리포트
```

- 프론트: Next.js, MapLibre GL(Fuel Watch 재사용 패턴)
- DB: PostgreSQL + PostGIS(Supabase/Neon, Bayni와 동일 패턴)
- 저장: Cloudflare R2(원본 씬 + COG + 타일)
- 오케스트레이션: Cloudflare Workers Cron(관리자 트리거 후 상태 폴링), 무거운 추론은 별도 컨테이너
- 추론 서비스: Python FastAPI + PyTorch + rasterio/GDAL/GeoPandas + IBM TerraTorch(Prithvi 로더), Docker 이미지, 스팟 GPU 또는 CPU 배치 실행(이벤트당 씬 몇 장이라 실시간 지연 필요 없음 — 배치로 충분, 비용은 이벤트당 몇 달러 수준으로 추정)

## 6. 데이터 모델 (스케치)

```sql
aois (id, name, kind text, geom geometry(Polygon,4326), watch_priority int, created_at)

events (id, aoi_id, name, kind text, -- typhoon | monsoon | manual | backtest
  pre_event_date date, post_event_date date, status text, created_at)

scene_refs (id, event_id, stac_id text, collection text, -- sentinel-1-grd | sentinel-2-l2a
  role text, -- baseline | post_event
  acquired_at timestamptz, footprint geometry(Polygon,4326), storage_key text)

inference_runs (id, event_id, model text, model_version text,
  input_scene_ids jsonb, started_at, finished_at, status, metrics jsonb)

flood_extents (id, event_id, run_id, geom geometry(MultiPolygon,4326),
  area_km2 numeric, confidence_mean numeric, raster_storage_key text)

admin_boundaries (id, level text, -- adm3_municipality | adm4_barangay
  name, psgc_code text, geom geometry(MultiPolygon,4326), source text, vintage date)

exposure_stats (id, event_id, admin_boundary_id,
  flooded_area_km2 numeric, flooded_area_pct numeric,
  est_population_affected numeric, est_buildings_affected int,
  population_source text, building_source text)

reports (id, event_id, pdf_storage_key, generated_at)

pipeline_events (id, run_id, step, input jsonb, output jsonb, status, created_at) -- insert-only
```

## 7. 파이프라인 단계

| 단계 | 설명 |
|---|---|
| aois.list_watched | 감시 대상 AOI 목록 |
| events.create | 이벤트 등록(AOI, 날짜, 종류) |
| scenes.fetch | STAC에서 S1 GRD(사후) + S2 L2A(베이스라인) 검색·다운로드 |
| preprocess.run | 재투영, 타일링, SAR 보정/스펙클 필터, 구름마스크 |
| inference.run | Prithvi 체크포인트로 침수 확률 래스터 생성 |
| baseline.diff | 상시 수역 마스크 차분 → 신규 침수만 추출 |
| vectorize.extract | 래스터 → 폴리곤, 육지 클립 |
| exposure.compute | 행정경계·인구격자·건물풋프린트 오버레이 |
| tiles.publish | COG/타일 R2 업로드 |
| reports.generate | PDF 리포트 |

각 단계 입출력은 `pipeline_events`에 insert-only로 기록(재현성·감사용).

## 8. 데이터 소스

| 종류 | 소스 | 비고 |
|---|---|---|
| SAR(사후, 구름 무관) | Sentinel-1 GRD | Copernicus Data Space Ecosystem STAC, 상업적 이용 포함 완전 무료 |
| 광학(베이스라인/시각화) | Sentinel-2 L2A | 동일 |
| 모델 | Prithvi-EO-2.0 + sen1floods11 체크포인트 | IBM/NASA 오픈소스, HuggingFace/TerraTorch |
| 행정경계 | HDX PH ADM3(시군, 안정적), ADM4(바랑가이, 커뮤니티 소스 — 최신성 불확실, 있는 곳만 사용) |
| 인구 | WorldPop 격자 인구 |
| 건물 | OSM 건물 풋프린트 / Google Open Buildings |

**표기 의무**: 모든 지도·리포트에 "Contains modified Copernicus Sentinel data [YEAR]" 부착. 모든 출력에 "AI 추정치이며 공식 재해 판정이 아님, PAGASA/지자체 공식 발표를 함께 확인할 것" 문구 고정.

## 9. 5주 스프린트 (기술검증 통과 후)

**Week 1 — 파이프라인 뼈대**
레포 스캐폴드(Fuel Watch 구조 차용), PostGIS 스키마, R2 버킷. STAC 클라이언트로 마리키나 AOI 테스트 씬 다운로드. 전처리(재투영/타일링/SAR 보정/구름마스크) 구현.

**Week 2 — 모델 통합**
TerraTorch로 Prithvi + sen1floods11 로드, 타일 단위 추론 → 전체 씬 스티칭. 상시수역 베이스라인 차분 로직.

**Week 3 — 노출도 계산**
ADM3(+가능하면 ADM4) 경계 적재, WorldPop·건물 데이터 적재, `exposure_stats` 계산. 래스터 벡터화, 전후 타일 페어 생성 및 R2 업로드.

**Week 4 — 대시보드 & 배포**
Next.js/MapLibre 대시보드(AOI/이벤트 선택, 전후 슬라이더, 통계 패널), PDF 리포트, 관리자 트리거 UI. 추론 서비스 Docker화 및 스팟 GPU/CPU 배포, Workers Cron 연동.

**Week 5 — 검증·확장·공개**
Kristine/Trami(2024-10), 2025년 7월 몬순 홍수, 2025년 8월 케손시티 홍수 등 과거 이벤트로 백테스트, 정확도 정직하게 문서화. 4개 유역으로 AOI 확장. 랜딩 페이지 + LGU DRRMO/NGO 대상 베타 신청 아웃리치. 추론 코어 오픈소스 공개, 대시보드/리포트는 비공개 제품으로 분리.

## 10. 가격/고객 가설 (검증 대상, 세일즈 사이클이 김을 전제)

- LGU DRRMO: 이벤트 리포트 건당 또는 월 구독 — 조달 절차가 느려 초반엔 무료 베타로 사례 확보 우선.
- NGO(재해대응 조정): API/리포트 접근, 보조금 예산 존재.
- 보험사(파라메트릭 홍수/농업보험 트리거): 최고 지불의사, 가장 긴 세일즈 사이클 — v2.
- 언론/연구자: 무료 제공 → 보도 노출로 마케팅 채널화.
- 초반 2–3개월은 매출보다 백테스트 사례 3–5건 + 언론 노출을 목표로 잡는다.

## 11. 수용 기준 / 메트릭

- 기술검증 게이트 통과(3장 기준).
- 백테스트 3개 이벤트에서 모델 침수 범위와 보도된 침수 지역이 방향적으로 일치.
- 이벤트 등록 → 대시보드 반영 파이프라인 전체 실행 시간 24시간 이내.
- 4개 유역 AOI 상시 감시 상태.
- 5주 종료 시 LGU/NGO 베타 신청 3곳 이상 또는 언론 노출 1건 이상.

## 12. 리스크와 대응

| 리스크 | 대응 |
|---|---|
| 도시 지역 SAR 정확도(레이더 음영/다중경로) | MVP는 하천·농촌 유역 우선, 도시는 광학 보조 또는 향후 과제로 명시 |
| 바랑가이 경계 데이터 최신성 불확실 | 시군(ADM3)을 1차 집계 단위로, 바랑가이는 있는 곳만 "잠정" 표기 |
| GPU 배포/Docker 경험 부재 | 5주 중 4주차에 배치, 실패해도 CPU 배치로 폴백 가능하게 설계 |
| LGU/보험사 세일즈 사이클 김 | 초반 목표를 매출이 아닌 백테스트 사례·언론 노출로 설정 |
| Solafune 등 기존 사업자와 사업 영역 겹침 | 글로벌 경쟁이 아니라 PH 로컬 실행력·관계로 차별화, 경쟁이 아니라 참고 사례로 취급 |
| 모델이 "공식 경보"로 오인될 위험 | 모든 출력에 AI 추정치 표기 + 공식 정보 확인 안내 고정 |

## 13. CLAUDE.md에 추가할 항목

```
## PH Flood Watch 규칙
- 모든 지도/리포트 출력에 Copernicus 표기와 "AI 추정치, 공식 판정 아님" 문구를 고정한다. 제거 금지.
- pipeline_events에 모든 파이프라인 실행 입출력을 insert-only로 기록한다. 재현 불가능한 추론 실행 금지.
- admin_boundaries는 항상 source와 vintage를 함께 저장한다. 출처 불명 경계 데이터 사용 금지.
- 모델/전처리 파라미터는 config/model.ts 에만 둔다. 코드에 상수로 박지 않는다.
- 도시 지역(레이더 음영 위험)의 결과는 UI에서 낮은 신뢰도로 별도 표기한다.
```

## 14. Claude Code 첫 프롬프트

```
새 레포 ph-flood-watch를 시작한다. 스펙은 docs/spec.md. 오늘은 3장의 "2-3일 기술 검증" 단계만 한다.
전면 개발(5주 스프린트)은 이 검증이 통과된 뒤에 시작한다.

1) Python 환경 스캐폴드: rasterio, GDAL, geopandas, pystac-client, torch, terratorch 설치 가능한지 확인.
2) Copernicus Data Space Ecosystem STAC API로 마리키나 AOI(대략적 bbox는 조사해서 사용)의
   Sentinel-1 GRD 씬을 2024년 10월 Kristine/Trami 태풍 전후로 검색·다운로드하는 스크립트 작성.
3) 다운로드한 씬을 rasterio로 열어 기본 정보(밴드, 해상도, 좌표계) 출력하고, 
   PNG로 시각화해서 눈으로 확인 가능하게 만든다.
4) Prithvi-EO-2.0 + sen1floods11 체크포인트를 TerraTorch로 로드하는 최소 스크립트 작성(모델 다운로드까지).

각 단계 끝에 결과와 다음 단계를 보고. 5주 스프린트 코드는 아직 작성하지 않는다 — 이건 go/no-go 판단용 스파이크다.
```

## 15. 이어지는 트랙 (같은 파이프라인 재사용)

**Track A — Solafune 대회 참가**: 이 프로젝트의 STAC 수집기 + Prithvi 추론 서비스를 그대로 가져다 현재 열려 있는 대회 데이터셋에 적용. 추가 인프라 거의 없음. 2–3주 몰입이면 충분. 지원 중인 회사에 직접 제출할 수 있는 결과물.

**Track B — 불법 채굴/채석 탐지**: 같은 파이프라인에서 모델만 변화탐지(Sentinel-2 시계열 + 토지피복 분류)로 교체. 고객은 DENR/환경단체. 대시보드 셸 재사용.

**동결 유지**: 이전에 정리한 세무/에이전트 계열 아이디어(Tax Assistant 확장, mcp-automation-core)는 보류. 지금은 이 방향에 집중.
