# 평가 (eval)

바로 서비스의 AI 품질을 바깥에서 재는 도구 모음이다. 지표 정의와 실행 규칙은 `docs/metrics.md`를 따른다.

## 구성

| 경로 | 내용 | 상태 |
|---|---|---|
| `llm_proxy.py` | OpenAI 요청 기록 장치. 호출마다 모델·토큰·지연·요청 본문을 기록하고 실패를 주입한다 | 완료 |
| `cases/` | 평가 사례. 사례 하나가 YAML 파일 하나 | 작성 중 |
| `cases/_template.yaml` | 사례 작성 양식 | 완료 |
| 평가기 | 사례를 모의 사용자로 진행하고 지표를 계산 | 예정 |
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

- 모든 인물·계좌·전화번호·주소는 가상이다.
- `split: holdout`인 사례는 프롬프트를 고치는 동안 열어 보지 않는다.
- 필수 정보 12개마다 "처음 서술에 있었는지"와 "물으면 돌려줄 답"을 적는다. 모르는 항목은 실제 사용자처럼 "모르겠어요"라고 적는다.
- `allowed_facts`에 없는 사실이 초안에 나오면 지어낸 사실(M1)로 센다.
