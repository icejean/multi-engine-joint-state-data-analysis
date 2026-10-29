# glm-5.2 M+S M0 · 7 题独挂根因分析

> 背景：glm-5.2 在 M+S M0 126 题里 116/126 = **92.1%**，比 deepseek-v4-flash（123/126 = 97.6%）少 7 题。
> 这 7 题 deepseek 全对、glm-5.2 独挂：**Q6 / Q37 / Q82 / Q96 / Q99 / Q111 / Q124**。
> 方法：逐题连库执行 glm/deepseek 的 final_sql 与 gold 比对，再回看 sql_history / agent_text 定位「为什么会错」。

---

## 一页结论

| 题 | 域 | 根因 | 能否修 |
|---|---|---|---|
| Q6 | Product | 末尾多跑验证 SQL（**答案其实对了**，被判错） | ✅ prompt（已验证） |
| Q96 | Product | 末尾多跑探测 SQL（**答案其实对了**，被判错） | ✅ prompt（已验证） |
| Q124 | Sales | 过度去重（`DISTINCT` 违反 notes §5）+ 末尾多跑 | ⚠️ 半修（末尾多跑已修，去重未修） |
| Q99 | BOM | 递归 CTE 缺 `DISTINCT`（fan-out 24 行 vs gold 23 行） | ✅ notes（已验证） |
| Q37 | Purchasing | `SUM(条件)/COUNT(全量)` 加权平均口径误解 | ⚠️ 难 |
| Q111 | Sales | ref 列角色 + 地址多路径（COALESCE 顺序错） | ⚠️ 难 |
| Q82 | HR | 时间态双口径（在职 vs 已离职） | ❌ 歧义≈样板 |

- **4 题可修**（3 末尾多跑 + 1 缺 DISTINCT）→ 修后 glm-5.2 = **120/126 = 95.2%**。
- **3 题难/不建议修**（1 口径误解 + 1 多路径 + 1 双口径歧义，后两者接近 pass4 已定性的「样板」性质）。

---

## 核心发现：glm-5.2 的「末尾多跑」病

3/7 独挂是同一个病：**agent 已经算出正确答案，又「多跑一条 SQL 确认/探测」，把正确答案顶掉**。
判分取「最后执行的一条 SQL」（`final_sql = sql_history[-1]`），所以末尾那条探测查询被判为答案。

| 题 | 正确答案（前面那条 SQL） | 末尾多跑的那条（被判错） |
|---|---|---|
| Q6 | `COUNT(*) ... HAVING COUNT(cmmn)>10` → **0** ✅ | `SELECT MAX(review_count)...` 验证「最多评论才 2 条」→ `[2,3]` ❌ |
| Q96 | `COUNT(*) ... WHERE sp.ref2=12 AND pc.nm='Clothing'` → **0** ✅ | `SELECT pc.nm, COUNT(*) ... GROUP BY pc.nm` 探测「促销里都有哪些类目」→ `[Components,12]` ❌ |
| Q124 | `SELECT s.nm,a.cty,sp.nm ... GROUP BY ... ORDER BY` → **701 行** ✅ | `SELECT t.nm, COUNT(*) ... HAVING cnt>1` 探测「哪家店有重复」→ 2 行 ❌ |

agent_text 里三题的最终文字答案**都是对的**（Q6 写「答案确认是 0」、Q96 写「0 个 Clothing」、Q124 写「701 行覆盖所有门店」）——纯粹是行为问题，不是能力问题。

`meta_instr` 末尾其实已有「得到答案后不要再执行任何验证/交叉核对/汇总 SQL，末尾多跑语句会导致答案被判错」，但 glm-5.2 的推理风格爱「再确认一下」，规则位置太靠后、措辞不够强，没拦住。

---

## 逐题分析

### Q6 / Q96 —— 末尾多跑（✅ 可修，已验证）
见上表。修法：把「答完即止」规则提到 meta_instr 最前、措辞升级为「严禁二次确认」。实测翻正。

### Q124 —— 过度去重（⚠️ 半修）
双层问题：
1. **末尾多跑**（已修）：第一次跑 `sql_history` 10 条、末尾 `HAVING cnt>1` 探测被判错；「答完即止」修复后降到 2 条、无探测。
2. **过度去重**（未修）：glm-5.2 条件反射加 `SELECT DISTINCT`，把 gold 的 712 行压成 701 行（多地址门店的重复行被删）。notes §5 已写「问『每个店的 城市/州』→ 保留所有行、**不要 DISTINCT**」，但 glm-5.2 没吃进去——「list every store」被它读成「一店一行」。

### Q99 —— 递归 CTE 缺 DISTINCT（✅ 可修）
- gold：`SELECT DISTINCT p.nm, bt.level ...` → 23 行。
- glm：`SELECT component_name, lvl ...`（**无 DISTINCT**）→ 24 行，多 1 行 `['Metal Sheet 5', 3]`。
- 根因：`Metal Sheet 5` 经两条装配路径到达 level 3，递归 CTE 里 fan-out 重复。glm 还硬编码了 `b.ref3 = 680`（值对，但违反「禁止硬编码」）。
- 修法：notes §3（BOM 递归）补一条「组件清单最终要 `SELECT DISTINCT 组件, 层级`——同一组件可经多路径到达同一层级」。

### Q37 —— 加权平均口径误解（⚠️ 难）
- gold：`SUM(IF(shp_mthd_id=5, ordr_qty, 0)) / COUNT(T3.ref1)` → 83.06。分子只累计 Cargo 行的数量，分母是**全部行**。
- glm：`SUM(ordr_qty) / COUNT(...) WHERE nm='CARGO TRANSPORT 5'` → 227.81。把 WHERE 同时作用到分子分母。
- evidence 已写「注意：average = SUM(OrderQty)/COUNT(所有行) 的加权平均，不是 AVG(OrderQty)」，但 glm 仍读成「过滤到 Cargo 再平均」。这是诡异口径（非 Cargo 行计进分母却计 0 分子），改 evidence 措辞边际收益不确定。

### Q111 —— ref 列角色 + 地址多路径（⚠️ 难）
- gold：`so_hdr.ref5 → addr → st_prv → cnty`（**订单收货地址**）→ 1884。
- deepseek：`cust → biz_addr(COALESCE(c.ref1, c.ref3)) → addr` → **1884**（客户实体地址，Store 优先）。
- glm：`EXISTS(... COALESCE(c.ref3, c.ref1) ...)`（客户实体地址，**Person 优先**）→ **1623**。
- 根因：`cust` 表有 **635 行 `ref1`(Store) 与 `ref3`(Person) 同时非空**（数据回填的副产物），`COALESCE` 顺序决定取哪个实体 → 顺序错就差 261 单。「客户位置」本身有 3 条合法路径（订单收货地址 / Store 地址 / Person 地址），glm 恰好选了计数不同的那条。要修得告诉它 gold 的精确路径，属题面级 overfitting。

### Q82 —— 时间态双口径（❌ 歧义≈样板）
- gold：`ORDER BY end_dt - strt_dt DESC` → **Rob Walters**（2007-12~2010-05，907 天，已离职）。
- glm：`ORDER BY DATEDIFF(COALESCE(end_dt, NOW()), strt_dt)` → **Roberto Tamburello**（2007-11 至今在职，6907 天）。
- 根因：gold 用 `end_dt - strt_dt`，在职员工 `end_dt IS NULL` → 相减得 NULL → 排序被排到末尾（**被排除**）。glm 用 `COALESCE(end_dt, NOW())` 把在职员工按「至今」计入。
- 判读：题面「has been in the department the longest」自然读法**包含在职**（Roberto 待了 18 年 > Rob 的 2.5 年），glm 的答案其实**更符合语义**。gold 的 `end_dt - strt_dt` 是 BIRD 原版口径（没处理 NULL），属于「两合法口径二选一」——与 Q56/Q107 同类，建议**留作样板或改 gold**，不硬修。

---

## 修法清单 + 验证结果

1. **meta_instr「答完即止」提前 + 升级**（修 Q6/Q96/Q124 的末尾多跑）：把「最终答案」段提到 meta_instr 最前，措辞改为——
   > ★【最高优先级】判分只取你**最后执行的一条 SQL**。一旦执行了最终答案 SQL 并看到结果，就**立即停止**，严禁再执行任何 SQL（验证、交叉核对、GROUP BY 探测、COUNT 试数、查重复、查明细都不行）。任何「确认一下」的后缀查询都会把正确答案顶掉、被判错。

2. **notes.md §3 补「递归 CTE 组件清单 DISTINCT」**（修 Q99）：
   > 求「组件/子件清单 + 层级」时，最终 `SELECT DISTINCT 组件, 层级`——同一组件可经多条装配路径到达同一层级，会 fan-out 重复。

### 实测（定向重跑 Q6/Q96/Q124/Q99，glm-5.2，硬隔离 M0）

- ✅ **Q6 / Q96 / Q99 翻正**（结果文件 `results_wc_mplus_glm52_fix4.json`）。
- ❌ **Q124 未翻正**：末尾多跑已修（12 轮→2 轮），但 glm-5.2 条件反射加 `SELECT DISTINCT` → 701 行 vs gold 712 行（过度去重）。
- 净收益 **3 题**：glm-5.2 从 116/126 → **119/126 = 94.4%**（放宽口径）。
- 修 Q124 需再强化 notes §5（「list every X 的 城市/州」= 一店一行 vs 一店一地址一行 的歧义，gold 选后者），但边际收益趋近于题面级 overfitting。

---

## 结论

- glm-5.2 的 7 题独挂里，**3 题是行为/规则问题、已翻正**（Q6/Q96 末尾多跑 + Q99 缺 DISTINCT），改 prompt/notes 即可。
- **1 题（Q124）半修**：末尾多跑修好了，剩「过度去重」——glm-5.2 爱加 DISTINCT，踩 notes §5「每店城市/州保留所有行」的规则。
- **3 题是真实语义差异**（Q37 口径 / Q82 双口径歧义 / Q111 多路径 ref 角色），是 glm-5.2 与 deepseek 的**能力/口径差距的真实下限**。
- 修复后 glm-5.2（94.4%）仍低于 deepseek（97.6%），差距收窄到 3 题（Q37/Q82/Q111）+ Q124 去重 + 3 共享样板（Q56/Q90/Q107）。
