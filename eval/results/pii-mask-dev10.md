# 평가 결과 pii-mask-dev10

## 실행 조건

| 항목 | 값 |
|---|---|
| run_id | pii-mask-dev10 |
| date_utc | 2026-11-26 10:39 |
| git_head | e62d505 |
| split | only 10 |
| cases_lock | 4efeb937d8427e8a |
| service_models | gpt-5-mini-2025-08-07, text-embedding-3-small |
| judge | none/gpt-5-2025-08-07 |
| judge_version | 2 |
| prices_as_of | 2026-11-25 |
| concurrency | 5 |
| wall_min | 12.0 |
| warmup | ready |

## 지표

| 지표 | 값 |
|---|---|
| cases | 10 |
| conversation_cases | 10 |
| errors | 0 |
| M2_recall | 90.0 |
| M2_precision | 42.2 |
| M3_questions_mean | 9.5 |
| M3_questions_max | 15 |
| completion_rate | 100.0 |
| M12_reasked_total | 10 |
| M12_reasked_per_case | 1.0 |
| undetected_question_turns | 0 |
| M4_keyword_accuracy | 90.0 |
| M6_primary_label_match | 30.0 |
| rag_failed | 0 |
| M5_unsupported_mishandled | None |
| M1_judge_fabricated_total | 0 |
| M1_cases_with_fabrication | 0 |
| M1_rule_numeric_total | 5 |
| M8_judge_assertions | 0 |
| M8_regex_assertions | 0 |
| judged_cases | 0 |
| reply_shows_None | 0 |
| M9_pii_in_requests | 0 |
| M9_by_kind | {} |
| llm_calls | 158 |
| llm_calls_unattributed | 42 |
| extract_reasoning_effort | ['low'] |
| M11_service_cost_usd | 0.4431 |
| M11_turn_latency_p50_s | 16.4 |
| M11_turn_latency_p95_s | 32.1 |
| judge_cost_usd | 0.0 |
| judge_failed | 10 |
| models_missing_price | [] |

## 호출 종류별 (M11)

| 종류 | 호출 | p50 초 | p95 초 | 출력 토큰 | 추론 토큰 | 비용 USD |
|---|---|---|---|---|---|---|
| compose | 10 | 27.4 | 37.4 | 27298 | 23552 | 0.0621 |
| embedding | 10 | 0.5 | 0.9 | 0 | 0 | 0.0 |
| extract | 109 | 16.3 | 31.1 | 159840 | 58880 | 0.335 |
| rag_keyword | 10 | 3.9 | 6.8 | 1647 | 1536 | 0.0058 |
| rag_summary | 19 | 12.5 | 19.8 | 17521 | 12608 | 0.0402 |

## 기준 실행과의 비교 (extract-structured-dev10, 커밋 21e2a9b)

바꾼 것은 식별정보 치환(S05)이다. 판정 모델은 돌리지 않았으므로 M1, M8은 없다 (위 표의 판정 항목은 0 또는 실패로 나온다).
이 실행에는 #25의 작성 프롬프트 수정도 들어 있다. 추출과 대화에는 영향이 없고 작성 호출에만 영향이 있다.

| 지표 | 치환 없음 | 치환 |
|---|---|---|
| M9 LLM 요청에 들어간 원문 식별정보 | 122 | 0 |
| M2 재현율 / 정밀도 (첫 턴) | 100.0% / 47.6% | 90.0% / 42.2% |
| M3 질문 수 평균 / 최대 | 10.1 / 15 | 9.5 / 15 |
| M12 재질문 | 8 | 10 |
| 완료율 | 100% | 100% |
| 한 턴 응답 중앙값 / p95 | 16.6초 / 21.1초 | 16.4초 / 32.1초 |
| 서비스 비용 (USD) | 0.439 | 0.443 |
| 응답과 초안에 남은 표식 (되돌려지지 않은 것) | 해당 없음 | 0 |
| 초안에 들어간 사례 인적정보 값 (10건 합계) | 7 | 10 |

## 읽은 것

- **원문 식별정보는 LLM 요청에 한 건도 없었다.** 이전에는 추출 104, 작성 8, 죄명 키워드 5, 임베딩 5건이었다. 이 숫자는 평가 사례의 인적정보 목록에 있는 값만 센 것이다. 이름과 주소는 평가기가 `known_pii`로 넘겼다 (입력 화면 값을 흉내 냄).
- **표식은 모두 되돌려졌다.** 질문 문장과 초안 20개 글에서 남은 표식은 없었고, 초안에 들어간 실제 이름·계좌 수는 줄지 않았다 (7 → 10).
- **첫 턴 재현율이 100% → 90%로 내려갔다.** 정답 30개 중 3개를 놓쳤다. 그중 2개가 표식이 가장 많은 pii-02 한 사례다 (`who`, `channel_or_place`: 집주인 이름과 주소가 표식으로 바뀐 자리). 모델이 표식을 "값이 있는 것"으로 읽지 못한 것으로 보인다. 나머지 1개(fraud-job-scam-04의 `method`)는 표식과 관계없는 항목이다.
- 놓친 항목은 대화에서 다시 물어 채워졌다. pii-02의 질문 수는 10 → 10으로 같고, 전체 평균도 늘지 않았다.

## 한계

- 10건, 1회 실행이다. 같은 10건의 재현율은 이전 실행들에서 90.0~100.0% 사이였다 (baseline 90.0, low 96.7, dialogue 93.3, structured 100.0). 이번 하락이 치환 때문인지 흔들림인지 이 실행만으로는 나눌 수 없다. 다만 놓친 3개 중 2개가 표식 자리라는 점은 치환의 영향을 가리킨다.
- 지어낸 사실(M1)은 재지 않았다.
- 가려지지 않는 값(입력 화면에 없는 이름, 닉네임, 상호, 형식이 다른 주소, 하이픈 없는 계좌번호)은 M9가 세지 못한다.
