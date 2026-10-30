# REPLAY_GUIDE_financial.md — financial（BIRD dev）复现指南

> 从零复现论文 §4.4 的 **financial**（BIRD dev 捷克银行库，混淆改名）SQL 收敛实验。
> 与 `formula_1` 共用同一套 `prep_bird.py` 管线（见 REPLAY_GUIDE_formula_1.md）。
> 资产：`data/financial/`、`scripts/`、`analysis/root-cause/`。

---

## 0. 定位与口径（先读）

- **数据域**：关系型（SQL），BIRD dev 的 `financial` 库（捷克银行，8 表）。
- **机制**：**M+S**（一次性注入 `schema.json` + `notes.md`，Agent 多轮执行反馈）；对照 **single-shot** 基线（B1 实验）。
- **收敛曲线**：同一库多轮跑，每轮换一份 notes.md（从零逐步积累），量化「notes 累积 → 准确率单调收敛」。
- **诚实边界**：M+S 走 Portal 真实执行链路（openclaw → MCP → dataai-sql kernel），需部署 DataAI Portal 全栈才能复跑——
  开源 DataAI 项目见 <https://github.com/icejean/dataai_with_jupyterlab_and_rstudio>（`docs/DataAI-Portal-AI数据分析平台简介.md` 是 Portal 介绍资料入口）。
  single-shot 直连 LLM API + pymysql 判分，第三方可复现。
- **判分**：`results_equal_relaxed`（值多重集比对，放宽多输出列）。

---

## 1. 数据源与下载

- **源**：BIRD dev 集，数据库 `financial`。<https://bird-bench.github.io> 下载 dev 集，得到：
  - `dev.json`（题库）、`dev_databases/financial/financial.sqlite`（数据库）、`dev_databases/financial/database_description/*.csv`（8 表英文列描述）。
- **本仓库已含**：`question_set.json` / `question_set_obfuscated.json`、`obfuscation_map.json`、`financial_schema.json`、`financial_notes.md`、`gold.json`、`gold_errors.json`、`database_description/*.csv`、`convergence_curve.json`、`results_fin_*.json`、`b1_*.log`。
- **本仓库不含**：`financial.sqlite`（二进制库，需下载）。

---

## 2. 预处理（混淆改名）

```bash
# 1) enrich + 混淆映射 + schema.json（读 dev.json + financial.sqlite + database_description/*.csv）
python3 scripts/prep_bird.py financial
#   → data/financial/{question_set.json, obfuscation_map.json, financial_schema.json}

# 2) gold SQL 改写（原名 SQLite 方言 → 混淆名 MySQL 方言）
python3 scripts/transform_gold_sql.py --questions data/financial/question_set.json \
    --map data/financial/obfuscation_map.json --out data/financial/question_set_obfuscated.json
```

> 混淆规则：表名缩写 + 非 FK 列去元音截 4 + FK 列 → `ref1/ref2`（与 works_cycles 同规则）。

---

## 3. 建库与加载

```bash
# SQLite → MySQL（混淆名，单库，无 sys_* 元数据表——schema 走注入的 schema.json）
python3 scripts/migrate_bird.py financial
```

- 凭据：repo 根 `.env`（缺省回退 `/opt/dataai/templates/.env`）。

---

## 4. 题集（106 题）

- **单一事实源**：`data/financial/question_set_obfuscated.json`（106 题，含 `id/question_id/question/evidence/SQL_obfuscated`）。

---

## 5. gold 源 / 生成 / fix

```bash
# 执行混淆 SQL → gold.json，并交叉验证「原名 SQLite vs 混淆 MySQL」结果一致
python3 scripts/gen_gold_bird.py financial
```

- 输出：`data/financial/gold.json` + `data/financial/gold_errors.json`（剔除：原 SQL 执行失败 / 退化 gold / 交叉验证不一致）。
- **gold fix**：见 `analysis/root-cause/gold-fixes-bird-dev.md`、`analysis/gold-verification.md`。

---

## 6. 资源文件（M+S 一次性注入）

- `data/financial/financial_schema.json`（prep_bird.py 产出，混淆名 + 英文描述 + 外键）。
- `data/financial/financial_notes.md`（迭代积累的注意事项，见 §10 收敛）。

---

## 7. 跑 benchmark

```bash
# M+S 收敛曲线（每轮换一份 notes.md）
python3 scripts/run_bench_bird_mplus.py --db financial --all \
    --results results_fin_round1.json       # 第 1 轮（从零 notes）
# ...逐轮积累 notes 后重跑 round2/round3...

# single-shot 基线（B1，同库对照；--with-notes 可选）
python3 scripts/run_bench_bird_singleshot.py --db financial --all \
    --results results_fin_ss.json
python3 scripts/run_bench_bird_singleshot.py --db financial --all --with-notes \
    --results results_fin_ss_notes.json

# pass^3（同一份收敛后 notes × 3 轮，量化模型漂移；统计 平均 pass@1 / 三轮全对 all-3）
python3 scripts/run_bench_bird_mplus.py --db financial --all --results results_fin_pass3_run1.json
python3 scripts/run_bench_bird_mplus.py --db financial --all --results results_fin_pass3_run2.json
python3 scripts/run_bench_bird_mplus.py --db financial --all --results results_fin_pass3_run3.json

# 收敛汇总（每轮一进 convergence_curve.json）
python3 scripts/summarize_convergence.py --db financial \
    --results results_fin_round1.json --round 1 --notes "empty(从零)"
```

- **B1 同库基线**：`scripts/run_b1_singleshot.sh`（后台串行跑 s1/s1n，日志落 `data/financial/b1_*.log`）；分析用 `scripts/analyze_b1_singleshot.py`。
- **断点续跑**：结果逐条落盘，已跑的题自动跳过。

---

## 8. 判分

```bash
python3 scripts/score.py --selftest          # 自检
python3 scripts/statistical_analysis.py      # McNemar + bootstrap CI（p2-statistical-results.md §B1）
```

---

## 9. 根因分析（文档索引）

| 主题 | 文档 |
|---|---|
| BIRD dev 跨库收敛 | `analysis/root-cause/bird-dev-convergence.md` |
| 跨模型对照 | `analysis/root-cause/glm52-7q-root-cause.md`、`bird-dev-pro-vs-flash.md` |
| gold 审计 | `analysis/root-cause/gold-fixes-bird-dev.md` + `analysis/gold-verification.md` |
| 统计方法 | `analysis/p2-statistical-results.md`（§B1 同库 single-shot 基线） |

---

## 10. 迭代时间线（收敛过程，非逐轮数字）

1. **prep + 建库**：`prep_bird.py` 混淆 → `migrate_bird.py` 建 MySQL 库。
2. **round1（从零）**：只注入 schema.json、无 notes，跑 M+S 得下界。
3. **根因 → 修 notes → 重跑**：逐轮对失败题做根因分析，把「语义歧义」消成 notes 规则，再重跑——这是收敛曲线的主体。
4. **B1 同库基线**：跑 single-shot（s1 无 notes / s1n 带 notes），得到「M+S 领先 single-shot」的同库对照。
5. **pass^3**：同一份收敛后 notes × 3 轮，得到「平均 pass@1」与「三轮全对 all-3」两个口径（后者更严格）。
6. **收口**：准确率收敛到 grounding 拉满的最终值，漂移根因与硬地板题锁定。

> 精确数字以 `analysis/p2-statistical-results.md` §B1 与 `convergence_curve.json` 为准。

---

## 11. 相关文件清单

**数据（`data/financial/`）**：`question_set.json`、`question_set_obfuscated.json`、`obfuscation_map.json`、`financial_schema.json`、`financial_notes.md`、`gold.json`、`gold_errors.json`、`database_description/*.csv`（8 表）、`convergence_curve.json`、`results_fin_*.json`、`b1_*.log`。

**脚本**：`scripts/{prep_bird,transform_gold_sql,migrate_bird,gen_gold_bird,run_bench_bird_mplus,run_bench_bird_singleshot,summarize_convergence,analyze_b1_singleshot,score,statistical_analysis}.py` + `scripts/run_b1_singleshot.sh`。
