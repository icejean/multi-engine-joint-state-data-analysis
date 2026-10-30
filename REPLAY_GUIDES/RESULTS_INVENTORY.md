# RESULTS_INVENTORY.md — 结果文件完整性清单

> 每个实验库的 `results_*.json` 按 **结论依赖 / 过程留档** 分级。
> **结论依赖** = 论文正文数字直接出自这些文件（复现者核对结论只看这一档）；**过程留档** = 探索过程的中间态（run → 根因 → 修 notes/gold → 重跑的逐轮证据链），留作可回溯、不参与结论。
> 精确数字一律以 `analysis/p2-statistical-results.md` 与对应结果文件为准，本清单不重述数字、只标层级与出处。

---

## works_cycles（BIRD AdventureWorks，126 题）

| 分级 | 文件 | 说明 / 论文出处 |
|---|---|---|
| **结论依赖** | `results_wc_mplus_126_pass{1,2,3}.json` | M+S M0 pass^3（平均 / 三轮全对），§4.3 |
| **结论依赖** | `results_wc_mplus_126_pass4.json` | pass4 天花板收口，§4.4 |
| **结论依赖** | `results_wc_s_full{,_pass1,_pass2,_pass3,_v2}.json` | S 轴（S0/S1/S2），§4.2 |
| **结论依赖** | `results_wc_m_126_full{,_pass1,_pass2,_pass3,_v2}.json` | M 轴（M0/M1/M2），§4.2/§4.3 |
| **结论依赖** | `results_wc_mplus_126_glm52{,_pass1,_pass2,_pass3}.json` | glm-5.2 跨模型，§4.5 |
| **结论依赖** | `results_wc_mplus_glm5pro_126{,_r2,_r3}.json` | glm-5.1/GLM-5-Pro 跨模型，§4.5 |
| **结论依赖** | `results_wc_s0_drift_r{1,2,3}.json`、`results_wc_s0_stab_r{1..5}.json` | S0 漂移/稳定实验，§4.3/§7.1 |
| 过程留档 | `results_wc_m_26*.json`、`results_wc_s_26*.json` | 26 题子集（pilot 阶段） |
| 过程留档 | `results_wc_pilot.json`、`results_wc_pilot_clean.json` | 试点 |
| 过程留档 | `results_wc_m_tier1_verify.json`、`results_wc_m_fix2_verify.json`、`results_wc_verify.json` | 定向验证 |
| 过程留档 | `results_wc_m_q90q101_test.json`、`results_wc_m_q93q94_test.json`、`results_wc_q99m2_confirm.json`、`results_wc_q1q99_v2.json`、`results_wc_s_q21.json`、`results_wc_s_q60.json` | 单题/子集重试 |
| 过程留档 | `results_wc_mplus_smoke*.json`、`results_wc_mplus_rerun_29_71.json`、`results_wc_mplus_ds_regression_check.json`、`results_wc_mplus_glm52_fix4.json`、`results_wc_m2_retry.json`、`results_wc_fix3.json`、`results_wc_cost_validate.json`、`results_wc_s_validate.json`、`results_wc_s_glm52_s2*.json`、`results_wc_s_glm5pro_s2_smoke.json`、`results_wc_s_glm5pro_s12_full.json` | 冒烟 / 修复 / 成本验证 / 跨模型子集 |

---

## financial（BIRD dev，106 题）

| 分级 | 文件 | 说明 / 论文出处 |
|---|---|---|
| **结论依赖** | `results_fin_pass3_run{1,2,3}.json` | pass^3（平均 / 三轮全对），§4.4 |
| **结论依赖** | `results_fin_passk{1,2,3}.json` | pass@k 汇总，§4.4 |
| **结论依赖** | `results_fin_ss_s1.json`、`results_fin_ss_s1n.json` | B1 single-shot 同库基线（s1 / s1n），§4.4/§B1 |
| **结论依赖** | `results_fin_round{1,2,3,4}.json` | 收敛轮（round1 从零 → 收敛），§4.4 |
| 过程留档 | `results_fin_notes{,_run1,_run2,_run3}.json` … `results_fin_notes4_run{1,2,3}.json` | 4 版 notes 各 ×3 轮（note 增量积累） |
| 过程留档 | `results_fin_note2test.json`、`results_fin_note11.json` | note 增量验证 |
| 过程留档 | `results_fin_fix2/3_run{1,2,3}.json`、`results_fin_evfix{,2}_run{1,2,3}.json`、`results_fin_goldfix.json`、`results_fin_promptfix.json`、`results_fin_new6_run{1,2,3}.json` | 定向修复 |
| 过程留档 | `results_fin_temp0_run{1,2,3}.json`、`results_fin_temp0_smoke.json` | temperature=0 稳定对照 |
| 过程留档 | `results_fin_hard_run{1,2,3}.json` | 硬地板分析 |
| 过程留档 | `results_fin_glm52_*.json` | glm-5.2 跨模型 |
| 过程留档 | `results_fin_q13q61.json`、`q13q83`、`q37_run{1,2,3}`、`q59q81`、`q61q101_run{1,2,3}`、`q81`、`q92`、`pro14` | 单题重试 |
| 过程留档 | `results_fin_full106{,_v2,_v3}.json`、`results_fin_final_run{1,2,3}.json` | 全量 106 / 最终轮 |

---

## formula_1（BIRD dev，174 题）

| 分级 | 文件 | 说明 / 论文出处 |
|---|---|---|
| **结论依赖** | `results_f1_pass3_run{1,2,3}.json` | pass^3，§4.4 |
| **结论依赖** | `results_f1_ss_s1.json`、`results_f1_ss_s1n.json` | B1 single-shot 同库基线，§4.4/§B1 |
| **结论依赖** | `results_f1_round{1,2,3,4,5}.json` | 收敛轮，§4.4 |
| **结论依赖** | `results_f1_final_run{1,2,3}.json` | 最终轮，§4.4 |
| 过程留档 | `results_f1_note1test.json`、`note2test`、`note3test` | note 增量验证 |
| 过程留档 | `results_f1_notesfix_run1.json`、`goldfix`、`driftfix`、`stablefix`、`regfix`、`q128fix` | 定向修复 |
| 过程留档 | `results_f1_smoke.json`、`smoke2`、`smoke_dsh`、`round5b` | 冒烟 / round5b |

---

## movie（CypherBench movie，401 题）

| 分级 | 文件 | 说明 / 论文出处 |
|---|---|---|
| **结论依赖** | `results_movie_final.json`、`results_movie_final2.json` | 定稿（96.5% EX），§5.1 |
| **结论依赖** | `results_movie_mplus.json`、`mplus_r2`、`mplus_r3`、`r4`、`r4b` | 收敛轮（85.8%→95.0%→96.5%），§5.1 |
| **结论依赖** | `results_movie_pass2.json`、`pass3.json` + `pass3_summary.md` | pass^3（三轮全对 94.0%），§5.1 |
| **结论依赖** | `convergence.json` | 收敛曲线汇总，§5.1 |
| 过程留档 | `results_movie_q2q52.json` | 子集验证 |

---

## sakila（反记忆 / 元数据梯度，25 题）

| 分级 | 文件 | 说明 / 论文出处 |
|---|---|---|
| **结论依赖** | `results_glm52.json` | M 系列 glm-5.2 定稿，§4.1 |
| **结论依赖** | `results_singleshot_{glm52,flash,pro}.json` | S 系列三模型，§4.1 |
| **结论依赖** | `results_dsh_{flash,glm52,pro}_full.json` | M 系列 DSH 三后端对照，§4.1 |

---

## tabred（TabReD weather，ML）

| 分级 | 文件 | 说明 / 论文出处 |
|---|---|---|
| **结论依赖** | `chat-*.html`（5 个） | 对话驱动全流程脱敏记录（Python LightGBM / R rtorch / R GBDT 的 RMSE 出处），§5.2/§5.3 |

> 注：tabred 无 SQL 式「题/gold/判分」体系，5 个 chat 记录即结论证据（脱敏版，密钥已 [REDACTED]）；原始 `weather.parquet` 从 TabReD 下载。
