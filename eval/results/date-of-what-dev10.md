# 평가 결과 date-of-what-dev10

## 실행 조건

| 항목 | 값 |
|---|---|
| run_id | date-of-what-dev10 |
| date_utc | 2026-11-27 13:28 |
| git_head | 7161894 |
| split | only 10 |
| cases_lock | 4efeb937d8427e8a |
| service_models | gpt-6.1-terra, text-embedding-3-small |
| judge | openai/gpt-6.1-sol |
| judge_version | 3 |
| prices_as_of | 2026-11-27 |
| compose | 함 |
| stray_every | 0 |
| concurrency | 5 |
| wall_min | 7.2 |
| warmup | ready |

## 지표

| 지표 | 값 |
|---|---|
| cases | 10 |
| conversation_cases | 10 |
| errors | 0 |
| M2_recall | 86.7 |
| M2_precision | 56.5 |
| M3_breakdown_cases | 10 |
| M3_needed_asked | 60 |
| M3_needed_skipped | 25 |
| M3_unneeded_asked | 4 |
| M3_other_asked | 41 |
| M3_recovered_asked | 0 |
| M3_reasked | 8 |
| M3_questions_mean | 11.3 |
| M3_questions_max | 18 |
| completion_rate | 100.0 |
| M12_reasked_total | 8 |
| M12_reasked_per_case | 0.8 |
| M12_stray_given | 0 |
| M12_stray_recovered | 0 |
| M12_stray_lost | 0 |
| undetected_question_turns | 0 |
| M4_keyword_accuracy | 100.0 |
| M4_cases | 10 |
| M6_primary_label_match | 80.0 |
| rag_failed | 0 |
| M5_unsupported_mishandled | None |
| M1_judge_fabricated_total | 0 |
| M1_cases_with_fabrication | 0 |
| M1_rule_numeric_total | 4 |
| M8_judge_assertions | 0 |
| M8_regex_assertions | 0 |
| judged_cases | 10 |
| reply_shows_None | 0 |
| M9_pii_in_requests | 0 |
| M9_by_kind | {} |
| llm_calls | 178 |
| llm_calls_unattributed | 41 |
| extract_reasoning_effort | ['low'] |
| verification_status | {'confirmed': 2, 'passed': 7, 'rewritten': 1} |
| verification_removed_total | 1 |
| confirm_cases | 3 |
| M1_basis_includes_confirmation | True |
| confirm_asked_total | 5 |
| confirm_yes_total | 4 |
| confirm_user_cost_usd | 0.0066 |
| M11_service_cost_usd | 0.8274 |
| M11_turn_latency_p50_s | 12.6 |
| M11_turn_latency_p95_s | 15.1 |
| judge_cost_usd | 0.0463 |
| judge_failed | 0 |
| models_missing_price | [] |

## 호출 종류별 (M11)

| 종류 | 모델 | 호출 | p50 초 | p95 초 | 출력 토큰 | 추론 토큰 | 비용 USD |
|---|---|---|---|---|---|---|---|
| compose | gpt-6.1-terra | 10 | 9.6 | 15.8 | 4431 | 2021 | 0.0658 |
| embedding | text-embedding-3-small | 10 | 0.3 | 0.7 | 0 | 0 | 0.0 |
| extract | gpt-6.1-terra | 123 | 12.6 | 15.0 | 96547 | 7293 | 0.6705 |
| rag_keyword | gpt-6.1-terra | 10 | 1.6 | 1.9 | 75 | 19 | 0.0281 |
| rag_summary | gpt-6.1-terra | 14 | 5.4 | 9.0 | 2957 | 728 | 0.0284 |
| rewrite | gpt-6.1-terra | 1 | 4.4 | 4.4 | 284 | 0 | 0.0021 |
| verify | gpt-6.1-terra | 10 | 3.3 | 20.7 | 2767 | 2338 | 0.0325 |
