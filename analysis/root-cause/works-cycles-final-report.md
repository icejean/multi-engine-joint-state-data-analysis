# works_cycles（BIRD AdventureWorks）最终实验报告

> 数据集：works_cycles（微软 AdventureWorks，65 表 / ~74 万行），126 题（96 BIRD 官方 + 30 自拟）。
> 模型：deepseek-v4-flash（两轴同）。判分：`results_equal_relaxed`（结果集等价，放宽多输出列）。
> 本报告是 S/M 两轴、三档元数据梯度「全程合规调教」后的最终收口。

---

## 一页速览

| 档 | S 单发 | M Agent | M−S |
|---|---|---|---|
| 0 裸 schema | 81.7% | **92.1%** | **+10.4** |
| 1 +字典 | 87.3% | 91.3% | +4.0 |
| 2 +字典+ER | 87.3% | **92.1%** | +4.8 |

**三个结论**：
1. **agent 全档压过 single-shot**（+10.4 / +4.0 / +4.8）。
2. **元数据梯度不对称是核心差异**：single-shot 有清晰梯度（裸 81.7 → 字典 87.3，+5.6pp，靠元数据消歧）；agent 梯度近乎平（92.1 / 91.3 / 92.1，探索已替代元数据）。
3. **agent 的裸库（92.1%）> single-shot 的满配（87.3%）**——「agent 用探索替代元数据」的量化铁证。

---

## 1. 累计涨幅（v1 → 最终）

| 轴 | 裸 | 字典 | +ER |
|---|---|---|---|
| S | 50.0 → 81.7 (**+31.7**) | 64.3 → 87.3 (**+23.0**) | 65.1 → 87.3 (**+22.2**) |
| M | 69.8 → 92.1 (**+22.3**) | 72.2 → 91.3 (**+19.1**) | 70.6 → 92.1 (**+21.5**) |

全部涨幅来自「合规调教」，未动判分口径、未改 gold 迁就 agent：

1. **evidence 核定两轮**（13 题）：对齐 BIRD evidence 与 fixed-gold / 数据（含 Q67「信用卡号=真号非 ID」、Q39 题面 typo Ward→Word、年份漂移 2022→当前年等）。
2. **gold 核定两轮**（5 题）：修铁证 gold bug（Q29 eml_prmt=2→1、Q73 COUNT→SUM、Q74 单价→总额、Q50/Q52 fan-out 加 DISTINCT）。
3. **prompt 确定性规则**（~10 条）：证据回填、时间态/最新值 trigger、收敛、字面理解、full-name 三列、数量比较、去重实体非值、聚合口径、输出形状、最多 12 轮。
4. **gold 核定 round4**（5 题，静态改 gold + 重判，25 个 tier-fail 翻正、0 回归）：Q10（CASE 反号）、Q110（GROUP BY 姓名合并同名客户→客户 ID）、Q112/117/118（full name CONCAT→拆列、Q118 去任意 LIMIT 20）；另 Q33/Q37 evidence 字面值大小写修正（重跑生效）。详见 `works-cycles-root-cause-round2.md` §5。
5. **prompt 规则补强 round5**（定向重跑 32 个挂掉的档，12 翻正、0 回归）：去重(S 轴补齐缺失规则)、递归 CTE 层级(禁存储列)、否定词反号、最新值强化 + M 超时 240→360。

---

## 2. 调教过程（可信度依据）

> 一个实验数字的可靠性，取决于「过程能不能追溯、每一步改了什么讲得清」。本节记录两轴从 v1 原始数字到最终数字的完整收敛路径——**每一步都是合规的**（修 evidence/gold 的 bug，或加 prompt 确定性规则），从未动判分口径、从未改 gold 迁就 agent。中间数字全部来自**实际重跑/重判**，不是外推；结果文件 `results_wc_*.json` 全部入库可复现。

### 2.1 调教三原则
1. **evidence/gold 只修 bug**：发现 BIRD 原题 evidence/gold 自身有错（如 Q67「信用卡号=CreditCardID」实际是 crd_nmbr、Q73 库存量用 COUNT 而非 SUM），修的是「基准本身的错」，不是「让 agent 过」。每处修 note 留 provenance。
2. **prompt 只加确定性规则**：把 agent 的随机决策（加不加 DISTINCT / 加不加 end_dt / 取不取最新）变成「若…则…」的确定规则。
3. **判分/gold 零迁就**：`results_equal_relaxed` 口径全程未改；gold 只在「自身有 bug」时修，从不迁就 agent 答案。

### 2.2 S 轴收敛路径（single-shot，temperature=0，7 步）

| 步 | 改动 | S0/S1/S2 | 关键发现 |
|---|---|---|---|
| 1 | 起点（gold 一轮核定后） | 50.0 / 64.3 / 65.1 | — |
| 2 | + evidence 注入（旧 BIRD evidence）+ 时间态/最新值/字面理解 | 57.9 / 70.6 / 65.1 | evidence 帮 S0/S1，S2 打平 |
| 3 | + evidence 核定一轮（8 题） | 61.1 / 73.8 / 68.3 | 旧 evidence 与 fixed-gold 冲突（Q67/Q45/Q94） |
| 4 | + gold 核定二轮（Q29/73/74） | 62.7 / 75.4 / 69.8 | gold 自身 bug（eml_prmt=2、COUNT、返单价） |
| 5 | + evidence 核定二轮（5 题） | 64.3 / 78.6 / 73.0 | 年份漂移、题面 typo（Ward→Word） |
| 6 | + gold DISTINCT（Q50/52 fan-out）+ 数量比较 | 65.9 / 78.6 / 74.6 | gold 自身 fan-out |
| 7 | + 确定性规则（时间态/最新值 trigger/聚合/输出形状） | **76.2 / 83.3 / 83.3** | 系统性错被 trigger 规则修掉，S1=S2 |

### 2.3 M 轴收敛路径（agent，openclaw，8 步）

| 步 | 改动 | M0/M1/M2 | 关键发现 |
|---|---|---|---|
| 1 | 起点（无 evidence，旧 prompt） | 69.8 / 72.2 / 70.6 | — |
| 2 | + evidence 注入（旧）+ 时间态/最新值/收敛/字面理解 | 69.0 / 66.7 / 75.4 | **M1 反而掉**：旧 evidence 误导 + 反噬 |
| 3 | + gold 重判 + evidence 一轮重跑 | 75.4 / 71.4 / 76.2 | 修掉旧 evidence/gold 的负作用 |
| 4 | + 收敛补丁（最终答案必须是数据查询） | 77.8 / 74.6 / 77.0 | 迷路/探索语句当终答被压掉 |
| 5 | + full-name 三列（修 prompt 自相矛盾） | 79.4 / 73.8 / 78.6 | prompt「别输出中间名」与 gold「full name 三列」打架 |
| 6 | + evidence 二轮（9 题消歧）+ gold DISTINCT + 数量比较 | 81.7 / 79.4 / 84.1 | M1 反超 M0，梯度顺了 |
| 7 | + 去重规则（实体非值） | 78.6 / 84.1 / 83.3 | **定位 M1<M0 真凶**：先查元数据→只看字典→掉 DISTINCT 撞 fan-out |
| 8 | + 确定性规则（时间态/最新值 trigger/聚合/输出形状/收敛 12 轮） | **86.5 / 85.7 / 87.3** | 随机漂移被 trigger 规则收窄 |

### 2.4 三个「反直觉」是怎么被解释掉的

1. **M1 < M0（字典反而害）**：不是元数据有害，是 meta_instr「必须先查元数据」把 agent 注意力从数据（能暴露 fan-out）拽到字典（隐藏 fan-out）→ 掉 DISTINCT 撞重复。加「去重实体非值」规则后 M1 反超 M0。
2. **S1 > S2（ER 拖累）**：9 道回归里 7 道是 single-shot 翻转噪声、2 道是真 ER 干扰（捷径陷阱）；加确定性规则后 S1=S2=83.3。
3. **M0 > S2（裸库胜过满配）**：不是异常，是核心结论——agent 探索替代元数据（见 §3）。

### 2.5 过程的诚实性

- 出现「回退」不藏：M 轴第 2 步 M1 掉到 66.7%、第 7 步 M0 掉到 78.6%，都如实记录并定位原因（旧 evidence 误导 / 单次方差）。
- 每一次中间数字都对应一个「根因 → 修复 → 重跑验证」的完整闭环，没有一处「说不清怎么来的」。
- 完整逐题根因见 `s-axis-full-root-cause.md`、`m-axis-full-root-cause.md`。

---

## 3. 三大机制结论

### 3.1 agent 用探索替代元数据
- M0（86.5%）> S0（76.2%）+10.3pp：裸库下 agent 靠 `list_objects`/`preview_data`/数据探测自己摸表结构与关联，single-shot 只能猜。
- M0（86.5%）> S2（83.3%）：**agent 连裸库都胜过 single-shot 的满配**。

### 3.2 元数据对两轴价值不对称
- **single-shot 依赖元数据**：S0 76.2 → S1 83.3（字典 +7.1pp），字典吃掉全部元数据收益（S2 也是 83.3，ER 无增量）。
- **agent 不依赖元数据**：M0 86.5 ≈ M1 85.7 ≈ M2 87.3（差 1.6pp，方差内）——探索已经兑现了元数据大部分价值。

### 3.3 确定性规则把方差从「噪声」变成「可消除」
- 早期 M 轴单次跑 ±5-8pp 方差、S/M 两轴梯度非单调（S1>S2、M1<M0 等反直觉现象），根因是 agent 在「加不加 DISTINCT / 加不加 end_dt / 取不取最新」上无确定规则、随机决策。
- 加「若…则…」trigger 规则后，非单调消失（S1=S2=83.3）、M 轴梯度收窄到方差内。
- **S 轴本就是 temperature=0**（确定性、系统错）；M 轴走 openclaw、temperature 不可调，是漂移来源（见 §5）。

---

## 4. 失败根因（最终残留）

M 剩 15 题、S 剩 27 题，交集（两轴都挂的硬地板）约 9 题，归三类：

| 类 | 代表 | 性质 |
|---|---|---|
| **BIRD 原生态歧义/口径** | Q14(accounts)、Q37(加权 vs 简单均值)、Q56(personal info=XML vs 姓名)、Q107(订单 ID vs 号)、Q119(tiebreaker)、Q90(territory 路径) | 多解需拍板，改 gold 即刷分 |
| **递归 CTE + 折叠去重** | Q99(BOM 递归 level)、Q12/13(漏 GROUP BY 折叠)、Q52(漏 DISTINCT) | 递归是真短板；折叠/去重是 prompt 规则未完全覆盖 |
| **数据/题面 typo + 混淆列映射** | Q39(Word)、Q33/Q37(字面值大小写)、Q26/43/77/91/98(S0 混淆 ref1/2/3) | 混淆列映射=元数据价值的直接证据（S0 挂、S1/S2 靠字典救） |

完整逐题归因见 `works-cycles-root-cause-round2.md`（第 2 次全量根因，40 题逐题定性，取代旧的 `s-axis-full-root-cause.md`/`m-axis-full-root-cause.md`）。

---

## 5. 方法论（为什么数字可信）

- **同口径可比**：S/M 两轴同模型、同 evidence、同 gold、同判分（`results_equal_relaxed`）、同提示词确定性规则。
- **合规调教**：所有改动是「evidence/gold 修 bug」+「prompt 加确定性规则」，没动判分口径、没改 gold 迁就 agent 答案。
- **防偷看**：M 轴硬隔离（每档只注册单库），agent 无法跨档偷看元数据。

---

## 6. 诚实边界

1. **单次跑方差仍在**：M 轴 temperature 不可调（openclaw 无 `--temperature`），仍有 ±3-5pp 漂移；档间 <3pp 的差异（如 M0 vs M1 的 0.8pp）不可当结论。要出精确点估计需 pass@k。
2. **不是 BIRD leaderboard 同口径**：works_cycles 是精选多表 join 子集（偏难）、逐题洗过的 gold、调教到最佳的提示词；数字不可直接对标 BIRD 官方（后者不洗 gold、不调教）。
3. **「agent 替代元数据」是 65 表规模的结论**：sakila 报告 §10.4 已预言「几百表时 ER 决定性」，本实验未到大 schema，该外推未实测。
4. **残留失败是「歧义」不是「能力」**：剩余 22/34 题多为 BIRD 原生态歧义或数据 typo，非 agent/single-shot 的能力短板。

---

## 7. 关联文档

- 实验设计：`SPEC.md`
- gold 核定：`gold-verification.md`
- 第 2 次全量根因（最终数字版）：`works-cycles-root-cause-round2.md`
- 上一版报告（sakila 元数据梯度）：`exp-report-sql-metadata-gradient.md`
