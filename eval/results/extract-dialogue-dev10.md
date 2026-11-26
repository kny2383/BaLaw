# 평가 결과 extract-dialogue-dev10

## 실행 조건

| 항목 | 값 |
|---|---|
| run_id | extract-dialogue-dev10 |
| date_utc | 2026-11-26 03:12 |
| git_head | 4591694 |
| split | only 10 |
| cases_lock | 4efeb937d8427e8a |
| service_models | gpt-5-mini-2025-08-07, text-embedding-3-small |
| judge | openai/gpt-5-2025-08-07 |
| judge_version | 2 |
| prices_as_of | 2026-11-25 |
| concurrency | 5 |
| wall_min | 13.9 |
| warmup | ready |

## 지표

| 지표 | 값 |
|---|---|
| cases | 10 |
| conversation_cases | 10 |
| errors | 0 |
| M2_recall | 93.3 |
| M2_precision | 56.0 |
| M3_questions_mean | 11.9 |
| M3_questions_max | 17 |
| completion_rate | 100.0 |
| M12_reasked_total | 16 |
| M12_reasked_per_case | 1.6 |
| undetected_question_turns | 0 |
| M4_keyword_accuracy | 90.0 |
| M6_primary_label_match | 30.0 |
| rag_failed | 0 |
| M5_unsupported_mishandled | None |
| M1_judge_fabricated_total | 42 |
| M1_cases_with_fabrication | 10 |
| M1_rule_numeric_total | 5 |
| M8_judge_assertions | 0 |
| M8_regex_assertions | 0 |
| judged_cases | 10 |
| reply_shows_None | 1 |
| M9_pii_in_requests | 149 |
| M9_by_kind | {'extract': 128, 'compose': 11, 'rag_keyword': 5, 'embedding': 5} |
| llm_calls | 180 |
| llm_calls_unattributed | 26 |
| extract_reasoning_effort | ['low'] |
| M11_service_cost_usd | 0.5233 |
| M11_turn_latency_p50_s | 15.6 |
| M11_turn_latency_p95_s | 18.6 |
| judge_cost_usd | 0.5691 |
| judge_failed | 0 |
| models_missing_price | [] |

## 호출 종류별 (M11)

| 종류 | 호출 | p50 초 | p95 초 | 출력 토큰 | 추론 토큰 | 비용 USD |
|---|---|---|---|---|---|---|
| compose | 10 | 24.9 | 29.0 | 26579 | 21312 | 0.0595 |
| embedding | 10 | 0.3 | 0.8 | 0 | 0 | 0.0 |
| extract | 131 | 15.6 | 18.6 | 203502 | 80384 | 0.4222 |
| rag_keyword | 10 | 2.5 | 4.7 | 1647 | 1536 | 0.0044 |
| rag_summary | 19 | 10.1 | 13.9 | 17561 | 12672 | 0.0372 |

## 해석 (2026-11-26 KST)

정보 추출 입력에 AI 질문을 함께 넣고 부분 세트 dev10(`eval/subsets/dev10.txt`, 10건)을 1회 실행했다. 비교 대상은 `extract-low-dev10`(같은 10건, 추론 강도 `low`, 사용자 발화만 입력)이다. 바뀐 것은 추출 입력 하나다: 사용자 발화마다 바로 앞의 AI 질문을 붙이고, 질문 줄은 맥락일 뿐이라는 규칙 두 줄을 프롬프트에 더했다. 포함되는 사용자 발화는 이전과 같다.

| 지표 | 사용자 발화만 (extract-low-dev10) | 질문 포함 | 변화 |
|---|---|---|---|
| 추출 재현율 / 정밀도 (M2) | 96.7% / 52.7% | 93.3% / 56.0% | 재현율 -3.4%p, 정밀도 +3.3%p |
| 질문 수 평균 (M3) | 11.0 | 11.9 | +0.9 |
| 재질문 (M12) | 13회 (사례당 1.3) | 16회 (사례당 1.6) | +3회 |
| 지어낸 사실 (M1, 판정 2판) | 49개 | 42개 | -7개 |
| 답변에 'None' 노출 | 0 | 1 | +1 |
| 한 턴 응답 중앙값 / p95 (M11) | 16.4초 / 20.2초 | 15.6초 / 18.6초 | 비슷 |
| 정보 추출 호출 비용 | 0.397달러 (121회) | 0.422달러 (131회) | 호출당 비용은 같음 |
| 완료율 / 오류 | 100% / 0 | 100% / 0 | 같음 |
| 판례 키워드 정확도 (M4) / 주된 죄명 일치 (M6) | 90.0% / 30.0% | 90.0% / 30.0% | 같음 |

판단:

- 방향이 엇갈린다. 정밀도와 지어낸 사실은 좋아진 쪽이고, 재현율·질문 수·재질문은 나빠진 쪽이다. 어느 쪽도 차이가 작고, 같은 조건을 다시 돌렸을 때의 흔들림을 아직 재지 않아 변경의 효과인지 구분할 수 없다.
- 기대했던 재질문 감소는 나타나지 않았다. 재질문 16회 중 6회는 날짜 항목이고, 모의 사용자의 답이 날짜가 아닌 경우("계좌이체요", "전화요")이거나 정확한 날짜가 없는 경우("올해 5월이요", "몰라요 작년 말쯤?")였다. 이런 재질문은 추출 입력이 아니라 질문 순서와 사례의 답 구성에서 온다.
- 사례별 질문 수는 -4에서 +3 사이로 움직였고(모욕 사례 `insult-01`은 4 → 7), 사례별 지어낸 사실 수는 -3에서 +1 사이였다.
- 'None' 노출 1건은 `insult-01`에서 추출 결과에 일시 항목의 요약 문장이 없을 때 생겼다. 요약이 없으면 질문 앞에 'None'이 붙는 것은 이전부터 있던 동작이다.
- 응답 시간과 호출당 비용은 변하지 않았다. 호출 수가 늘어난 것은 질문 수가 늘어서다.
- **이 변경은 main에 반영하지 않는다.** 좋아졌다는 근거가 없고, 줄이려던 재질문이 줄지 않았다. 코드는 병합하지 않은 브랜치 `feat/extract-dialogue-window`(`4591694`)에 남겨 둔다. 흔들림을 잰 뒤 다시 볼 수 있다.
- 다음 측정에서 비교할 기준은 그대로 `extract-low-dev10`이다.

한계: 부분 세트 10건, 1회 실행, 흔들림 미측정. 이 실행의 비용은 서비스 0.523달러 + 판정 0.569달러였다.
