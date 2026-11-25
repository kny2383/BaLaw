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

판례 벡터 DB 같은 대용량 데이터는 레포에 넣지 않고 `local-data/`에 둔다. 이 폴더는 git에서 제외된다.
