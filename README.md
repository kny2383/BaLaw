# 바로(BaLaw)

AI 고소장 작성 도우미 서비스. 사용자가 사건을 일상어로 설명하면, 고소장에 필요한 사실관계를 항목별로 정리하고 빠진 정보를 질문으로 보완해 표준 양식의 초안을 만든다.

## 품질 개선 결과

AI 품질을 평가 사례 53건(모두 가상)으로 재고, 문제마다 원인을 찾아 고친 뒤 다시 쟀다. 과정과 숫자의 출처는 [`docs/case-study.md`](docs/case-study.md)에 있다.

| 문제 | 처음 | 지금 |
|---|---|---|
| 한 턴 응답 시간 (중앙값) | 37.1초 | 11.4~12.6초 |
| 초안의 지어낸 사실 | 초안 33건 중 32~33건에 있음 | 10건 중 0~1건, 보류 세트 13건 중 0건 |
| LLM 요청에 실린 식별정보 원문 | 384건 | 0건 |
| 미지원 죄목을 지원하는 것처럼 처리 | 100% | 0% |
| 판례의 주된 죄명이 사건과 맞음 | 23.8% | 71.9% |
| 답한 항목을 다시 물음 (같은 조건) | 16회 | 5회 |
| LLM 실패를 정상처럼 돌려줌 | 12개 조합 중 2개 | 0개 |

처음과 지금 사이에 서비스 모델, 판정 모델, 판정 기준이 바뀌었으므로 지어낸 사실의 두 숫자는 같은 자로 잰 것이 아니다. 단계마다 같은 조건으로 잰 전후와 남은 문제는 위 문서에 있다.

| 문서 | 내용 |
|---|---|
| [`docs/case-study.md`](docs/case-study.md) | 문제 숫자 → 원인 → 조치 → 결과 숫자 |
| [`docs/roadmap.md`](docs/roadmap.md) | 할 일과 진행 상황 |
| [`docs/metrics.md`](docs/metrics.md) | 지표 M1~M12의 정의 |
| [`docs/decisions/`](docs/decisions/) | 범위, 모델, 대화 흐름 제어에 대한 결정 기록 |
| [`eval/README.md`](eval/README.md) | 평가 도구와 실행 방법 |
| [`eval/results/`](eval/results/) | 실행별 결과 |

## 레포 구조

| 폴더 | 내용 | 원래 레포 |
|---|---|---|
| `docs/` | 요구사항, 기획 대 구현 대조표, 품질 지표, 결정 기록 | - |
| `server/` | 백엔드 API (FastAPI, PostgreSQL) | capston-design-baro/Baro-Server |
| `ai/` | AI 서비스 (FastAPI, LangGraph, OpenAI, ChromaDB) | capston-design-baro/Baro-AI |
| `eval/` | 평가 사례, 평가기, 결과 | - |
| `web/` | 프론트엔드 (React, Vite) | capston-design-baro/Baro-Front |
| `deploy/` | 운영 배포 구성 (Docker Compose, GitHub Actions) | capston-design-baro/Baro-Deploy |

원래 4개 레포의 커밋 기록은 각 폴더에 그대로 보존했다. 레포를 합친 이유와 진행 순서는 `docs/`를 참고한다.

## 작업 방식

- `main` 하나만 두고, 모든 변경은 작업 브랜치에서 PR로 올린다 (GitHub Flow).
- PR은 CI를 통과해야 병합된다. CI는 바뀐 폴더만 검사한다.

  | 검사 | 대상 |
  |---|---|
  | Python 문법 | `server/`, `ai/`, `eval/` |
  | 서버 린트(ruff)·테스트(pytest) | `server/` |
  | 평가 사례 형식·정답 잠금 | `eval/` (`python eval/check_cases.py`) |
  | 서버·AI 이미지 빌드 | `server/`, `ai/` |
  | 프론트 린트·빌드 | `web/` |
  | 비밀 값 | 전체 |

- 배포 시점은 버전 태그와 GitHub Releases로 표시한다.
- 레포 통합 초기 작업(2026-11-25, 4개 레포 병합부터 평가 사례 추가까지)은 PR 없이 `main`에 직접 커밋했다. 이후 작업은 모두 PR로 진행한다.

## 로컬 실행

```bash
cp server/.env.example server/.env   # 값 채우기
cp ai/.env.example ai/.env           # 값 채우기 (OPENAI_API_KEY 필수)
docker compose up -d --build         # PostgreSQL, Redis, AI, 서버

cd web && cp .env.example .env && pnpm install && pnpm dev   # 프론트
```

| 서비스 | 주소 |
|---|---|
| 서버 API | http://localhost:8000 (헬스 체크 `/health`) |
| AI | http://localhost:8001 |
| 프론트 | http://localhost:5173 |
| PostgreSQL | localhost:5432 (baro / baro) |

종료는 `docker compose down`, DB까지 지우려면 `docker compose down -v`.

## 로컬 전용 데이터

대용량 데이터는 레포에 넣지 않는다. AI 코드가 읽는 위치에 직접 두고 git에서 제외한다.

| 경로 | 내용 | 없을 때 |
|---|---|---|
| `ai/data/rag_db/` | 판례 벡터 DB (ChromaDB, 약 640MB) | `RAG_DB_URL`의 S3 주소에서 내려받거나 `ai/scripts/generate_embeddings.py`로 다시 생성 |
| `ai/crawl/prec_labeled_final.jsonl` | 죄명 라벨이 붙은 형사 판례 11,392건 (약 370MB). 벡터 DB에는 11,393건이 들어 있다 | `ai/crawl/` 수집 스크립트로 다시 생성 |
| `local-data/` | 그 밖의 로컬 사본 | - |

각 폴더의 `.env`는 `.env.example`을 복사해 만든다. `.env`는 커밋하지 않는다.
