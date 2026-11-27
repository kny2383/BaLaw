# 평가 결과 holdout-final

## 실행 조건

| 항목 | 값 |
|---|---|
| run_id | holdout-final |
| date_utc | 2026-11-27 16:34 |
| git_head | 9e726e2 |
| split | holdout |
| cases_lock | 4efeb937d8427e8a |
| service_models | gpt-6.1-terra, text-embedding-3-small |
| judge | openai/gpt-6.1-sol |
| judge_version | 3 |
| prices_as_of | 2026-11-27 |
| compose | 함 |
| stray_every | 0 |
| concurrency | 5 |
| wall_min | 10.4 |
| warmup | ready |

## 지표

| 지표 | 값 |
|---|---|
| cases | 15 |
| conversation_cases | 13 |
| errors | 0 |
| M2_recall | 94.9 |
| M2_precision | 61.7 |
| M3_breakdown_cases | 13 |
| M3_needed_asked | 80 |
| M3_needed_skipped | 27 |
| M3_unneeded_asked | 4 |
| M3_other_asked | 60 |
| M3_recovered_asked | 0 |
| M3_reasked | 13 |
| M3_questions_mean | 12.08 |
| M3_questions_max | 20 |
| completion_rate | 100.0 |
| M12_reasked_total | 13 |
| M12_reasked_per_case | 1.0 |
| M12_stray_given | 0 |
| M12_stray_recovered | 0 |
| M12_stray_lost | 0 |
| undetected_question_turns | 0 |
| M4_keyword_accuracy | 100.0 |
| M4_cases | 13 |
| M6_primary_label_match | 88.0 |
| rag_failed | 0 |
| M5_unsupported_mishandled | 0.0 |
| M1_judge_fabricated_total | 0 |
| M1_cases_with_fabrication | 0 |
| M1_rule_numeric_total | 1 |
| M8_judge_assertions | 0 |
| M8_regex_assertions | 0 |
| judged_cases | 13 |
| reply_shows_None | 0 |
| M9_pii_in_requests | 0 |
| M9_by_kind | {} |
| llm_calls | 243 |
| llm_calls_unattributed | 64 |
| extract_reasoning_effort | ['low'] |
| verification_status | {'confirmed': 1, 'passed': 11, 'rewritten': 1} |
| verification_removed_total | 1 |
| confirm_cases | 1 |
| M1_basis_includes_confirmation | True |
| confirm_asked_total | 1 |
| confirm_yes_total | 1 |
| confirm_user_cost_usd | 0.0016 |
| M11_service_cost_usd | 1.1312 |
| M11_turn_latency_p50_s | 12.3 |
| M11_turn_latency_p95_s | 15.0 |
| judge_cost_usd | 0.0614 |
| judge_failed | 0 |
| models_missing_price | [] |

## 호출 종류별 (M11)

| 종류 | 모델 | 호출 | p50 초 | p95 초 | 출력 토큰 | 추론 토큰 | 비용 USD |
|---|---|---|---|---|---|---|---|
| compose | gpt-6.1-terra | 13 | 9.2 | 11.9 | 5925 | 2656 | 0.0863 |
| embedding | text-embedding-3-small | 13 | 0.2 | 0.7 | 0 | 0 | 0.0 |
| extract | gpt-6.1-terra | 170 | 12.2 | 14.9 | 133324 | 9357 | 0.927 |
| rag_keyword | gpt-6.1-terra | 13 | 1.7 | 2.9 | 187 | 88 | 0.0369 |
| rag_summary | gpt-6.1-terra | 20 | 4.8 | 7.5 | 4278 | 866 | 0.0412 |
| rewrite | gpt-6.1-terra | 1 | 5.2 | 5.2 | 316 | 0 | 0.0025 |
| verify | gpt-6.1-terra | 13 | 2.9 | 10.0 | 1788 | 1456 | 0.0373 |
