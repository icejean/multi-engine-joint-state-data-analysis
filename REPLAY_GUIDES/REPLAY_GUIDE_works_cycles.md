# REPLAY_GUIDE_works_cycles.md — works_cycles（BIRD AdventureWorks）复现指南

> 从零复现论文 §4 的 **works_cycles**（BIRD dev 的 AdventureWorks 库，混淆改名）SQL 实验：
> 数据获取 → 混淆预处理 → 建库加载 → 题集/gold → 跑 S / M / M+S（含 pass^3）→ 判分 → 根因与迭代时间线。
> 资产：`data/works_cycles/`、`scripts/`、`analysis/root-cause/`。

---

## 0. 定位与口径（先读）

- **数据域**：关系型（SQL），BIRD dev 的 `works_cycles` 库 = Microsoft AdventureWorks 样例库（65 表）。
- **机制对照**：同一 126 题 × 三档元数据库，对比三种机制——
  - **S**（single-shot Text2SQL）：单次 LLM 调用、元数据预注入、无执行反馈。
  - **M**（Agent 自迭代）：多轮工具调用 + 执行反馈 + 现场探索 `sys_*` 元数据表。
  - **M+S**（Agent + 一次性注入）：把 M 轴的「现场探索」替换为「按绝对路径一次性加载 `schema.json` + `notes.md`」。
- **诚实边界**：M / M+S 走 Portal 真实执行链路（openclaw → MCP → dataai-sql kernel），需部署 DataAI Portal 全栈才能复跑——
  开源 DataAI 项目见 <https://github.com/icejean/dataai_with_jupyterlab_and_rstudio>（其中 `docs/DataAI-Portal-AI数据分析平台简介.md` 是 Portal 介绍资料入口）。
  S 系列直连 LLM API + pymysql 判分，**第三方可完全复现**。
- **判分口径**：M/S 判分用 `results_equal_relaxed`（值多重集比对，放宽多输出列）保证两轴可比。

---

## 1. 数据源与下载

- **源**：BIRD（BIg Bench）dev 集，数据库 `works_cycles`（AdventureWorks）。
- **下载**：<https://bird-bench.github.io> → 下载 dev 集，得到：
  - `dev.json` / `train.json` / `dev_tables.json` / `train_tables.json`（题库 + 表结构）
  - `dev_databases/works_cycles/works_cycles.sqlite`（数据库）
  - `dev_databases/works_cycles/database_description/*.csv`（65 表英文列描述）
- **本仓库已含**（无需下载即可复现判分与结论）：`question_set_final_obfuscated.json`、`gold.json`、`obfuscation_map.json`、`descriptions.json`、`works_cycles_er_schema.json`、`notes.md`、`database_description/*.csv`、全部 `results_*.json`。
- **本仓库不含**（需下载）：`works_cycles.sqlite`（二进制库文件）、`train.json` / `dev.json`（BIRD 题库，大）。

---

## 2. 预处理（混淆改名）

脚本在 `data/works_cycles/`（库专属规则）。以下命令均在 **repo 根目录** 下执行：

```bash
cd data/works_cycles

# 1) 选题：从 BIRD train.json 筛有区分度的题（≥2 JOIN 优先，实际 98 题）
python3 select_questions.py --train-json <BIRD>/train.json --db-id works_cycles \
    --target 100 --out question_set_100.json

# 2) 合并官方 98 + 自拟 28 → 最终题集（126 题）
python3 merge_question_sets.py --official question_set_100.json \
    --custom custom_questions_24.json --out question_set_final.json

# 3) 混淆映射（表名缩写 + 非 FK 列去元音截 4 + FK 列 → ref1/ref2）
python3 generate_obfuscation_map.py --sqlite works_cycles.sqlite --out obfuscation_map.json

# 4) gold SQL 改写（原名 SQLite 方言 → 混淆名 MySQL 方言）
python3 transform_gold_sql.py --questions question_set_final.json \
    --map obfuscation_map.json --out question_set_final_obfuscated.json

# 5) 中文描述（表类型 fact/dim/junction + 字段 gloss）
python3 generate_descriptions.py --map obfuscation_map.json \
    --desc-dir database_description --out descriptions.json

# 6) 三梯度元数据 JSON（L1 裸 / L2 字典 / L3 ER）
python3 build_metadata_gradients.py --db-dir <BIRD>/dev_databases/works_cycles --out-dir metadata
```

> 混淆规则与 Sakila 三梯度库对齐（`actr/addr/cust` 去元音风格）。`obfuscation_map.json` 是**可逆映射**（原名 ↔ 缩写名 + 主键 + 外键），供建库、gold 翻译、判分回溯共用。

---

## 3. 建库与加载

```bash
# SQLite → MySQL 三梯度库（读 obfuscation_map.json + descriptions.json）
python3 data/works_cycles/migrate_to_mysql.py
```

- 产出三库（数据一致，元数据逐级增加）：
  - `works_cycles`（裸数据，65 表，混淆名，无 sys 表）→ M0 / S0
  - `works_cycles_dict`（+ `sys_tables` / `sys_table_fields`）→ M1 / S1
  - `works_cycles_er`（+ `sys_foreignkeys`）→ M2 / S2
- 数据清理：BIRD 的 `works_cycles.sqlite` 里 `CountryRegion` 首行是 CSV 表头误入，脚本已 `DELETE ... WHERE ModifiedDate='ModifiedDate'` 修正。
- 凭据：repo 根 `.env`（`MYSQLHOST/MYSQLPORT/MYSQLUSER/MYSQLPASSWORD`），缺省回退 `/opt/dataai/templates/.env`。

---

## 4. 题集（126 题）

- **单一事实源**：`data/works_cycles/question_set_final_obfuscated.json`（126 题，含 `id/question_id/question/evidence/SQL_obfuscated/source`）。
- 组成：98 官方（`question_set_100.json`）+ 28 自拟（`custom_questions_24.json`）。
- 自拟题覆盖 BIRD 未覆盖的场景（如 BOM 物料清单 `WITH` 递归、`end_dt`/`rt_chng_dt` 历史表口径等）。

---

## 5. gold 源 / 生成 / fix

```bash
# gold 源 = question_set_final_obfuscated.json 的 SQL_obfuscated 字段；对 works_cycles 库执行
python3 scripts/gen_gold_wc.py
```

- 输出：`data/works_cycles/gold.json`（可判分题基准）+ `data/works_cycles/gold_errors.json`（剔除：执行失败 / 退化 gold「空集聚合→NULL」）。
- **gold fix**（见 `analysis/root-cause/gold-fixes-bird-dev.md`、`analysis/gold-verification.md`）：定稿版 gold = **gold-v4**，修了 3 题（Q14/72/79 是 gold bug）；「35 处」→ gold-v4 又修 3 处。

---

## 6. 资源文件（M+S 一次性注入）

```bash
# 从 MySQL sys_tables/sys_table_fields/sys_foreignkeys 打包成数据字典 + 外键 + 列类型
python3 scripts/gen_schema_resource.py works_cycles_er
```

- 产出 `data/works_cycles/works_cycles_er_schema.json`。
- `data/works_cycles/works_cycles_er_notes.md`：迭代积累的注意事项（库专属口径，见 §10）。

---

## 7. 跑 benchmark（S / M / M+S / pass^3）

```bash
# S 系列（single-shot，第三方可复现；key 读自 ~/.openclaw / ~/.claude / ~/.dsh）
python3 scripts/run_bench_wc_singleshot.py --all --levels S0,S1,S2 \
    --model deepseek-v4-flash --base-url <DeepSeek-OpenAI-endpoint> --results results_wc_s_full.json

# M 系列（Agent 自迭代，需 Portal 全栈；信创环境加 --backend dsh）
python3 scripts/run_bench_wc.py --all --levels M0,M1,M2 \
    --model deepseek-v4-flash --results results_wc_m_126_full.json

# M+S 系列（一次性注入 schema.json + notes.md）
python3 scripts/run_bench_wc_mplus.py --all --levels M0,M1,M2 \
    --model deepseek-v4-flash --results results_wc_mplus_126.json

# pass^3（每题 × 3 轮，统计 平均 / 三轮全对 / 并集）
bash scripts/run_mplus_pass.sh    # 或 run_pass.sh
```

- **pass^3 口径**：同一题跑 3 轮，统计 平均（pass@1）/ 三轮全对（all-3）/ 并集（≥1 轮对），对应论文 §4.3 的方差与漂移分析。
- **断点续跑**：结果逐条落盘，已跑的 `(question_id, level)` 自动跳过。
- **S0 漂移/稳定实验**（`scripts/run_s0_drift.sh`）：S0 单发非确定性对照（漂移 vs temperature=0 稳定），结果 `results_wc_s0_drift_r{1,2,3}.json` / `results_wc_s0_stab_r{1..5}.json`。
- **跨模型**（M+S 换模型验证「跨模型成立」）：glm-5.2（`scripts/run_mplus_glm52.sh` + `run_mplus_glm52_pass.sh` → `results_wc_mplus_126_glm52*.json`）、glm-5.1/GLM-5-Pro（`results_wc_mplus_glm5pro_126*.json`）。
- **探索变体**（结果文件前缀即过程）：`pilot`/`pilot_clean`（26 题试点）、`m_26*`/`s_26*`（26 题子集）、`m_tier1_verify`/`fix*`/`q*`（定向验证/单题重试）、`mplus_126_pass4`（天花板收口）。

---

## 8. 判分

```bash
python3 scripts/score.py --selftest          # 自检（gold 自身为候选，期望 100%）
python3 scripts/rescore_wc.py                # 复判
python3 scripts/statistical_analysis.py      # McNemar + bootstrap CI + pass@k → p2-statistical-results.md
```

- 判分引擎：`scripts/score.py` 的 `results_equal`（值多重集比对，忽略行序/列序，数值 2 位容差）。

---

## 9. 根因分析（文档索引，均在 `analysis/root-cause/`）

| 主题 | 文档 |
|---|---|
| 收敛终点 / round5 | `works-cycles-final-report.md`、`works-cycles-root-cause-round2.md` |
| S 轴根因 | `s-axis-root-cause-analysis.md`、`s-axis-full-root-cause.md` |
| M 轴根因 | `m-axis-root-cause-analysis.md`、`m-axis-full-root-cause.md` |
| 跨模型对照 | `mplus-126-glm52-vs-deepseek.md`、`glm52-7q-root-cause.md`、`bird-dev-pro-vs-flash.md` |
| pass^3 方差 | `pass3-variance-report.md` |
| pass4 天花板 | `pass4-failure-root-cause.md` |
| 单题根因 | `q90-root-cause-analysis.md` |
| gold 审计 | `gold-fixes-bird-dev.md`（+ `analysis/gold-verification.md`） |
| BIRD dev 收敛（跨库） | `bird-dev-convergence.md` |

---

## 10. 迭代时间线（复现「收口」的过程，非逐轮数字）

复现的终点不是某一轮数字，而是把实验推到**收口状态**——机制结论自洽、天花板锁定、边界诚实。按顺序走：

1. **选题 + 建库**：BIRD dev `works_cycles` 选题 98 + 自拟 28 → 126 题；三梯度库 `works_cycles/_dict/_er`。
2. **S 轴**：跑 single-shot 基线（S0/S1/S2 三档元数据预注入），确立「单发天花板」与「预注入在大 schema 下退化」的边界。
3. **M 轴**：跑 Agent 自迭代（M0/M1/M2），观察「执行反馈 + 元数据探索」相对 S 的增益与轮数/成本。
4. **M+S**：跑注入模式，对照 M——量化「探索 → 一次性注入」省下的轮数/token、以及准确率是否打平。
5. **pass^3**：每题 × 3 轮，量化模型漂移（漂移题占比）与三轮全对口径。
6. **pass4 / 收口**：按失败根因逐题修 notes/gold，把准确率推到天花板、锁定剩余硬地板题（无法靠机制消除的数据缺陷）。
7. **跨模型验证**：换 glm-5.2 复跑 M+S，确认「M+S 跨模型成立」。

每步的失败根因 → 修 notes/gold → 重跑，是 §9 各根因文档记录的核心循环。最终状态 = SQL 线三库（works_cycles / financial / formula_1）断层式领先 single-shot SOTA。

> 精确数字以 `analysis/p2-statistical-results.md` 与对应 `results_*.json` 为准。

---

## 11. 相关文件清单

**数据（`data/works_cycles/`）**：`question_set_final_obfuscated.json`、`question_set_100.json`、`custom_questions_24.json`、`obfuscation_map.json`、`descriptions.json`、`gold.json`、`gold_errors.json`、`works_cycles_er_schema.json`、`works_cycles_er_notes.md`、`database_description/*.csv`（65 表）、`metadata/works_cycles_L{1,2,3}_*.json`、`metadata/fk_diff_sqlite_vs_tablesjson.md`（FK 口径差异注）、`results_wc_*.json`（含 s0_drift/s0_stab/glm52/glm5pro/pass4 变体）。

**脚本**：`data/works_cycles/{select_questions,merge_question_sets,generate_obfuscation_map,transform_gold_sql,generate_descriptions,build_metadata_gradients,migrate_to_mysql,_rootcause2_dump}.py` + `scripts/{gen_gold_wc,gen_schema_resource,run_bench_wc,run_bench_wc_mplus,run_bench_wc_singleshot,score,rescore_wc,statistical_analysis}.py` + `scripts/run_{mplus_pass,pass,s0_drift,mplus_glm52,mplus_glm52_pass}.sh`。

**不随仓（需下载）**：`works_cycles.sqlite`、`train.json`/`train_tables.json`/`train_gold.sql`、`Customer_classic.csv`（原始/大数据）。

**分析文档**：`analysis/root-cause/` 下 §9 所列各篇 + `analysis/{p2-statistical-results,pass3-variance-report,tech-route-selection,stateful-analysis-report}.md`。
