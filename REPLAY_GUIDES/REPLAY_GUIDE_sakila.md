# REPLAY_GUIDE_sakila.md — sakila（反记忆 / 元数据梯度）复现指南

> 从零复现论文 §4.1 / §7.1③ 引用的 **sakila** 元数据梯度实验：用官方 MySQL sakila 样例库改名 + 加合成表，
> 做「裸 schema / +数据字典 / +ER 图」三档元数据上的 S（single-shot）vs M（Agent 自迭代）对照，
> 同时用改名/混淆检验**反记忆**（模型是否靠背下公开 sakila 库取巧）。
> 资产：`data/sakila/`、`scripts/`。

---

## 0. 定位与口径（先读）

- **数据域**：关系型（SQL），官方 MySQL `sakila` 样例库（16 基表）改名版。
- **机制对照**：同一 25 题 × 三档元数据库，对比 S（single-shot）与 M（Agent 自迭代）。
- **反记忆**：sakila 是公开样例库，改名/混淆（`rename_map.json`）用于检验模型是否靠记忆而非理解。
- **诚实边界**：
  - **S 系列**（single-shot）：直连 LLM API + pymysql 判分，**第三方可完全复现**。
  - **M 系列**（Agent 自迭代）：复用 DataAI Portal 真实执行链路（openclaw → MCP → dataai-sql kernel），需部署 Portal 全栈——
    开源 DataAI 项目见 <https://github.com/icejean/dataai_with_jupyterlab_and_rstudio>（`docs/DataAI-Portal-AI数据分析平台简介.md` 是 Portal 介绍资料入口）。
  - M 系列在 prompt 里注入「先查 sys_* 元数据表」的过程性指令（`meta_instr`），是隔离「Agent 会不会主动用 ER」变量的**实验控制**，非 Portal 默认用户消息。

---

## 1. 数据源与下载

- **源**：MySQL 官方 sakila 样例库。下载：<https://dev.mysql.com/doc/index-other.html> 的「Example Databases → Sakila Database」，直链 `https://downloads.mysql.com/docs/sakila-db.tar.gz`（zip 版 `sakila-db.zip`）。
- **导入**：

```bash
tar xf sakila-db.tar.gz   # → sakila-db/（sakila-schema.sql + sakila-data.sql）
mysql -u root -p -e "SOURCE /path/to/sakila-db/sakila-schema.sql"
mysql -u root -p -e "SOURCE /path/to/sakila-db/sakila-data.sql"
```

- **行数校验**（sakila 内容稳定，用行数做一致性校验）：`customer 599 / film 1000 / film_actor 5462 / payment 16500 / rental 15420 / store 2`。

---

## 2. 建三档库 + rename_map（改名/混淆 + 合成表）

```bash
# 幂等重建 sakila_rntl / sakila_rntl_m1 / sakila_rntl_meta + 导出 rename_map.json
python3 scripts/build_sakila_rntl.py
```

- 三档库（数据一致，元数据逐级增加）：
  - `sakila_rntl`（裸 schema，无 sys 表）→ M0 / S0
  - `sakila_rntl_m1`（+ `sys_tables` / `sys_table_fields` 数据字典）→ M1 / S1
  - `sakila_rntl_meta`（+ `sys_foreignkeys` ER 图）→ M2 / S2
- 16 基表改名（`actr/addr/cust` 去元音风格）+ 外键列混淆为 `ref<N>` + 字典措辞「去表名化」。
- **合成表**（全部由 `build_sakila_rntl.py` 幂等生成，无一次性手工步骤）：`card`（798，付款卡维度，制造换卡歧义）、`awd`（21，复合外键奖项表）、`doc`（`film_text` 改名 + 反记忆改造：G/PG/PG-13 子集 + 55 部片名加「(旧版)」）。
- 凭据：repo 根 `.env`（缺省回退 `/opt/dataai/templates/.env`）。

---

## 3. 题集（25 题）

- **单一事实源**：`data/sakila/questions.json`（25 题，题面 + gold_sql）；人读版 `questions-final.md`；旧 40 题设计稿 `questions.md`（留档）。

---

## 4. gold 生成

```bash
# 执行 questions.json 的 gold_sql → data/sakila/gold.json（判分基准）
python3 scripts/gen_gold.py
```

---

## 5. 跑 benchmark（S / M）

```bash
# S 系列（single-shot，第三方可复现；key 读自 ~/.openclaw / ~/.claude）
python3 scripts/run_bench_singleshot.py --all --levels S0,S1,S2 \
    --model <model> --base-url <endpoint> --results results_singleshot_<model>.json

# M 系列（Agent 自迭代，需 Portal 全栈；信创环境加 --backend dsh）
python3 scripts/run_bench.py --all --levels M0,M1,M2 \
    --model <model> --results results_<model>.json
```

- **冒烟**：`python3 scripts/smoke_test.py`（数据源/元数据/gold/判分端到端自检）。
- **断点续跑**：结果逐条落盘，已跑的 `(question_id, level)` 自动跳过。

---

## 6. 判分

```bash
python3 scripts/score.py --selftest   # 以 gold 自身为候选，期望 100%
```

- 判分引擎：`scripts/score.py` 的 `results_equal`（值多重集比对，忽略行序/列序，数值 2 位容差）。

---

## 7. 报告与根因

| 主题 | 文档 |
|---|---|
| 对外实验报告（结论 + 数据） | `analysis/exp-report-sql-metadata-gradient.md` |
| 权威结论推导（逐题证据） | `analysis/findings.md` |
| 实验设计 | `analysis/SPEC.md`（旧）、`analysis/paper-spec.md` |
| 错误根因分析 | `analysis/root-cause/error-root-cause-analysis.md` |

---

## 8. 相关文件清单

**数据（`data/sakila/`）**：`questions.json`、`questions-final.md`、`questions.md`、`gold.json`、`rename_map.json`、`results_*.json`。

**脚本**：`scripts/{build_sakila_rntl,gen_gold,run_bench,run_bench_singleshot,score,smoke_test}.py`。

**说明**：sakila 原库从 MySQL 官方下载；改名/合成表/三档库全部由 `build_sakila_rntl.py` 确定性重建，无需单独准备数据。
