# 평가 결과 baseline-1

## 실행 조건

| 항목 | 값 |
|---|---|
| run_id | baseline-1 |
| date_utc | 2026-11-25 15:50 |
| git_head | 8233fb6 |
| split | dev |
| cases_lock | 4efeb937d8427e8a |
| service_models | gpt-5-mini-2025-08-07, text-embedding-3-small |
| judge | openai/gpt-5-2025-08-07 |
| prices_as_of | 2026-11-25 |
| concurrency | 5 |
| wall_min | 65.1 |
| warmup | ready |

## 지표

| 지표 | 값 |
|---|---|
| cases | 38 |
| conversation_cases | 33 |
| errors | 0 |
| M2_recall | 96.4 |
| M2_precision | 51.9 |
| M3_questions_mean | 11.06 |
| M3_questions_max | 18 |
| completion_rate | 100.0 |
| M12_reasked_total | 46 |
| M12_reasked_per_case | 1.39 |
| undetected_question_turns | 0 |
| M4_keyword_accuracy | 94.7 |
| M6_primary_label_match | 27.5 |
| rag_failed | 0 |
| M5_unsupported_mishandled | 100.0 |
| M1_judge_fabricated_total | 123 |
| M1_cases_with_fabrication | 32 |
| M1_rule_numeric_total | 12 |
| M8_judge_assertions | 0 |
| M8_regex_assertions | 0 |
| judged_cases | 33 |
| reply_shows_None | 0 |
| M9_pii_in_requests | 384 |
| M9_by_kind | {'extract': 330, 'compose': 30, 'rag_keyword': 12, 'embedding': 12} |
| llm_calls | 560 |
| llm_calls_unattributed | 85 |
| M11_service_cost_usd | 3.1566 |
| M11_turn_latency_p50_s | 37.1 |
| M11_turn_latency_p95_s | 49.3 |
| judge_cost_usd | 1.5104 |
| judge_failed | 0 |
| models_missing_price | [] |

## 호출 종류별 (M11)

| 종류 | 호출 | p50 초 | p95 초 | 출력 토큰 | 추론 토큰 | 비용 USD |
|---|---|---|---|---|---|---|
| compose | 33 | 32.6 | 42.4 | 86443 | 68864 | 0.1944 |
| embedding | 38 | 0.4 | 1.0 | 0 | 0 | 0.0001 |
| extract | 399 | 37.0 | 49.3 | 1380598 | 1003136 | 2.8252 |
| rag_keyword | 38 | 3.1 | 6.1 | 6832 | 6400 | 0.0238 |
| rag_summary | 52 | 10.8 | 16.6 | 49858 | 36032 | 0.1131 |

## 해석 (2026-11-26 작성, 실행은 2026-11-25 15:50 UTC = 11-26 00:50 KST)

측정 커밋은 8233fb6이다. 이후 main에 들어간 #6, #7은 서버 의존성·테스트·CORS만 바꿨고 `ai/`, `eval/`, compose 파일은 그대로다 (`git diff 8233fb6 3c37716 -- ai eval compose.yaml compose.eval.yaml` 결과 없음). 평가는 AI를 직접 호출하는 경로 A라 서버 변경의 영향을 받지 않는다.

첫 기준선이다. 5단계 개선의 비교 대상이며, 개발 세트 1회 실행이라 같은 사례를 다시 돌렸을 때의 흔들림은 아직 모른다.

| 지표 | 값 | 판단 |
|---|---|---|
| M2 재현율 / 정밀도 | 96.4% / 51.9% | 서술에 있는 정보는 거의 다 잡지만, 채웠다고 판단한 항목의 절반은 실제로 서술에 없다 |
| M3 질문 수 | 평균 11.1, 최대 18 | |
| M12 재질문 | 사례당 1.39회 (총 46회) | 시험 실행(사례당 3회)보다 낮다. 표본 차이로 본다 |
| M4 판례 검색 키워드 | 94.7% | 키워드는 대부분 맞다 |
| M6 판례 주된 죄명 일치 | 27.5% | 키워드는 맞는데 보여 주는 판례가 엉뚱하다. 문제는 검색 단계에 있다 |
| M5 미지원 죄목 오처리 | 100% (5/5) | 알려진 결함 F11. `ai/baroai.py`의 `_normalize_offense`가 모르는 죄목을 모두 사기로 바꾼다 |
| M1 지어낸 사실 | 33건 중 32건, 총 123개 (사례 중앙값 4) | 판정 표본 12개를 훑어보니 대부분 실제 문제(입력에 없는 증거 부존재 단정, 정신적 피해 추가, 근거 없는 사실)였고, 일부는 입력에서 추론 가능한 경계 사례였다. 사람 검수(20%)를 거쳐 확정한다 |
| M8 법적 단정 | 0 | |
| M9 개인정보 원문 전송 | LLM 요청 384건 | 알려진 결함 S05. 이름·전화·계좌가 정보 추출 요청에 그대로 들어간다 |
| M11 한 턴 응답 | 중앙값 37.1초, p95 49.3초 | 정보 추출 호출(중앙값 37초, 추론 토큰이 출력의 73%)이 대부분을 차지한다 |
| 비용 | 서비스 3.16달러 + 판정 1.51달러 | 서비스 비용의 90%가 정보 추출 호출 |

개선 우선순위 근거: 응답 시간과 비용 모두 정보 추출 호출에 몰려 있고, 지어낸 사실과 정밀도 문제도 같은 호출의 결과에서 시작된다. 5단계는 정보 추출부터 본다.
