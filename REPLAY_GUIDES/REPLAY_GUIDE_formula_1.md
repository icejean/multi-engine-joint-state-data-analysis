# REPLAY_GUIDE_formula_1.md — formula_1（BIRD dev）复现指南

> 从零复现论文 §4.4 的 **formula_1**（BIRD dev F1 赛车库，混淆改名）SQL 收敛实验。
> 与 `financial` 共用同一套 `prep_bird.py` 管线（见 REPLAY_GUIDE_financial.md），本文只标差异。
> 资产：`data/formula_1/`、`scripts/`、`analysis/root-cause/`。

---

## 0. 定位与口径（先读）

- **数据域**：关系型（SQL），BIRD dev 的 `formula_1` 库（F1 赛车，13 表）。
- **机制**：**M+S**（一次性注入 schema.json + notes.md）+ 对照 single-shot 基线（B1）。
- **收敛曲线**：同一库多轮跑，每轮换一份 notes.md（从零逐步积累）。
- **诚实边界**：M+S 走 Portal 真实执行链路，需部署 DataAI Portal 全栈才能复跑——
  开源 DataAI 项目见 <https://github.com/icejean/dataai_with_jupyterlab_and_rstudio>（`docs/DataAI-Portal-AI数据分析平台简介.md` 是 Portal 介绍资料入口）。
  single-shot 直连 LLM API + pymysql，第三方可复现。
- **判分**：`results_equal_relaxed`。

---

## 1. 数据源与下载

- **源**：BIRD dev 集，数据库 `formula_1`。<https://bird-bench.github.io> 下载 dev 集，得到 `dev.json`、`dev_databases/formula_1/formula_1.sqlite`、`database_description/*.csv`（13 表）。
- **本仓库已含**：`question_set.json` / `question_set_obfuscated.json`、`obfuscation_map.json`、`formula_1_schema.json`、`formula_1_notes.md`、`gold.json`、`gold_errors.json`、`database_description/*.csv`、`convergence_curve.json`、`results_f1_*.json`、`b1_*.log`。
- **本仓库不含**：`formula_1.sqlite`（二进制库，需下载）。

---

## 2. 预处理（混淆改名）

```bash
python3 scripts/prep_bird.py formula_1
#   → data/formula_1/{question_set.json, obfuscation_map.json, formula_1_schema.json}

python3 scripts/transform_gold_sql.py --questions data/formula_1/question_set.json \
    --map data/formula_1/obfuscation_map.json --out data/formula_1/question_set_obfuscated.json
```

---

## 3. 建库与加载

```bash
python3 scripts/migrate_bird.py formula_1
```

---

## 4. 题集（174 题）

- **单一事实源**：`data/formula_1/question_set_obfuscated.json`（174 题）。

---

## 5. gold 源 / 生成 / fix

```bash
python3 scripts/gen_gold_bird.py formula_1
```

- 输出：`data/formula_1/gold.json` + `gold_errors.json`（交叉验证「原名 SQLite vs 混淆 MySQL」）。

---

## 6. 资源文件（M+S 一次性注入）

- `data/formula_1/formula_1_schema.json` + `formula_1_notes.md`。

---

## 7. 跑 benchmark

```bash
# M+S 收敛曲线
python3 scripts/run_bench_bird_mplus.py --db formula_1 --all \
    --results results_f1_round1.json

# single-shot 基线（B1）
python3 scripts/run_bench_bird_singleshot.py --db formula_1 --all \
    --results results_f1_ss.json

# 收敛汇总
python3 scripts/summarize_convergence.py --db formula_1 \
    --results results_f1_round1.json --round 1 --notes "empty(从零)"
```

---

## 8. 判分

```bash
python3 scripts/score.py --selftest
python3 scripts/statistical_analysis.py      # p2-statistical-results.md §B1
```

---

## 9. 根因分析（文档索引）

| 主题 | 文档 |
|---|---|
| BIRD dev 跨库收敛 | `analysis/root-cause/bird-dev-convergence.md` |
| 跨模型对照 | `analysis/root-cause/glm52-7q-root-cause.md`、`bird-dev-pro-vs-flash.md` |
| gold 审计 | `analysis/root-cause/gold-fixes-bird-dev.md` + `analysis/gold-verification.md` |
| 统计方法 | `analysis/p2-statistical-results.md`（§B1） |

---

## 10. 迭代时间线（收敛过程，非逐轮数字）

与 financial 同构：prep → 建库 → round1 从零 → 根因/修 notes/重跑 → B1 同库基线 → 收口（收敛到 grounding 拉满、锁定硬地板）。formula_1 的库专属 notes 涉及圈速 `TIME_TO_SEC` 等 F1 语义坑。

> 精确数字以 `analysis/p2-statistical-results.md` §B1 与 `convergence_curve.json` 为准。

---

## 11. 相关文件清单

**数据（`data/formula_1/`）**：`question_set.json`、`question_set_obfuscated.json`、`obfuscation_map.json`、`formula_1_schema.json`、`formula_1_notes.md`、`gold.json`、`gold_errors.json`、`database_description/*.csv`（13 表）、`convergence_curve.json`、`results_f1_*.json`、`b1_*.log`。

**脚本**：同 financial（`scripts/{prep_bird,transform_gold_sql,migrate_bird,gen_gold_bird,run_bench_bird_mplus,run_bench_bird_singleshot,summarize_convergence,analyze_b1_singleshot}.py` + `run_b1_singleshot.sh`）。
