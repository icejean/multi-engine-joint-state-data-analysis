# M 轴全量根因分析（works_cycles 126 题 × M0/M1/M2）

> 数据源：`results_wc_m_126_full.json`（378 次 agent 运行，模型 deepseek-v4-flash，openclaw 后端，硬隔离三档）。
> 本文回答：① M 轴为什么元数据梯度近平（与 sakila/S 轴相反）；② 失败归因到可修 / 需判断 / 固有；③ fix 清单与重跑建议。

---

## 0. 结论先行

| 档 | EX | Δ₄ | 对照 S 轴 | 对照 sakila |
|---|---|---|---|---|
| M0 裸 | **69.8%** (88/126) | — | S0 50.0 | M0 80 |
| M1 +字典 | 72.2% (91/126) | +2.4pp | S1 64.3 | M1 96 |
| M2 +字典+ER | 70.6% (89/126) | +0.8pp | S2 65.1 | M2 100 |

**三个反直觉事实**：
1. **agent 梯度近平**（M0≈M1≈M2），而 single-shot 梯度强（S0→S2 +15pp）、sakila agent 梯度强（+20pp）。
2. **M0 已压过 S2**（69.8 > 65.1）：裸 agent 胜过满配元数据的 single-shot。
3. **梯度平是部分假象**：M1/M2 被人为压低（见 §2 机制 2 反噬），修掉后梯度应恢复。

---

## 1. 失败总览

- 唯一失败题 **49 道**；按档：M0=38 / M1=35 / M2=37；**三档全挂 24 道**（硬地板）。
- 无答案类（超时 4 + 报错 1）仅占 378 次的 **1.3%**；其余都是「有 SQL 但结果不等价」。

---

## 2. 五大机制

### 机制 1：meta_instr 缺「时间态/最新值」规则（prompt 旧版）★最高优先

M 轴 `run_bench_wc.py` 的 meta_instr 是旧版，**缺 S 轴 fix3 的「有效期/时间态」和 fix2 的「禁保留字」**（见 `s-axis-root-cause-analysis.md` §3）。gold 却已按「`end_dt IS NULL` = 当前生效」「每人最新薪资/时薪」口径修过（gold-verification §4.4）。

- 命中：Q9/Q29/Q35/Q36/Q50/Q65/Q72/Q82/Q87/Q100（最新薪资、在职重叠、BOM 递归 end_dt）。
- 例：Q82「Engineering 待最久」gold 要 `ORDER BY end_dt - strt_dt`，agent 猜 `ORDER BY strt_dt ASC`。
- **Fix：把 S 轴两条规则原样回填 meta_instr（零风险、零成本）。**

### 机制 2：meta_instr 反噬（强制「先查元数据」）★梯度平的元凶

meta_instr 写死「生成 SQL 前必须先查 sys 表」。后果两类：

- **超时**（4 题次，占 1.1%）：Q25@M0、Q19@M1、Q36@M2、Q61@M2，均 `elapsed=270s`（subprocess 硬超时兜底，openclaw 的 `--timeout 240` 没拦住）。其中 3 题在其他档通过 → 孤立方差。
- **迷路**（~7 题次，把探索语句当终答）：Q14@M2 终答是 `SELECT ... FROM sys_tables WHERE desc LIKE '%客户%'`；Q36@M0 查了不存在的 `sys_tables`（ProgrammingError）；Q50@M1/M2、Q71@M1、Q83@M1、Q34@M2 同理。

**关键**：反噬**专打 M1/M2**（只有 M1/M2 才强制查 sys 表，M0 用 list_objects 没这包袱），所以 M1/M2 的 72.2%/70.6% 被系统性压低。**Fix：超时 240→360s + meta_instr 加收敛句**（「最多探索 ~N 轮、拿不准就基于已探明信息给最优解、别反复查同一张表、别把元数据查询当最终答案」）。

### 机制 3：拆列/CONCAT 口径冲突（gold 表示不一致）

- **full name 缺中间名**：Q18/Q70/Q87，gold 要 `frst_nm+mddl_nm+lst_nm` 三列，agent 只给 `frst_nm+lst_nm`。
- **CONCAT 反向冲突**：Q112/Q117/Q118，gold 用 `CONCAT(frst,' ',lst)` 单列，但 prompt 禁 CONCAT 让 agent 拆成两列 → 与 gold 单列对不上。
- 同是「名字」，gold 三处三种表示（三列 / 两列 / CONCAT 单列），自相矛盾。
- **Fix：gold 归一化（统一「full name」表示）+ 判分对名字做等价放宽。**

### 机制 4：gold 语义残留（BIRD 原生态歧义，需判断）

非「agent 对、gold 错」的干净假阴性，而是 **BIRD 原题本身含糊**：

- Q4「wish to receive email promotion」：`eml_prmt` 有 0/1/2 三值，gold 取 `=1`(5044 人)，agent 猜 `<>0`(8814 人，含 2)。合理读法两种都成立。
- Q7「over at least 1 review」：≥1 = 2 产品，gold 用 `COUNT>1` = 1 产品。「over」与「at least」语义打架。
- Q35「average age」：gold 用 `YEAR(CURRENT)-YEAR(birth)`（粗糙，42.0），agent 用 `TIMESTAMPDIFF`（精确，41.75）。gold 偏高一截。
- Q114「per month」：gold 用 `substr(ordr_dt,1,7)`（"2013-01"），agent 用 `MONTH()`（1..12）。

**Fix：逐题判断「正确口径」再改 gold（第二轮 gold 核定，非机械归一）。**

### 机制 5：固有难句（真地板）

Q90（双重歧义+间接 schema，两轴 6 格全挂）、store ref1/ref2 join（Q76/Q78/Q124）、PO vs SO（Q37）、LIMIT tie（Q119）、Q52（4832 行数据待查）等，约 15 题。

---

## 3. 静态重判结果（不重跑 LLM）

**可静态确定的**（改判分/改 gold 即翻）：

| 类别 | 题 | 静态翻正 |
|---|---|---|
| 拆列/CONCAT 归一（机制 3） | Q18/Q70/Q87/Q112/Q117/Q118 | ~10 题次 ≈ +3pp/档 |

**静态不可测、需重跑的**（prompt 行为改变）：

| 类别 | 题 | 预估 |
|---|---|---|
| 时间态/最新值（机制 1） | ~10 题 | +5~8pp/档 |
| 超时+收敛（机制 2） | 4 超时 + ~7 迷路 | +2~3pp/档（M1/M2 更多） |
| gold 语义（机制 4） | ~6 题 | +3~4pp/档（需先核定） |

> **诚实边界**：机制 3/4 是 gold 侧、可静态重判；机制 1/2 是 prompt 侧、只能重跑验证。静态重判的确定性收获只有拆列那一块（+3pp 量级）；Jean 预期的「大增长」主要在机制 1/2，**必须重跑才能坐实**。

---

## 4. Fix 清单（按优先级）

1. **[prompt] 回填时间态+最新值+禁保留字**：把 S 轴 `build_prompt` 的三段规则移植进 `run_bench_wc.py` 的 meta_instr。
2. **[prompt] 收敛句 + 超时**：超时 240→360；加「限制探索轮数/别把元数据查询当终答/别反复查同一张表」。
3. **[gold] 拆列/CONCAT 归一**：统一 full name 表示；判分对名字等价放宽。
4. **[gold] 机制 4 逐题核定**：eml_prmt / COUNT>1 / age 口径 / month 格式，第二轮 gold 核定。

---

## 5. 重跑建议

- **最小验证**：只改 1+2（prompt），重跑 **M1 单档**（126 题，~2.4h、$2.4）。若 M1 从 72.2% 显著升（预期 +8~12pp），即证明「平梯度是反噬+缺时间态造成的」，再重跑 M0/M2。
- **完整**：改 1+2+3，三档重跑（~7.5h、$7.6）。
- **机制 4 单独走**：不阻塞重跑，另行逐题核定。

关联：`gold-verification.md`、`s-axis-root-cause-analysis.md`、`q90-root-cause-analysis.md`。
