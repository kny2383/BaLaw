# 평가 (eval)

바로 서비스의 AI 품질을 바깥에서 재는 도구 모음이다. 지표 정의와 실행 규칙은 `docs/metrics.md`를 따른다.

## 구성

| 경로 | 내용 | 상태 |
|---|---|---|
| `llm_proxy.py` | OpenAI 요청 기록 장치. 호출마다 모델·토큰·지연·요청 본문을 기록하고 실패를 주입한다 | 완료 |
| `cases/` | 평가 사례 53건. 사례 하나가 YAML 파일 하나 | 완료 |
| `cases/_template.yaml` | 사례 작성 양식 | 완료 |
| `run_eval.py` | 평가기. 사례를 모의 사용자로 진행하고 지표를 계산 (경로 A) | 완료 |
| `judge.py` | 판정 모델 호출 계층. 공급자를 바꿀 수 있게 분리 (결정 0002) | OpenAI만 구현 |
| `prices.json` | 모델 판본별 단가와 기준 날짜 | 완료 |
| `check_cases.py` | 사례 형식·정답 잠금 검사 (CI에서도 실행) | 완료 |
| `results/` | 실행별 요약 (커밋) | - |
| `runs/` | 실행 기록. 사례 서술과 요청 본문이 들어 있어 git에서 제외 | - |

## 기록 장치와 함께 띄우기

```bash
docker compose -f compose.yaml -f compose.eval.yaml up -d
docker compose -f compose.yaml -f compose.eval.yaml exec redis redis-cli FLUSHDB   # 판례 요약 캐시 비우기
```

기록은 `eval/runs/llm_calls.jsonl`에 쌓인다. 실행 이름과 사례 이름은 제어 주소로 붙인다.

```bash
curl -X POST localhost:8090/_control -d '{"run_id":"baseline-1","case_id":"fraud-used-goods-01"}'
```

실패 주입 (지표 M10):

```bash
curl -X POST localhost:8090/_control -d '{"fail_rate":1.0,"fail_mode":"http","seed":1}'   # 모든 채팅 호출을 500으로
curl -X POST localhost:8090/_control -d '{"fail_rate":0}'                                  # 해제
```

## 사례 작성 원칙

- 모든 인물·계좌·전화번호·주소는 가상이다. 평가기는 사례 원문을 서비스와 판정 모델(외부 API)로 그대로 보내므로 실제 사용자 서술은 절대 넣지 않는다.
- `split: holdout`인 사례는 프롬프트를 고치는 동안 열어 보지 않는다.
- 필수 정보 12개마다 "처음 서술에 있었는지"와 "물으면 돌려줄 답"을 적는다. 모르는 항목은 실제 사용자처럼 "모르겠어요"라고 적는다.
- 지어낸 사실(M1)은 처음 서술과 모의 사용자가 실제로 한 답 전체를 근거로 판정한다.

## 평가 실행

```bash
docker compose -f compose.yaml -f compose.eval.yaml up -d
python3 eval/run_eval.py --run-id baseline-1 --split dev --flush-cache
python3 eval/run_eval.py --run-id try-1 --only fraud-used-goods-01 vague-01   # 일부 사례만
```

- 진행 순서는 프론트와 같다: 대화 시작 → 판례 검색 대기 → 고정 문장으로 첫 질문 요청 → 모의 사용자 답변 반복 → 초안 생성 → 판정.
- AI가 물은 항목은 응답의 `_asked_count` 변화로 알아낸다. 정답에 없는 선택 항목을 물으면 "잘 모르겠어요."라고 답한다.
- 실행 전에 AI를 한 번 예열하고, `--flush-cache`면 판례 요약 캐시를 비운다.
- 판정 모델은 `--judge-provider`, `--judge-model`로 고른다. 기본은 `openai/gpt-5-2025-08-07`. 키는 환경 변수가 없으면 `ai/.env`에서 읽는다.
- 결과: `eval/runs/<run-id>/` (사례별 기록, git 제외), `eval/results/<run-id>.md` (요약, 커밋).

2026-11-25 시험 실행 기준 대략의 비용과 시간 (사례 2건):

| 항목 | 값 |
|---|---|
| 서비스 비용 | 대화 사례 1건당 약 0.1달러 |
| 판정 비용 | 1건당 약 0.05달러 |
| 시간 | 1건당 6~10분 (한 턴 30~40초). 5건 동시 실행 |

개발 세트(38건, 대화 33건) 1회는 약 5달러, 50분 안팎으로 예상한다.

## 알려진 한계

- 지표 M7(서버 경유 DOCX 검사)과 M10(실패 주입 실행)은 아직 평가기에 없다.
- M12는 "이미 답한 항목을 다시 묻는 횟수"만 센다. 답변 앞 요약 문장에서 같은 지적을 반복하는 경우는 아직 세지 않는다.
- M1·M8 판정은 표본 20%를 사람이 다시 보고 결과에 적는다.
- 판례 요약 호출처럼 사건 서술이 요청에 없는 호출은 사례를 특정하지 못한다 (`llm_calls_unattributed`). 개인정보 검사(M9)는 모든 호출을 대상으로 한다.
