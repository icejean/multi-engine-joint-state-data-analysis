> ⚠️ 本文为第 1 次根因（中间结果，S0=61.1/73.8/68.3、M0=75.4/71.4/76.2 已过时）。
> 最终数字版见 works-cycles-root-cause-round2.md（S 76.2/83.3/83.3、M 86.5/85.7/87.3 的逐题定性）。

# S 轴全量根因分析（126 题 × S0/S1/S2，evidence+prompt 修复后 v2）

> 数据源：`results_wc_s_full_v2.json`。当前 S0=61.1 / S1=73.8 / S2=68.3。
> 本文逐题归类全部 55 道唯一失败题，并给出剩余改善点。

---

## 0. 失败总览

- 唯一失败题 **55 道**：三档全挂 **29**、两档 **9**、单档 **17**（单档多为 S0，靠元数据救回）。
- 结论先行：55 道失败里，**~20 道是「gold/evidence 自身的 bug 或口径怪癖」**（agent 的答案反而更对），**~6 道是固有语义歧义**，其余是输出形状/时间态/最新值的可调项。

---

## 1. 五大根因

### ① gold 口径 bug（agent 对、gold 错/怪）—— 8 题

| 题 | gold 的怪癖 | agent 的做法（更合理） |
|---|---|---|
| Q13 | 用 `GROUP BY` 把同一 vendor 的多产品行折叠成 1 行 | 直接列全部行（无 GROUP BY）→ 行数不符 |
| Q37 | 「平均」= `SUM(Cargo5 qty)/COUNT(全部行)`（加权） | `AVG(qty WHERE Cargo5)`（更自然的均值） |
| Q38 | 「on sale」= 有促销记录 `spcl_offr` | evidence 明说 `SellStartDate NOT NULL`，agent 照 evidence |
| Q72 | 前 5 名不取最新薪资（历史行直接排） | agent 取每人最新薪资（更对） |
| Q73 | 「库存量」用 `COUNT(*)`（数行数） | agent 用 `SUM(stck_qty)`（真·库存量） |
| Q74 | 题问「总额」却返 `unt_prc`（单价） | agent 算 `SUM(ttl_due)`（真·总额） |
| Q110 | 「customer」= 仅自然人（`ref3 IS NOT NULL`） | agent 自然人+门店都算 |
| Q119 | `ORDER BY 2 DESC, 1`（带 name tiebreaker） | agent 只 `ORDER BY count DESC` → LIMIT 10 边界 tie |

### ② evidence 仍与 gold/data 冲突（evidence 第二波 bug）—— 6 题

| 题 | evidence 说 | 实际/gold |
|---|---|---|
| Q22 | 最低评分 = `Rating = 1` | 数据里最低评分不是 1（gold 用子查询 MIN） |
| Q29 | EmailPromotion = `1` | gold 用 `= 2` |
| Q36 | 工龄 = `2022 − year(hire)` | gold 用 `CURRENT_TIMESTAMP`（2026，随年份漂移） |
| Q39 | 题面/evidence「Sheela **Ward**」 | 数据里是「Sheela **Word**」（BIRD 原题 typo） |
| Q41 | 「Information **Service**」 | 数据里是「Information **Services**」（缺 s） |
| Q54 | 年龄 = `2022 − year + 1` | gold 用 `CURRENT_TIMESTAMP`（漂移） |

### ③ 输出形状：CONCAT / 拆列 / fan-out —— 6 题

- **CONCAT vs 拆列**：Q71（gold 要 3 列，agent CONCAT）；Q112/Q117/Q118（gold 用 `CONCAT(name)` 单列，agent 拆成两列，且 Q112/Q117/Q118 都多 join 了 `emp`）。
- **fan-out / DISTINCT**：Q33（gold `COUNT` 数行含 fan-out，agent `COUNT DISTINCT`）、Q50（agent 加了 DISTINCT，gold 无）。

### ④ 时间态/最新值/输出列的过度应用 —— 3 题

- Q30（「work shift」gold 要 `strt_tm,end_tm` 时段，agent 给 `nm` 名字 + 加 `end_dt IS NULL`）；
- Q57（「used to belong to」agent 加 `end_dt IS NOT NULL`，gold 无过滤）；
- Q79（`dscr LIKE 'Chromoly steel%'` 描述匹配没做对）。

### ⑤ 固有语义歧义（硬骨头，短时修不动）—— 6 题

- Q10（「private document」= summary IS NULL 还是 IS NOT NULL，正反都能读）；
- Q14（「accounts」= 地址行数 vs 客户实体，evidence 也压不住）；
- Q15（「how many times」= 比值 vs 百分比 `*100`）；
- Q45（「no offer」= discount `=0` 还是 `<>0`，agent 反复反号）；
- Q90（双重歧义 + 间接 schema，两轴 6 格全挂，见 q90-root-cause-analysis.md）；
- Q12（agent SQL 与 gold 几乎逐字一致却判错，需单独复查）。

---

## 2. 剩余改善点（按 ROI 排序）

1. **[gold 核定 round 2]（~8 题，静态改 gold 即翻）**：Q13/Q37/Q38/Q72/Q73/Q74/Q110/Q119。这是最干净的一批——agent 的答案语义更对，gold 本身口径有问题，改 gold 后重判即恢复，无需重跑 LLM。
2. **[evidence 核定 round 2]（~6 题）**：Q22/Q29/Q36/Q39/Q41/Q54。继续对齐 evidence 与 fixed-gold/数据（Q22 的 Rating≠1、Q29 的 =2、Q36/Q54 的年份漂移、Q39/Q41 的题面 typo）。
3. **[gold 归一：CONCAT→拆列 + 去 fan-out]（~6 题）**：Q71/Q112/Q117/Q118（统一「full name」表示，去掉 spurious emp join 的判分容忍）、Q33/Q50（判分对 fan-out 的 DISTINCT 等价放宽）。
4. **[prompt 微调]（~3 题）**：Q30/Q57/Q79——「work shift 要时段不要名字」「used to 别强加 end_dt」「描述 LIKE 匹配」。

> 做完 1+2+3（纯静态，不调 LLM）预期 S 轴可再 +10~13pp（S0/S1/S2 各自往上抬），且这些修正对 M 轴同样生效（gold/evidence 是两轴共享的）。

---

## 3. 诚实边界（写进报告）

1. **S 轴 single-shot 有 ~31% 逐格翻转噪声**：单次跑的 S0/S1/S2 绝对 pp 之间，差值 < ~5pp 不可当结论（S1>S2 的 5.5pp 里约 4pp 是噪声，见 `m-axis-root-cause-analysis.md` §3）。
2. **「哪档高哪档低」要 pass@k 才能定**：建议抽 S0/S1/S2 各 20 题跑 3 次，量化翻转率，给每个数字一个方差下界。
3. **gold/evidence 还在「洗」**：本文 ① ② 表明 gold/evidence 仍需第二轮核定（BIRD 原题标注质量 ~44% 的问题率，第一轮 gold-verification 修了 35 处，这里又暴露 ~14 处）。

关联：`gold-verification.md`、`s-axis-root-cause-analysis.md`（26 题版）、`m-axis-root-cause-analysis.md`、`q90-root-cause-analysis.md`。
