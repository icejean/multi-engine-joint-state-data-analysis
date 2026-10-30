# REPLAY_GUIDE_movie.md — movie（CypherBench 图库）复现指南

> 从零复现论文 §5.1 的 **movie**（CypherBench movie 子图，Neo4j）图查询实验：
> 数据获取 → Neo4j 导入 → schema/gold → 跑 M+S → 判分 → 收敛轨迹与根因。
> 资产：`data/movie/`、`scripts/`、`analysis/root-cause/`。

---

## 0. 定位与口径（先读）

- **数据域**：图（Cypher → Neo4j），CypherBench 的 movie 子图（401 题；459,393 节点 / 1,892,202 关系 / 7 标签 / 9 关系类型）。
- **机制**：**M+S**（一次性注入 `movie_schema.json` + `movie_notes.md`，Agent 多轮执行反馈生成裸 Cypher）；无 S/M 元数据梯度（单图单模式）。
- **诚实边界**：M+S 走 Portal 真实执行链路，需部署 DataAI Portal 全栈才能复跑——
  开源 DataAI 项目见 <https://github.com/icejean/dataai_with_jupyterlab_and_rstudio>（`docs/DataAI-Portal-AI数据分析平台简介.md` 是 Portal 介绍资料入口）。
- **判分**：`score_cypher.py` 的 `results_equal_relaxed`（值多重集比对，放宽多列，NULL/空串等价，数值 2 位容差）。

---

## 1. 数据源与下载

- **源**：CypherBench，movie 子图。
  - 仓库：<https://github.com/megagonlabs/cypherbench>
  - 数据集：<https://huggingface.co/datasets/megagonlabs/cypherbench>（`*_simplekg.json`，movie 约 507MB）
- **本仓库已含**：`test_movie.json`（401 题 + gold_cypher）、`gold.json`、`movie_schema.json`、`movie_notes.md`、`convergence.json`、`results_movie_*.json`、`pass3_summary.md`。
- **本仓库不含**：`*_simplekg.json`（原始 JSON，大）、`import/*.csv`（节点/关系 CSV，83MB，由 import_movie.py 生成）。

---

## 2. 预处理（导出 CSV）

```bash
# *_simplekg.json 流式转 neo4j-admin import 的 CSV（不整读入内存）
python3 scripts/import_movie.py movie data/movie/import
#   → data/movie/import/{nodes_<Label>.csv, rels_<Type>.csv, run_import.sh}
```

- 节点 ID 直接用 Wikidata `eid`（如 `Movie#Q1000094`），全局唯一，关系 CSV 的 subj/obj 可直接当 `:START_ID/:END_ID`。

---

## 3. 建库与加载（Neo4j）

```bash
cd data/movie/import
bash run_import.sh      # neo4j-admin database import full（节点 + 关系）
```

- 需要 Neo4j 4.4+（movie 图库）。`run_import.sh` 由 `import_movie.py` 自动生成。

---

## 4. 题集（401 题）

- **单一事实源**：`data/movie/test_movie.json`（401 题，含 `question` / `gold_cypher` / `answer_json` / `match_category`）。

---

## 5. schema / gold 源 / 生成 / fix

```bash
# schema 资源文件（节点标签/属性 + 关系类型/方向 → movie_schema.json）
python3 scripts/gen_schema_movie.py

# gold：逐条执行 test_movie.json 的 gold_cypher → gold.json
python3 scripts/gen_gold_movie.py
```

- **gold fix**（见 `analysis/gold-verification.md`）：评测前修 6 条非确定 gold（`ORDER BY 稀疏属性 DESC LIMIT 1` 空值排序）+ 4 条比较题重名笛卡尔积，使 gold 401/401 确定。
- 与 SQL 的差异：图库无「空集聚合→NULL」退化，也无 SQL 方言执行失败——401 条 gold_cypher 全部可执行且结果确定。

---

## 6. 资源文件（M+S 一次性注入）

- `data/movie/movie_schema.json`（图结构权威来源）+ `data/movie/movie_notes.md`（Cypher 注意事项，见 §10 收敛）。

---

## 7. 跑 benchmark

```bash
# M+S（注入 schema + notes；终答是裸 Cypher，审计落 ~/log/<chat_id>.cypher）
python3 scripts/run_bench_movie.py --all --results results_movie_mplus.json

# pass^3（三轮全对/并集）
python3 scripts/run_bench_movie.py --all --results results_movie_mplus_r2.json   # 第 2/3 轮
# 汇总三轮 → pass3_summary.md

# 收敛汇总（读一轮 results → convergence.json）
python3 scripts/summarize_convergence.py --db movie --results results_movie_mplus.json \
    --round 1 --notes "v1(初始 schema + 基础 notes)"
```

- **断点续跑**：结果逐条落盘，已跑的题自动跳过。

---

## 8. 判分

```bash
python3 scripts/score_cypher.py         # 候选 Cypher → neo4j 执行 → 值多重集比对
python3 scripts/eval_movie.py           # 逐条执行 gold_cypher，反向验证导入类型正确
```

---

## 9. 根因分析（文档索引）

| 主题 | 文档 |
|---|---|
| Cypher 收敛 + 失败结构 | `analysis/root-cause/bird-dev-convergence.md`（§5.1 段）、`analysis/gold-verification.md` |
| pass^3 汇总 | `data/movie/pass3_summary.md` |

---

## 10. 迭代时间线（收敛过程，非逐轮数字）

1. **导入 + schema/gold**：`import_movie.py` 导 CSV → `run_import.sh` 建 Neo4j 图 → `gen_schema_movie.py` / `gen_gold_movie.py`。
2. **round1（v1）**：初始 schema + 基础 notes，得下界。
3. **根因 → 修 notes → 重跑**：对失败题做根因（重名节点去重 / NULL 排序 / Genre.name 值不统一），逐条消成 notes 规则再重跑——收敛到 96.5% EX。
4. **pass^3**：三轮全对/并集，量化模型漂移。
5. **收口**：锁定 6 条硬地板（重名节点数据缺陷）+ 18 条模型漂移题。

> 精确数字以 `convergence.json`、`data/movie/pass3_summary.md` 与对应 `results_movie_*.json` 为准。

---

## 11. 相关文件清单

**数据（`data/movie/`）**：`test_movie.json`、`gold.json`、`movie_schema.json`、`movie_notes.md`、`convergence.json`、`results_movie_*.json`、`pass3_summary.md`、`import/run_import.sh`（`import/*.csv` 由 import_movie.py 生成、不随仓）。

**脚本**：`scripts/{import_movie,gen_schema_movie,gen_gold_movie,run_bench_movie,score_cypher,eval_movie,summarize_convergence}.py`。

**说明**：movie 导入的原始 `*_simplekg.json`（507MB）与导出 CSV（83MB）都不随仓；第三方从 HuggingFace 下数据集后按 §2–3 自建。
