# 바로(BaLaw)

AI 고소장 작성 도우미 서비스. 사용자가 사건을 일상어로 설명하면, 고소장에 필요한 사실관계를 항목별로 정리하고 빠진 정보를 질문으로 보완해 표준 양식의 초안을 만든다.

## 레포 구조

| 폴더 | 내용 | 원래 레포 |
|---|---|---|
| `docs/` | 요구사항, 기획 대 구현 대조표, 품질 지표, 결정 기록 | - |
| `server/` | 백엔드 API (FastAPI, PostgreSQL) | capston-design-baro/Baro-Server |
| `ai/` | AI 서비스 (FastAPI, OpenAI, ChromaDB) | capston-design-baro/Baro-AI |
| `web/` | 프론트엔드 (React, Vite) | capston-design-baro/Baro-Front |
| `deploy/` | 운영 배포 구성 (Docker Compose, GitHub Actions) | capston-design-baro/Baro-Deploy |

원래 4개 레포의 커밋 기록은 각 폴더에 그대로 보존했다. 레포를 합친 이유와 진행 순서는 `docs/`를 참고한다.

## 로컬 전용 데이터

대용량 데이터는 레포에 넣지 않는다. AI 코드가 읽는 위치에 직접 두고 git에서 제외한다.

| 경로 | 내용 | 없을 때 |
|---|---|---|
| `ai/data/rag_db/` | 판례 벡터 DB (ChromaDB, 약 640MB) | `RAG_DB_URL`의 S3 주소에서 내려받거나 `ai/scripts/generate_embeddings.py`로 다시 생성 |
| `ai/crawl/prec_labeled_final.jsonl` | 죄명 라벨이 붙은 형사 판례 11,396건 (약 380MB) | `ai/crawl/` 수집 스크립트로 다시 생성 |
| `local-data/` | 그 밖의 로컬 사본 | - |

각 폴더의 `.env`는 `.env.example`을 복사해 만든다. `.env`는 커밋하지 않는다.
