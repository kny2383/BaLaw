# 평가 결과 extract-structured-dev10

## 실행 조건

| 항목 | 값 |
|---|---|
| run_id | extract-structured-dev10 |
| date_utc | 2026-11-26 03:38 |
| git_head | 21e2a9b |
| split | only 10 |
| cases_lock | 4efeb937d8427e8a |
| service_models | gpt-5-mini-2025-08-07, text-embedding-3-small |
| judge | openai/gpt-5-2025-08-07 |
| judge_version | 2 |
| prices_as_of | 2026-11-25 |
| concurrency | 5 |
| wall_min | 11.0 |
| warmup | ready |

## 지표

| 지표 | 값 |
|---|---|
| cases | 10 |
| conversation_cases | 10 |
| errors | 0 |
| M2_recall | 100.0 |
| M2_precision | 47.6 |
| M3_questions_mean | 10.1 |
| M3_questions_max | 15 |
| completion_rate | 100.0 |
| M12_reasked_total | 8 |
| M12_reasked_per_case | 0.8 |
| undetected_question_turns | 0 |
| M4_keyword_accuracy | 90.0 |
| M6_primary_label_match | 27.8 |
| rag_failed | 0 |
| M5_unsupported_mishandled | None |
| M1_judge_fabricated_total | 49 |
| M1_cases_with_fabrication | 10 |
| M1_rule_numeric_total | 5 |
| M8_judge_assertions | 1 |
| M8_regex_assertions | 0 |
| judged_cases | 10 |
| reply_shows_None | 0 |
| M9_pii_in_requests | 122 |
| M9_by_kind | {'extract': 104, 'compose': 8, 'rag_keyword': 5, 'embedding': 5} |
| llm_calls | 158 |
| llm_calls_unattributed | 27 |
| extract_reasoning_effort | ['low'] |
| M11_service_cost_usd | 0.4391 |
| M11_turn_latency_p50_s | 16.6 |
| M11_turn_latency_p95_s | 21.1 |
| judge_cost_usd | 0.5571 |
| judge_failed | 0 |
| models_missing_price | [] |

## 호출 종류별 (M11)

| 종류 | 호출 | p50 초 | p95 초 | 출력 토큰 | 추론 토큰 | 비용 USD |
|---|---|---|---|---|---|---|
| compose | 10 | 25.3 | 30.0 | 23015 | 17792 | 0.0523 |
| embedding | 10 | 0.2 | 0.8 | 0 | 0 | 0.0 |
| extract | 111 | 16.6 | 21.1 | 168459 | 64064 | 0.3498 |
| rag_keyword | 10 | 2.7 | 3.7 | 1520 | 1408 | 0.004 |
| rag_summary | 17 | 10.3 | 15.4 | 15163 | 10816 | 0.033 |

## 해석 (2026-11-26 KST)

정보 추출 호출의 출력을 죄목별 pydantic 스키마로 강제하고 부분 세트 dev10(`eval/subsets/dev10.txt`, 10건)을 1회 실행했다. 비교 대상은 `extract-low-dev10`(같은 10건, 추론 강도 `low`, 출력은 자유 형식 JSON)이다. 바뀐 것은 출력 형식 하나다. 프롬프트 문구와 추출 입력은 같다.

| 지표 | 자유 형식 (extract-low-dev10) | 구조화 출력 | 변화 |
|---|---|---|---|
| 추출 재현율 / 정밀도 (M2) | 96.7% / 52.7% | 100.0% / 47.6% | 재현율 +3.3%p, 정밀도 -5.1%p |
| 질문 수 평균 / 최대 (M3) | 11.0 / 17 | 10.1 / 15 | -0.9 |
| 재질문 (M12) | 13회 (사례당 1.3) | 8회 (사례당 0.8) | -5회 |
| 지어낸 사실 (M1, 판정 2판) | 49개 | 49개 | 같음 |
| 답변에 'None' 노출 | 0 | 0 | 같음 |
| 구조화 출력 실패 | 해당 없음 | 111회 중 0회 | |
| 한 턴 응답 중앙값 / p95 (M11) | 16.4초 / 20.2초 | 16.6초 / 21.1초 | 비슷 |
| 정보 추출 호출 비용 | 0.397달러 (121회) | 0.350달러 (111회) | 호출당 0.0033 → 0.0032달러 |
| 완료율 / 오류 | 100% / 0 | 100% / 0 | 같음 |
| 판례 키워드 정확도 (M4) | 90.0% | 90.0% | 같음 |

판단:

- 스키마는 실제 호출 111회에서 한 번도 실패하지 않았고, 응답 시간과 호출당 비용은 그대로다. 스키마가 요청에 실려도 비용이 늘지 않았다.
- 질문 수와 재질문은 줄어든 쪽이다. 다만 정밀도가 5.1%p 내려갔다. 스키마가 모든 슬롯에 값을 요구하므로, 이전에는 응답에서 빠지던 슬롯에 '있음'이 더 자주 붙었을 수 있다. 그렇다면 질문 수가 준 것의 일부는 묻지 않고 넘어간 것이다. 이 실행만으로는 확인하지 못했다.
- 정밀도 하락을 기록으로 나눠 보면, 첫 턴에 '있음'으로 판정한 슬롯이 55개에서 63개로 늘었고 그중 정답과 맞는 것은 29개에서 30개, 틀린 것은 26개에서 33개다. 틀린 것이 늘어난 슬롯은 `who`(3 → 6), `proof`(0 → 2), `to_whom`(5 → 6), `what_action`(1 → 2)이다. 자유 형식에서는 슬롯 값 자리에 '있음' 대신 인용문을 적은 경우가 2개 있었고(판정에서 '있음'이 아닌 것으로 처리됨), 구조화 출력에서는 이런 값이 나올 수 없다. 늘어난 8개 중 2개는 이것으로 설명되고 나머지는 흔들림과 구분하지 못했다.
- 두 실행 모두 틀린 '있음'은 `who`, `to_whom`, `timeline`, `why_believed`, `quote`처럼 "말했다"의 기준이 사람마다 다를 수 있는 슬롯에 몰려 있다. 정답 기준과 프롬프트 기준이 어긋나는지 따로 볼 필요가 있다.
- 구조화 출력 실패 0회는 기록 장치의 호출 기록으로 셌다: 추출 호출 111회 모두 스키마가 실렸고, 응답 상태 200이며, 본문이 `elements`와 `details`를 가진 JSON이다.
- 지어낸 사실 수는 같다. 사례별로는 -3에서 +4 사이로 움직였다.
- 어느 차이도 흔들림을 재지 않은 상태에서 변경의 효과라고 단정할 수 없다 (10건 1회).
- 판정이 단정 문장 1건(M8)을 잡았다: "피고소인의 범행에 관하여 수사하여 주시기를 요청드립니다." 초안 작성 호출의 출력이고 이 변경과 직접 관련은 없다.
- **이 변경을 반영한다.** 항목과 슬롯이 빠지거나 허용하지 않은 값이 오는 일을 형식으로 막고, 비용과 속도가 그대로이며, 나빠졌다고 단정할 지표가 없다. 정밀도 하락은 흔들림을 잴 때 같은 10건으로 다시 확인한다.
- 이후 측정의 비교 기준은 이 실행(`extract-structured-dev10`)이다.

측정 뒤 바꾼 것: 리뷰 지적에 따라, 구조화 출력을 받지 못하면 빈 결과로 진행하지 않고 오류(HTTP 502)로 알리게 했다. 이 실행에서는 실패가 없었으므로 위 숫자에 영향이 없다.

한계: 부분 세트 10건, 1회 실행, 흔들림 미측정. 이 실행의 비용은 서비스 0.439달러 + 판정 0.557달러였다.
