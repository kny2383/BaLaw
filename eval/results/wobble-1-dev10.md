# 평가 결과 wobble-1-dev10

## 실행 조건

| 항목 | 값 |
|---|---|
| run_id | wobble-1-dev10 |
| date_utc | 2026-11-27 13:42 |
| git_head | 5644050 |
| split | only 10 |
| cases_lock | 4efeb937d8427e8a |
| service_models | gpt-6.1-terra, text-embedding-3-small |
| judge | openai/gpt-6.1-sol |
| judge_version | 3 |
| prices_as_of | 2026-11-27 |
| compose | 함 |
| stray_every | 0 |
| concurrency | 5 |
| wall_min | 7.3 |
| warmup | ready |

## 지표

| 지표 | 값 |
|---|---|
| cases | 10 |
| conversation_cases | 10 |
| errors | 0 |
| M2_recall | 93.3 |
| M2_precision | 58.3 |
| M3_breakdown_cases | 10 |
| M3_needed_asked | 62 |
| M3_needed_skipped | 23 |
| M3_unneeded_asked | 4 |
| M3_other_asked | 42 |
| M3_recovered_asked | 0 |
| M3_reasked | 9 |
| M3_questions_mean | 11.7 |
| M3_questions_max | 18 |
| completion_rate | 100.0 |
| M12_reasked_total | 9 |
| M12_reasked_per_case | 0.9 |
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
| M1_rule_numeric_total | 3 |
| M8_judge_assertions | 0 |
| M8_regex_assertions | 0 |
| judged_cases | 10 |
| reply_shows_None | 0 |
| M9_pii_in_requests | 0 |
| M9_by_kind | {} |
| llm_calls | 183 |
| llm_calls_unattributed | 40 |
| extract_reasoning_effort | ['low'] |
| verification_status | {'confirmed': 2, 'passed': 8} |
| verification_removed_total | 0 |
| confirm_cases | 2 |
| M1_basis_includes_confirmation | True |
| confirm_asked_total | 4 |
| confirm_yes_total | 4 |
| confirm_user_cost_usd | 0.0026 |
| M11_service_cost_usd | 0.8179 |
| M11_turn_latency_p50_s | 11.9 |
| M11_turn_latency_p95_s | 13.7 |
| judge_cost_usd | 0.0474 |
| judge_failed | 0 |
| models_missing_price | [] |

## 호출 종류별 (M11)

| 종류 | 모델 | 호출 | p50 초 | p95 초 | 출력 토큰 | 추론 토큰 | 비용 USD |
|---|---|---|---|---|---|---|---|
| compose | gpt-6.1-terra | 10 | 8.9 | 12.3 | 4367 | 1876 | 0.0656 |
| embedding | text-embedding-3-small | 10 | 0.3 | 0.5 | 0 | 0 | 0.0 |
| extract | gpt-6.1-terra | 127 | 11.9 | 13.7 | 100499 | 7062 | 0.6956 |
| rag_keyword | gpt-6.1-terra | 10 | 1.5 | 3.0 | 71 | 15 | 0.0018 |
| rag_summary | gpt-6.1-terra | 16 | 4.9 | 7.6 | 3380 | 732 | 0.0253 |
| verify | gpt-6.1-terra | 10 | 3.5 | 13.7 | 2106 | 1773 | 0.0296 |
