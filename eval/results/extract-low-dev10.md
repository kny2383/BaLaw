# 평가 결과 extract-low-dev10

## 실행 조건

| 항목 | 값 |
|---|---|
| run_id | extract-low-dev10 |
| date_utc | 2026-11-26 02:41 |
| git_head | 3a40633 |
| split | only 10 |
| cases_lock | 4efeb937d8427e8a |
| service_models | gpt-5-mini-2025-08-07, text-embedding-3-small |
| judge | openai/gpt-5-2025-08-07 |
| judge_version | 2 |
| prices_as_of | 2026-11-25 |
| concurrency | 5 |
| wall_min | 13.5 |
| warmup | ready |

## 지표

| 지표 | 값 |
|---|---|
| cases | 10 |
| conversation_cases | 10 |
| errors | 0 |
| M2_recall | 96.7 |
| M2_precision | 52.7 |
| M3_questions_mean | 11 |
| M3_questions_max | 17 |
| completion_rate | 100.0 |
| M12_reasked_total | 13 |
| M12_reasked_per_case | 1.3 |
| undetected_question_turns | 0 |
| M4_keyword_accuracy | 90.0 |
| M6_primary_label_match | 30.0 |
| rag_failed | 0 |
| M5_unsupported_mishandled | None |
| M1_judge_fabricated_total | 49 |
| M1_cases_with_fabrication | 10 |
| M1_rule_numeric_total | 6 |
| M8_judge_assertions | 0 |
| M8_regex_assertions | 0 |
| judged_cases | 10 |
| reply_shows_None | 0 |
| M9_pii_in_requests | 162 |
| M9_by_kind | {'extract': 142, 'compose': 10, 'rag_keyword': 5, 'embedding': 5} |
| llm_calls | 170 |
| llm_calls_unattributed | 29 |
| extract_reasoning_effort | ['low'] |
| M11_service_cost_usd | 0.5032 |
| M11_turn_latency_p50_s | 16.4 |
| M11_turn_latency_p95_s | 20.2 |
| judge_cost_usd | 0.5176 |
| judge_failed | 0 |
| models_missing_price | [] |

## 호출 종류별 (M11)

| 종류 | 호출 | p50 초 | p95 초 | 출력 토큰 | 추론 토큰 | 비용 USD |
|---|---|---|---|---|---|---|
| compose | 10 | 26.6 | 29.3 | 26094 | 21056 | 0.0597 |
| embedding | 10 | 0.5 | 0.9 | 0 | 0 | 0.0 |
| extract | 121 | 16.5 | 20.2 | 187873 | 73856 | 0.3972 |
| rag_keyword | 10 | 2.7 | 7.5 | 1903 | 1792 | 0.006 |
| rag_summary | 19 | 9.6 | 14.6 | 17549 | 12608 | 0.0403 |

## 해석 (2026-11-26 KST)

정보 추출 호출의 추론 강도를 `low`로 낮춰 부분 세트 dev10(`eval/subsets/dev10.txt`, 10건)을 1회 실행했다. 비교 대상은 baseline-1의 같은 10건이다 (추론 강도 미지정 = 모델 기본값). baseline-1의 M1은 같은 초안을 판정 기준 2판으로 다시 판정한 값(`baseline-1-judge-v2`)을 썼다. 바뀐 것은 추론 강도 하나다.

| 지표 | baseline-1 (같은 10건) | low | 변화 |
|---|---|---|---|
| 한 턴 응답 중앙값 (M11) | 38.0초 | 16.4초 | -57% |
| 한 턴 응답 p95 | 49.7초 | 20.2초 | -59% |
| 정보 추출 호출 비용 | 0.894달러 (125회) | 0.397달러 (121회) | -56% |
| 정보 추출 추론 토큰 | 318,592 | 73,856 | -77% |
| 추출 재현율 / 정밀도 (M2) | 90.0% / 51.9% | 96.7% / 52.7% | 나빠지지 않음 |
| 질문 수 평균 (M3) | 11.4 | 11.0 | 비슷 |
| 재질문 (M12) | 사례당 1.3 | 사례당 1.3 | 같음 |
| 지어낸 사실 (M1, 판정 2판) | 46개 | 49개 | 비슷 |
| 완료율 / 오류 | 100% / 0 | 100% / 0 | 같음 |
| 판례 키워드 정확도 (M4) | 90.0% | 90.0% | 같음 |
| 판례 주된 죄명 일치 (M6) | 30.0% | 30.0% | 같음 |

판단:

- 응답 시간과 정보 추출 비용이 절반 아래로 줄었다. 줄어든 것은 대부분 추론 토큰이다.
- 추출 품질(M2), 질문 수, 재질문, 지어낸 사실은 나빠진 근거가 없다. 다만 좋아졌다고도 말할 수 없다. 10건 1회이고, 같은 조건을 다시 돌렸을 때의 흔들림을 아직 재지 않았다. 사례별 지어낸 사실 수는 한쪽으로 쏠리지 않고 -3에서 +4 사이로 움직였다.
- 정밀도 51.9% → 52.7%는 그대로라고 본다. 정밀도 문제는 추론 강도가 아니라 추출 입력과 프롬프트에서 온다.
- 판례 검색(M4, M6)은 정보 추출과 다른 호출이라 추론 강도의 영향을 받지 않고, 값도 같았다.
- 서비스 기본값을 `low`로 바꾼다. `minimal`은 재지 않았다.

한계: 부분 세트 10건, 1회 실행. 서비스 전체 비용은 이번 실행에서 0.503달러(정보 추출 0.397 + 초안 작성·판례 요약 등)였고, baseline-1의 같은 10건은 초안 작성 호출을 사례별로 나누지 못해 정보 추출 호출만 비교했다.
