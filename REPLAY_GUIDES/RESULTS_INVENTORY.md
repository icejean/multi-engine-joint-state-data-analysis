# RESULTS_INVENTORY.md — Result-file completeness inventory

> Each experiment's `results_*.json` is classified into **conclusion-critical / process-record**.
> **Conclusion-critical** = the paper's numbers come directly from these files (reproducers check conclusions against only this tier); **process-record** = intermediate states of the exploration (the per-round evidence chain of run → root cause → fix notes/gold → re-run), kept for trace-back, not part of the conclusions.
> Exact numbers are always authoritative in `analysis/p2-statistical-results.md` and the corresponding result files; this inventory states only tier and provenance, not numbers.

---

## works_cycles (BIRD AdventureWorks, 126 questions)

| Tier | File | Note / paper location |
|---|---|---|
| **Conclusion-critical** | `results_wc_mplus_126_pass{1,2,3}.json` | M+S M0 pass^3 (average / all-3), §4.3 |
| **Conclusion-critical** | `results_wc_mplus_126_pass4.json` | pass4 ceiling closure, §4.4 |
| **Conclusion-critical** | `results_wc_s_full{,_pass1,_pass2,_pass3,_v2}.json` | S axis (S0/S1/S2), §4.2 |
| **Conclusion-critical** | `results_wc_m_126_full{,_pass1,_pass2,_pass3,_v2}.json` | M axis (M0/M1/M2), §4.2/§4.3 |
| **Conclusion-critical** | `results_wc_mplus_126_glm52{,_pass1,_pass2,_pass3}.json` | glm-5.2 cross-model, §4.5 |
| **Conclusion-critical** | `results_wc_mplus_glm5pro_126{,_r2,_r3}.json` | glm-5.1/GLM-5-Pro cross-model, §4.5 |
| **Conclusion-critical** | `results_wc_s0_drift_r{1,2,3}.json`, `results_wc_s0_stab_r{1..5}.json` | S0 drift/stability experiment, §4.3/§7.1 |
| Process-record | `results_wc_m_26*.json`, `results_wc_s_26*.json` | 26-question subset (pilot stage) |
| Process-record | `results_wc_pilot.json`, `results_wc_pilot_clean.json` | pilot |
| Process-record | `results_wc_m_tier1_verify.json`, `results_wc_m_fix2_verify.json`, `results_wc_verify.json` | targeted verification |
| Process-record | `results_wc_m_q90q101_test.json`, `results_wc_m_q93q94_test.json`, `results_wc_q99m2_confirm.json`, `results_wc_q1q99_v2.json`, `results_wc_s_q21.json`, `results_wc_s_q60.json` | single-question / subset retries |
| Process-record | `results_wc_mplus_smoke*.json`, `results_wc_mplus_rerun_29_71.json`, `results_wc_mplus_ds_regression_check.json`, `results_wc_mplus_glm52_fix4.json`, `results_wc_m2_retry.json`, `results_wc_fix3.json`, `results_wc_cost_validate.json`, `results_wc_s_validate.json`, `results_wc_s_glm52_s2*.json`, `results_wc_s_glm5pro_s2_smoke.json`, `results_wc_s_glm5pro_s12_full.json` | smoke / fixes / cost validation / cross-model subsets |

---

## financial (BIRD dev, 106 questions)

| Tier | File | Note / paper location |
|---|---|---|
| **Conclusion-critical** | `results_fin_pass3_run{1,2,3}.json` | pass^3 (average / all-3), §4.4 |
| **Conclusion-critical** | `results_fin_passk{1,2,3}.json` | pass@k summary, §4.4 |
| **Conclusion-critical** | `results_fin_ss_s1.json`, `results_fin_ss_s1n.json` | B1 single-shot same-DB baseline (s1 / s1n), §4.4/§B1 |
| **Conclusion-critical** | `results_fin_round{1,2,3,4}.json` | convergence rounds (round1 from scratch → convergence), §4.4 |
| Process-record | `results_fin_notes{,_run1,_run2,_run3}.json` … `results_fin_notes4_run{1,2,3}.json` | 4 notes versions × 3 rounds each (notes incremental accumulation) |
| Process-record | `results_fin_note2test.json`, `results_fin_note11.json` | notes incremental validation |
| Process-record | `results_fin_fix2/3_run{1,2,3}.json`, `results_fin_evfix{,2}_run{1,2,3}.json`, `results_fin_goldfix.json`, `results_fin_promptfix.json`, `results_fin_new6_run{1,2,3}.json` | targeted fixes |
| Process-record | `results_fin_temp0_run{1,2,3}.json`, `results_fin_temp0_smoke.json` | temperature=0 stability control |
| Process-record | `results_fin_hard_run{1,2,3}.json` | hard-floor analysis |
| Process-record | `results_fin_glm52_*.json` | glm-5.2 cross-model |
| Process-record | `results_fin_q13q61.json`, `q13q83`, `q37_run{1,2,3}`, `q59q81`, `q61q101_run{1,2,3}`, `q81`, `q92`, `pro14` | single-question retries |
| Process-record | `results_fin_full106{,_v2,_v3}.json`, `results_fin_final_run{1,2,3}.json` | full 106 / final round |

---

## formula_1 (BIRD dev, 174 questions)

| Tier | File | Note / paper location |
|---|---|---|
| **Conclusion-critical** | `results_f1_pass3_run{1,2,3}.json` | pass^3, §4.4 |
| **Conclusion-critical** | `results_f1_ss_s1.json`, `results_f1_ss_s1n.json` | B1 single-shot same-DB baseline, §4.4/§B1 |
| **Conclusion-critical** | `results_f1_round{1,2,3,4,5}.json` | convergence rounds, §4.4 |
| **Conclusion-critical** | `results_f1_final_run{1,2,3}.json` | final round, §4.4 |
| Process-record | `results_f1_note1test.json`, `note2test`, `note3test` | notes incremental validation |
| Process-record | `results_f1_notesfix_run1.json`, `goldfix`, `driftfix`, `stablefix`, `regfix`, `q128fix` | targeted fixes |
| Process-record | `results_f1_smoke.json`, `smoke2`, `smoke_dsh`, `round5b` | smoke / round5b |

---

## movie (CypherBench movie, 401 questions)

| Tier | File | Note / paper location |
|---|---|---|
| **Conclusion-critical** | `results_movie_final.json`, `results_movie_final2.json` | final (96.5% EX), §5.1 |
| **Conclusion-critical** | `results_movie_mplus.json`, `mplus_r2`, `mplus_r3`, `r4`, `r4b` | convergence rounds (85.8%→95.0%→96.5%), §5.1 |
| **Conclusion-critical** | `results_movie_pass2.json`, `pass3.json` + `pass3_summary.md` | pass^3 (all-3 94.0%), §5.1 |
| **Conclusion-critical** | `convergence.json` | convergence-curve summary, §5.1 |
| Process-record | `results_movie_q2q52.json` | subset validation |

---

## sakila (anti-memorization / metadata gradient, 25 questions)

| Tier | File | Note / paper location |
|---|---|---|
| **Conclusion-critical** | `results_glm52.json` | M axis glm-5.2 final, §4.1 |
| **Conclusion-critical** | `results_singleshot_{glm52,flash,pro}.json` | S axis three models, §4.1 |
| **Conclusion-critical** | `results_dsh_{flash,glm52,pro}_full.json` | M axis DSH three-backend control, §4.1 |

---

## tabred (TabReD weather, ML)

| Tier | File | Note / paper location |
|---|---|---|
| **Conclusion-critical** | `chat-*.html` (5 files) | desensitized records of the conversation-driven full pipeline (source of the Python LightGBM / R rtorch / R GBDT RMSE numbers), §5.2/§5.3 |

> Note: tabred has no SQL-style "questions/gold/scoring" framework; the 5 chat records are the conclusion evidence (desensitized, keys [REDACTED]); the raw `weather.parquet` is downloaded from TabReD.
