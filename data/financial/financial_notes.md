# financial SQL 生成注意事项

> 配合 `financial_schema.json`（数据字典 + 外键 + 列类型）一次性加载。
> 本文件是「裸 schema 和字典都看不出来、但写错就翻车」的坑，按踩坑频率排序。
> 库专属注意事项；通用 SQL 规范（输出列/去重/聚合口径等）走 Agent 的通用 prompt。

## 1. DISTINCT / fan-out 口径

- 问 count / how many → 直接 `COUNT(...)`，别 `COUNT(DISTINCT ...)`。
- 问「list 哪些实体 / which accounts / which clients / which districts」→ `SELECT DISTINCT 实体列`（每个实体一条，去重）。
- 问「list 每条记录 / 明细 / 每条 transaction 的 id（如 account holder identification number）」→ 别 DISTINCT（fan-out，一行一条）。
- ⚠️ 分界看题面：list 实体名单（accounts/clients/districts）→ DISTINCT（Q13/Q54）；list 明细行 id（transaction 级）→ fan-out 别去重（Q57/Q59/Q94）。

## 2. 百分比/比率口径

- percentage = `CAST(SUM(布尔条件) AS DOUBLE) * 100 / COUNT(...)`。
- **别用 ROUND(..., 2)**（gold 不四舍五入）。
- 问「percentage of accounts/clients」= 按**行数 COUNT**，别用 amount 加权（别 SUM(amnt) 当分子分母）。

## 3. 表选择 ord vs trns

- household payment / withdrawal / 交易流水 → 用 **trns**（transactions），别用 **ord**（支付订单）。
- `ord` 只在题面明确「payment order / 转账指令」时用。

## 4. 输出列对齐

- gold 要几列就返回几列（如「ID and district」= 3 列），别 name/id 换错、别漏列、别多列。

## 5. 别硬编码、走 JOIN

- 别把探索时看到的 id 写死进 WHERE（如 district_id=69），用 JOIN + 语义条件表达（如 `WHERE a2='Jesenik'`）。
- 「account owner」= clnt → dsp → acct 三表链（clnt.clnt_id = dsp.ref1, dsp.ref2 = acct.accn_id），别把 clnt 直接当 account。

## 6. 方向/符号

- 「difference in A and B」= A − B（先提的先减）。例：East vs North Bohemia = `SUM(a3='east Bohemia')` − `SUM(a3='north Bohemia')`。

## 7. district 外键：home vs branch（两套外键别混）

- `clnt.ref1` = 客户**居住地**（home district）；`acct.ref1` = 账户**开户分支**（branch）。
- 问「client from district / 居住在某地」→ 用 `clnt.ref1`，直接 `clnt JOIN dstr`。
- 问「account branch / opened accounts in branch / branch 在某地」→ 用 `acct.ref1`，走 `clnt→disp→acct→dstr` 链。
- ⚠️ 题面「account holder / account / 经账户·贷款·卡找的 client 的 district」→ 用 `acct.ref1`（branch），别用 `clnt.ref1`（home）。只有明确「client 居住 / from district」才用 home。
- 「account owner number N」= 账户 N 的 owner：`acct.accn_id = N` 经 dsp 找 clnt（`dsp.ref1`），别当 `clnt_id = N`。

## 8. 输出形状

- 问「owner and disponent 两个数」→ 返回两列 `SUM(typ='OWNER'), SUM(typ='DISPONENT')`，别 `COUNT(*)` 一列。
- 问「top ten / list districts」→ 只列 `DISTINCT` 名单，别 `SUM/GROUP BY` 聚合。
- gold 要几列返回几列（如 list clients = clnt_id + accn_id 两列），别漏列、别多列。

## 9. 问 which districts / list districts → 返回名字，别返回 id

- 问「which districts / list districts / district」→ 返回 `a2`（可读名），别返回 `ref1`/`dstr_id`（内部 id）。
- 只有题面明确要「district id / Id」时才返回 id 列。

## 10. dsp.typ：OWNER vs DISPONENT

- `dsp.typ` = 'OWNER' 是账户**所有者**；= 'DISPONENT' 是**授权使用人**（非 owner）。
- **只在题面问「client 的金融活动」时加 `dsp.typ = 'OWNER'`**（如「client 的 loans」「某 client 付了多少钱」——这些要经 dsp 找该 client 作为 owner 的账户）。
- 题面问「clients in district / from region / 某地的 clients」这类**地理归属**时，用 home district（clnt.ref1）或 account branch 口径，**别加 typ 过滤**。
- 题面明确说「owner and disponent」时才两个都算。
- ⚠️「made a payment / transaction / card / loan / 地理归属」类题别加 `dsp.typ='OWNER'` 过滤——gold 不筛 OWNER（Q94/Q44 加 typ 得错数）。

## 11. percentage/count 按实体计数，别 COUNT(*)

- percentage / proportion / average 这类题，分子分母按**实体**计数，别按**行**计数。
- 分母用 `COUNT(实体主键)`（如 `COUNT(clnt_id)`），别 `COUNT(*)`——多表 join 会 fan-out 多算行，把百分比算错。
- 「clients in district / from region」这类**地理归属**直接 `clnt JOIN dstr`（home district，1:1），别绕 `dsp→acct`（account branch 会 fan-out 多算）。

## 12. 外键角色映射：ref1/ref2 是「泛化外键」，目标随表变（必读）

所有表的 ref1/ref2 都是泛化外键名，指向哪张表取决于所在表：

- trns.ref1 = acct.accn_id（交易所属账户）
- ln.ref1   = acct.accn_id（贷款所属账户）
- ord.ref1  = acct.accn_id（订单所属账户）
- dsp.ref1  = clnt.clnt_id（客户）
- dsp.ref2  = acct.accn_id（账户）
- crd.ref1  = dsp.dsp_id（发卡对应的 disposition）
- acct.ref1 = dstr.dstr_id（开户分支 branch）
- clnt.ref1 = dstr.dstr_id（居住地 home district）

铁律：账户永远是 acct.accn_id、客户永远是 clnt.clnt_id。别把 trns.ref1 当客户、别把 dsp.ref1 当账户。客户↔账户必须经 dsp 链（clnt.clnt_id = dsp.ref1 AND dsp.ref2 = acct.accn_id）。
⚠️「account holder / holder identification number / account id」这类表述 = 账户 id（trns.ref1 = acct.accn_id），不是客户 id（clnt_id）；别绕 dsp 去找 client。

## 13. 高频枚举取值（写错就翻车的坑）

- trns.oprt：'VYBER KARTOU'=信用卡取现，别跟 'VYBER'=现金取现混（同前缀）。
- trns.k_symb：'SIPO'=家庭支付(household payment)。⚠️ 有空值 ' '。
- acct.frqn：'POPLATEK MESICNE'=月度出账、'POPLATEK PO OBRATU'=每笔交易后出账。
- ln.stts：'C'/'D'=运行中(running)、'A'/'B'=已结清(finished)。「active / running / 还在还」= IN ('C','D')。
- crd.typ：'gold'=高等级卡。

## 14. dstr 三列角色：dstr_id / a2 / a3（别混）

- dstr.dstr_id = 内部 id（题面「branch location / district id」返回这个，不是 a3）。
- dstr.a2 = district_name（区/县名，细粒度 77 个）。
- dstr.a3 = region（州/地区名，粗粒度 8 个）。
- ⚠️ a3 除 'Prague' 外全小写（'north Bohemia' 不是 'North Bohemia'）。
- ⚠️ dstr.a4（居民数）是 **text** 列：排序用 `ORDER BY a4 DESC`（文本字典序，'9…' > '1…'），**别 `CAST(a4 AS SIGNED)` 转数值**（数值排序会选错区）。
- 题面「district / 区县」默认 a2；「region / 州」→ a3；「branch location / district id」→ dstr_id。若 evidence 明确指认列名，以 evidence 为准。

## 15. 聚合子查询取全集（比较基准别带主查询过滤）

- 「less/more than average / 比平均 X」这类题，比较基准的聚合子查询（AVG/SUM over）取**与主查询相同时间范围的全集**：**时间过滤（year/日期范围）要保留**，但别把主查询的**具体值过滤**（operation/type/具体 id）带进子查询。
- 例：「1998 年信用卡取现 < 平均」的基准 = 1998 年全部交易的 AVG（保留 year=1998，去掉 oprt 过滤）。

## 16. 「oldest/youngest AND highest/lowest salary」并列条件

- gold 按 **age**（oldest=brth_dt ASC / youngest=brth_dt DESC）为主排序，salary 只作 tie-break / GROUP BY 去重，**别把 salary 当独立 WHERE 过滤**（别加 a11 = MAX(a11)/MIN(a11)）。
- 结果通常 LIMIT 1（只取一个 client/account）。
