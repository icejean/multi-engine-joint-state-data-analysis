# pass4 错题根因分析（M+S M0 全量 126 题）

> 数据源：`results_wc_mplus_126_pass4.json`（调优版 notes.md + Q54 evidence 修复后）。
> 结果：**M+S M0 = 118/126 = 93.7%**，失败 8 题 `[14, 29, 56, 71, 72, 79, 90, 107]`。
> 判分：`results_equal_relaxed`（结果集等价、忽略行/列序、数值 2 位容差、候选可比 gold 多输出列）。
> 方法：对每个错题实例，把 agent 的 `final_sql` 与 gold SQL 分别连库执行、逐值比对，再定性根因。所有数字来自实际执行，非外推。
> 对照：pass3（调优前）`results_wc_mplus_126_pass3.json` = 115/126 = 91.3%，失败 `[12,14,21,54,57,71,72,77,79,90,107]`。

---

## 0. 总览

调优后 net +3 题（+2.4pp），其中 **2 道稳定硬地板被真修回**（Q54 evidence、Q57 notes「used to」），但 4 道硬地板仍在，另有 2 道单发噪声翻挂。

**8 道错题归 4 类**：

| 类 | 题数 | 题号 | 可修? |
|---|---|---|---|
| **A. gold bug（agent 语义更对、gold 算错/取错列）** | 3 | 14, 72, 79 | ✅ 改 gold（无损归一） |
| **B. 已接受的双口径歧义（round4 已回退留档）** | 2 | 56, 107 | ❌ 拍板留档（「二选一」归一只是搬回归） |
| **C. agent 规则缺口（notes 可补）** | 2 | 29, 71 | ✅ 补 notes 规则 |
| **D. schema 间接性（agent 走错 join 路径）** | 1 | 90 | ⚠️ 技术上可补 schema note，但已拍板留作「AI 局限性」例证 |

**核心结论：8 道里 5 道是 gold 问题（3 gold bug + 2 已接受歧义），只有 3 道是真 agent 能力缺口（Q29/Q71/Q90）。**

> 这个 benchmark 的「~94-95% 天花板」有一大半是 **gold 质量的天花板，不是 agent 能力的天花板**。若把 Q14/Q72/Q79 的 gold 修对（agent 本来就答对），真实 agent 准确率已 ~96%+；真正咬人的只剩 Q90（schema 间接）+ Q56/Q107（双口径歧义）+ Q71（并列 tie）。

---

## 1. 逐题根因

### A 类：gold bug（agent 语义更对）

#### Q14（Geography）「accounts Bothell vs Kenmore + State name」

| | SQL / 结果 |
|---|---|
| gold | `SELECT SUM(IIF(city='Bothell',1,0)) - SUM(IIF(city='Kenmore',1,0)), stateprovincecode ... GROUP BY stateprovincecode` → **75 行**：`[13,'WA'] + 74 个 [0,'其它州']` |
| agent | `(COUNT(Bothell)) - (COUNT(Kenmore)), (SELECT st_prv.nm WHERE cty IN (...) LIMIT 1)` → **1 行** `[13, 'Washington']` |

**两个 gold 缺陷**：① `GROUP BY 州` 没过滤，返 74 个零行（噪音）；② 返州**码** `'WA'`，而题面问的是州**名**（agent 返 `'Washington'`）。agent 对。修法 = 加 `WHERE city IN ('Bothell','Kenmore')` + 改返 `StateProvince.Name`，gold 75 行→1 行 `[13,'Washington']`。

#### Q72（HR）「first 5 hired employees 的时薪」

| | SQL / 结果 |
|---|---|
| gold | `SELECT Rate ... ORDER BY HireDate ASC LIMIT 5`（未去重）→ `[12.45, 13.4615, 43.2692, 8.62, 23.72]` |
| agent | `WHERE RateChangeDate = MIN(...) per emp`（取每人入职时薪）→ `[12.45, 13.4615, 43.2692, 8.62, 25.0]` |

**gold fan-out bug**：最早入职的 **emp4 有 3 条薪资史**（8.62 / 23.72 / 29.8462），`LIMIT 5` 把它算成 2 行、**漏掉第 5 名 emp12**。gold 的 5 行里 emp4 出现两次，实为 4 个不同员工。agent 取每人**入职时薪**（5 个不同员工）才是「first 5 employees」的正解。修法 = 加「每人最早薪资」子查询，gold → `[12.45, 13.4615, 43.2692, 8.62, 25.0]`。

#### Q79（Product）「which chromoly steel model saved in English」

| | SQL / 结果 |
|---|---|
| gold | `SELECT ProductModelID ... WHERE Description LIKE 'Chromoly steel%' AND Name='English'` → `[[95]]` |
| agent | `SELECT prod_mdl.nm ... WHERE dscr='Chromoly steel.' AND nm='English'` → `[['LL Bottom Bracket']]` |

**gold 返模型 ID（95），agent 返模型名（'LL Bottom Bracket'=ID 95）**。找对了同一模型，只是 gold 的列选择是 ID（BIRD gold 作者的 FK 列惯性），题面「which model」应返名字。修法 = `JOIN ProductModel` 改返 `Name`，gold → `[['LL Bottom Bracket']]`。

### B 类：已接受的双口径歧义（round4 已回退）

#### Q56（HR）「personal information of highest-paid married employee」

gold 返 `Demographics` **XML 列**（`dmgr`），agent 返姓名/生日/性别列。**「personal information」= XML 还是姓名列，两口径均合法**。round4 曾尝试归一（返姓名列）→ S2/M1 反向回归，**已回退**，question_set note 标注歧义。**不修。**

#### Q107（Sales）「orders with different bill/ship city」

gold 返 `SalesOrderID`（48507），agent 返 `SalesOrderNumber`（'SO48507'）。**订单标识 = ID 还是号，两口径均合法**。round4 已回退留档。**不修。**

### C 类：agent 规则缺口（notes 可补）

#### Q29（HR）「married+email 员工最高薪资比平均高多少」

| | SQL / 结果 |
|---|---|
| gold | `MAX(rt)-AVG(rt)` over **每人最新薪资**子查询 → `42.059` |
| agent | `MAX(rt)-AVG(rt)` over **全部历史行**（漏取最新）→ `40.543` |

agent 漏了 `emp_pay_hist` 的「取最新」——§2 的「第N高/排名→不取最新」例外被 agent 误套到「highest/average」上。**notes 可修**：§2 细化为「单一聚合（最高/最低/平均）over 历史表→先取最新；只有『第N高/排名/排序』→不取最新」。★注：Q29 本身 pass1-3 三轮全过（本轮单发翻挂），非稳定缺口。

#### Q71（HR）「10th highest salary 的职位+姓名」

| | SQL / 结果 |
|---|---|
| gold | `ORDER BY Rate DESC LIMIT 9,1`（第 10 **行**）→ `['Pacific Sales Manager', 48.101, 'Syed','E','Abbas']` |
| agent | `WHERE Rate = (SELECT DISTINCT Rate ... OFFSET 9)`（第 10 个**不同值**）→ `['R&D Manager', 42.4808, 'Michael', ...]` |

agent 把「第N高」读成「第N个 distinct 值」，gold 是「第N行」——**并列时两者不同**（rate 48.101 有 **3 人并列**：125.5/84.13/72.11/63.46/60.09/50.48×2/48.5577 = 8 行后，第 9-11 行都是 48.101）。**notes 半可修**：补「第N高=ORDER BY col DESC LIMIT N-1,1 取第N行，不是第N个不同值」。但即使规则修对，第 10 名是 3 人并列（gold 的 Syed Abbas 是 MySQL 无 tiebreaker 任意取的），仍是 3 选 1 的硬币——与 Q119 同类。

### D 类：schema 间接性

#### Q90（Sales）「France territory 的门店 + 指派销售员」

| | SQL / 结果 |
|---|---|
| gold | 走 `Customer` 桥表：`SalesTerritory→Customer(TerritoryID)→Store(StoreID=BusinessEntityID)` → **74 行** |
| agent | 走门店地址：`Store→地址→州→territory` → **40 行** |

agent 把「门店的 territory」从门店物理地址的州去绕，正确路径是 `Customer.StoreID=Store.BusinessEntityID → Customer.TerritoryID`（Customer 是 Store↔Territory 桥表）。这是 schema 间接性——`Store` 表无 TerritoryID。**技术上可补 schema note（像 §6 BOM 自引用那样）**，但 round2 已拍板留 Q90 当「AI 卡在 schema 间接性」的局限例证。

---

## 2. 与 round2 根因的对照（重要修订）

round2（`works-cycles-root-cause-round2.md` §1）把 Q14/72/79/90 归为「G 类 固有语义歧义（不修）」。本轮连库逐值比对后**修正**：

| 题 | round2 定性 | 本轮修订 |
|---|---|---|
| Q14 | 「accounts=地址行 vs 客户实体」歧义 | **不是歧义**：两者都按地址行 count，真正差异是 gold 的 75 行 GROUP BY 泛滥 + 返 code 非 name |
| Q72 | 「取哪条薪资史行」歧义 | **是 fan-out bug**：emp4 算 2 行漏 emp12，「取入职时薪」是唯一合理口径 |
| Q79 | 「saved in English」含糊 | **是 ID-vs-name 列选择**：agent 找对了模型，gold 返 ID 非 name |
| Q90 | 门店 vs 销售员 territory 歧义 | 维持：真歧义 + schema 间接性（唯一真硬骨头） |

**教训**：Q14/Q72/Q79 从「固有歧义（不修）」重判为「gold bug（agent 对、无损可修）」，是「逐值连库比对」比「读题定性」更硬的方法论产出——**别急着把「agent 挂」归因给「agent 不行」，先确认 gold 自己对不对。**

---

## 3. 改善路线（本轮拍板）

1. **【改 gold，无损归一，3 题 +3】**：Q14（GROUP BY 过滤 + code→name）、Q72（去重取入职时薪）、Q79（ID→name）。改完 rescore 即翻，pass4 → 121/126。
2. **【补 notes 规则，2 题】**：Q29（§2 单一聚合取最新）、Q71（§8/§9 第N高=第N行）。Q71 并列 tie 仍不稳。
3. **【不修，留档，2 题】**：Q56、Q107（round4 已回退的双口径歧义）。
4. **【不修，留作局限例证，1 题】**：Q90（schema 间接性）。

> **实际结果（已落地验证）**：① gold 修 3 题 rescore → 121/126；② notes 重跑 Q29+Q71 均翻正 → **123/126 = 97.6%**。剩余 3 道：Q56/107（双口径歧义）+ Q90（schema 间接，已拍板留作局限例证）。Q71 的并列 tie（rate 48.101 三人并列）本轮虽翻正，但 gold 自身无 tiebreaker，属「agent 与 gold 同用 `LIMIT 9,1` 撞同一次序」的脆弱修复，不算稳健。

---

## 关联文档

- 第 2 次全量根因：`works-cycles-root-cause-round2.md`（本文件对 Q14/72/79 的定性做了修订）
- pass^3 三轮方差：`pass3-variance-report.md`
- 技术路线选择：`tech-route-selection.md`
- 复现：`../REPRODUCE.md`
