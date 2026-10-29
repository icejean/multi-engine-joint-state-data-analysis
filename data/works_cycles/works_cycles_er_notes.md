# works_cycles_er SQL 生成注意事项

> 配合 `works_cycles_er_schema.json`（数据字典 + 外键 + 列类型）一次性加载。
> 本文件是**裸 schema 和字典都看不出来、但写错就翻车**的坑，按踩坑频率排序。
> 这是库专属的注意事项；通用的 SQL 规范（输出列/去重/聚合口径等）走 Agent 的通用 prompt。

## 1. 时间态：`end_dt IS NULL` = 当前生效（SCD Type 2）

带 `end_dt` 的历史表：`bom`、`emp_dept_hist`、`prod_cst_hist`、`prod_lst_hist`、`sls_terr_hist`、`wo`。

- 「当前/在职/生效中/最新」→ **`end_dt IS NULL`**（非空 = 已失效/历史）。
- 「历史/曾经/离职/已离开」→ `end_dt IS NOT NULL`。
- 递归 CTE 的 base 和 recursive 两层都要加 `end_dt IS NULL`。

⚠️ 两个例外，别当成 SCD 用：
- `prod` 表是 `sll_end_dt`（停售）/`dscn_dt`（停产），语义不同。
- `spcl_offr.end_dt` 是「促销结束日期」（促销期 = end_dt − strt_dt），不是员工/产品的在职状态。

## 2. 历史表取最新：先 `rt_chng_dt = 每人内 MAX` 再聚合

`emp_pay_hist`（时薪，`rt_chng_dt`=调薪日期）、`emp_dept_hist`（任职）是「一人多行」历史表。

- 问「当前/最新/平均薪资·时薪·部门」→ **先取每人最新一条**（`rt_chng_dt` / 变更日期 = 该人内的 MAX）再 AVG/SUM，否则历史行重复加权。
- 问「最高/最低/平均 薪资·时薪·价格」等**单一聚合**（对历史表做 MAX/AVG/SUM/MIN）→ **同样先取最新**再聚合，别因为「最高/highest」字样误当成下面这条的「第N高」。
- 问「第 N 高/第 N 名/排名/排序」（要返回「排在第 N 位的那一行」）→ **不取最新**，直接按该列排序。

## 3. BOM 递归：层级用 `level + 1` 累加，禁止用 `bm_lvl`

`bom` 是自引用表：`ref2` = 组件编号（子），`ref3` = 装配产品编号（父）。

- 求「最深装配层级」= 递归 CTE：base 层 = 1，recursive 层 = `上一层层级 + 1`，最终 `MAX(level)`。
- **禁止用 `bm_lvl`**——它是「相对根件的全局层级」，不是「相对某产品的递归层级」，两者不是一回事。
- 求「组件/子件清单 + 层级」（要返回每个组件）时，最终 `SELECT DISTINCT 组件, 层级`——同一组件可经多条装配路径到达同一层级，会 fan-out 重复。

## 4. 大小写敏感（utf8mb4_bin）

全库排序规则 `utf8mb4_bin`，字面值必须和数据**大小写完全一致**。

- 题面给的值常是 TitleCase/小写，但数据里是全大写/另一种大小写（如 `'Vista'`、`'CARGO TRANSPORT 5'`）。
- 写 `WHERE nm = '...'` 前，用 `preview_data` 核对真实值的大小写，别照题面猜。

## 5. fan-out 去重

JOIN 到「一人/一物多行」表（`emp_pay_hist`、`emp_dept_hist`、`bom` 等）会 fan-out。

- 聚合前先「取最新」或加 `DISTINCT` / `GROUP BY 实体主键`。
- 去重对象是**实体**（人/物/订单/产品），不是值：别对返回值列（金额/名字）做 DISTINCT。
- **去重粒度 = 输出粒度**，先判断题面要的是「实体」还是「实体-明细」：
  - 问「谁/哪些人/哪些店/哪些产品」（答案是实体名字/主键）→ 按实体去重（一人/一店/一产品一行）。
  - 问「每个实体的明细」（如「每个店的 城市/州」——城市/州是**地址**属性不是店属性；订单明细行、历史记录行）→ 保留所有行，**不要** DISTINCT。

## 6. ref 列角色 + ER 的盲区

- 混淆后外键列叫 `ref1/ref2/ref3`，按外键声明顺序映射——见 schema.json 的 `foreign_keys`。
- **ER（foreign_keys）不含 `bom` 的自引用**：逻辑自引用不是声明外键，只能靠字段描述确认 `ref2`/`ref3` 角色。
- 复合外键（`count > 1`）要**全部列一起 join**，只连一列会 fan-out 翻倍（见 foreign_keys 的 `seq`/`count`）。

## 7. 语义按字面理解，尽早收敛

- 题面业务名词按「能直接命中的表字段」最字面理解，别过度联想成业务实体再绕多表 JOIN。
- 探索只为找「最小表集合」；一旦确认字段含义就写最终答案 SQL，别反复换解读、别枚举候选实体。

## 8. 排名 / top N 的 tiebreaker

`ORDER BY ... LIMIT N` 且主排序键有并列、LIMIT 正好切进并列组时，MySQL 不保证选哪几条 → 结果集合不确定、判错。

- 排名/top N 题，主排序键后面**必须加一个确定性次要键**（如 `nm` 或主键 id）做 tiebreaker。
- **「第 N 高/第 N 名」= 按主排序键排序后取第 N 行**（`ORDER BY col [DESC] LIMIT N-1,1`），**不是**「第 N 个去重后的不同值」——别写 `WHERE col = (SELECT DISTINCT col ... OFFSET N-1)`，有并列时「第 N 行」和「第 N 个不同值」会指向不同的人。
- 例：Q119「供应最多 distinct products 的 top 10」= `ORDER BY cnt DESC, nm LIMIT 10`（count=16 有 5 个 vendor、只取 4 个，必须靠 `nm` 定谁进谁出）。

## 9. 其它确定性规则

- **百分比/比例**：分母用 `COUNT(*)`（总行数），不要 `COUNT(某列)`——`COUNT(列)` 排除 NULL，分母偏小、比例偏大。
- **年份/年龄**：用 `YEAR(CURRENT_TIMESTAMP)` / `YEAR(NOW())`，不要写死年份（数据里的年份是历史值，不是当前年）。
- **「最多/最高/最…」**：`ORDER BY ... LIMIT 1` 取第一行，不要返回全部候选。
- **语义条件别写死 ID**：如「夜班」用 `shft.nm = 'Night'` 表达，不要写死 `h.ref1 = 3`。
- **「used to / 曾经属于 / 任职历史」**：这类题语义是「历史上任过哪些（含当前）」，不要加 `end_dt IS NOT NULL` 排除当前；只有明确「已离职/已离开/不再」才用 `end_dt IS NOT NULL`。
