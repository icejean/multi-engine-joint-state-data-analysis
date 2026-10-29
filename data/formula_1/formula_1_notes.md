# formula_1 SQL 生成注意事项

> 配合 `formula_1_schema.json`（数据字典 + 外键 + 列类型）一次性加载。
> 本文件是「裸 schema 和字典都看不出来、但写错就翻车」的坑，按踩坑频率排序。
> 库专属注意事项；通用 SQL 规范（输出列/去重/聚合口径等）走 Agent 的通用 prompt。

## 1. 积分/排名/胜场：standings vs results（最高频坑）

两套表都有 `pnts`（积分）/ `pstn`（名次）/ `wns`（胜场）列，含义不同：

- `rslt`（results）/ `cnstr_rslt`（constructorResults）= **单场正赛**结果（该场名次/积分/圈速等）。
- `drvr_std`（driverStandings）/ `cnstr_std`（constructorStandings）= **赛季积分榜**（累计积分/胜场/赛季排名）。

**按题面关键词选表（别按是否提到具体 race 判断）：**

| 题面关键词 | 用哪个表 |
|---|---|
| **points / score**（most/highest/0/average/top N points） | **一律 standings**（`drvr_std`/`cnstr_std`），**即使题面提到具体 race/year**（那是「该站后的累计积分」，不是单场积分） |
| **ranked N / rank**（排名第 N） | **results**（`rslt.rnk`） |
| **position / 名次 / 排位**（积分榜排位） | **standings**（`drvr_std.pstn` / `cnstr_std.pstn`） |
| **wins / 胜场** | **standings**（`drvr_std.wns` / `cnstr_std.wns`） |

反面例子：
- 「most points」→ `drvr_std`，别用 `rslt`。
- 「highest point constructor」→ `cnstr_std`，别 `SUM(cnstr_rslt)`。
- 「top 3 drivers and points in Chinese Grand Prix」→ 仍用 `drvr_std`（Chinese GP 只是时间点，取该站后的累计积分），别用 `rslt`。
- 「ranked 2」→ `rslt.rnk = 2`，别用 `drvr_std.pstn`。

补充（容易漏的别名）：
- 题面的「track number / at Nth track / Nth track」也是 **position 口径**（= 排名/名次），走 **standings**，别理解成 grid（起步位置）或 circuit（赛道）。
- 「most total wins / 胜场最多」→ 用 `standings.wns` 列，别去 results 里 COUNT 夺冠场次（`pstn_ordr = 1`）。

## 2. 圈速/时间：字符串列直接排序，别用 mlls

- 字符串时间列：`lp_tm.tm`（每圈）、`rslt.fsts_lp_tm`（最快圈速）、`pt_stp.drtn`（停站时长），格式 'M:SS.mmm'。
- 毫秒整数列：`mlls`（lp_tm/rslt/pt_stp）。

规则（gold 口径）：
- 「最快/最短」→ 字符串列 **ASC**；「最慢/longest」→ 字符串列 **DESC**。直接 `ORDER BY` 字符串列，**别用 mlls、别用 TIME_TO_SEC、别手动转秒**。
- 只有题面**明确要「milliseconds / 毫秒」**时才用 `mlls` 列（如「time in milliseconds」）。
- 列归属：「最快圈速记录」用 `rslt.fsts_lp_tm`；「每圈/第 N 圈」用 `lp_tm.tm`；「停站时长」用 `pt_stp.drtn`。
- 反例：TIME_TO_SEC('1:33.501') 会当 'HH:MM:SS' 解析成 5580，别用。

## 3. DISTINCT 与输出列

**DISTINCT 口径：**
- 问「which circuits / unique 名单 / 去重后的 location/coordinates」→ 加 `SELECT DISTINCT`（去 join fan-out 的重复行）。
- 问「count / how many」→ 直接 `COUNT(...)`，别 `COUNT(DISTINCT ...)`。
- 问「list 每条记录」（某车手参加的每场、某场每个名次、某圈速记录的每条）→ 别加 DISTINCT，保留每行。

**输出列对齐 gold：**
- 题面要几列就返回几列，别漏列（如「full name + lap time」= 名+姓+时间三列，别只返回名字）。
- 问「full name / name / who」→ 返回名+姓；题面明确要「id / driver_id / reference name」→ 返回对应 id/ref 列。
- 问「circuit 的 website / info / 信息」→ 返回 `crct.url`（赛道链接），别用 `rcs.url`（比赛链接）。

## 4. oldest / youngest 排除 NULL

`drvr.db`（出生日期）有 NULL（如 Ray Reed），问「oldest / youngest」要加 `db IS NOT NULL`，否则 NULL 排最前、被误当最老。

## 5. rate / percentage 返回百分数

「rate / percentage」按 gold 公式 `* 100`（返回百分数），不是 `* 1.0`（小数）。

## 6. 问 who / list drivers → 返回名字，别返回 id

- 问「who / list drivers / which driver / name」→ 返回 `forename + surname`（可读名字），别返回 `driverId`/`ref`（内部 id）。
- 只有题面明确要「id / driver ID / code / reference name」时才返回对应 id/ref/code 列。

## 7. url 归属：crct.url vs rcs.url

- 问「where can the introduction / information / more information about the races held on circuit X be found」这类「赛事的介绍/信息链接」→ 返回 **`crct.url`**（赛道的 wikipedia 介绍链接），**别返回 `rcs.url`**（单场比赛的详情链接）。
- 判据：题面问「在哪个 circuit 办的比赛」的信息 → 该 circuit 的 url（crct.url）。两表都有 url 列，别选错。

## 8. standings vs results 补充

- 「have 0 points in N races」→ **`cnstr_std`**（constructorStandings，`pnts`=0），别用 `cnstr_rslt`（constructorResults）。
- 「how many times X won (at circuit Y)」→ **`SUM(drvr_std.wns)`**（standings 的累计胜场，按 circuit join），别去 results 里 COUNT 夺冠场次。
- 「most winning」→ **ORDER BY `COUNT(wns)`**（赢的次数），别 `ORDER BY MAX(wns)`；但「most total wins / tallied most wins / 总胜场最多」→ **ORDER BY `wns` DESC LIMIT 1**（单条积分榜的最大累计 wns 值），别 `COUNT(wns)`。
- ⚠️ 「participated」选表不唯一（BIRD 两题相反），别一刀切：`race ID number N` → drvr_std；`named race + 国籍过滤` → rslt。具体按 evidence。
- ⚠️ 例外：「scored most points **from [具体赛道/年份区间]**」→ **`cnstr_rslt`**（constructorResults，逐场 SUM，点数可为小数如 218.5），别用 `cnstr_std`（积分榜是整数累计）。判据：题面「from + 具体 circuit/race + 年份区间」且要累加各场得分 → results；「整体积分/积分榜/最高分」→ standings。

## 9. DISTINCT / fan-out 补充

- 「have been ranked N / has the fastest lap time / born X and has fastest lap / obtain laptime < X」这类「满足某条件的每条记录」→ **保留 fan-out**（每次排名/每圈/每条记录一行），**别 DISTINCT、别去重**（gold 返回多行重复）。
- 「count how many X who obtain Y」（Y 是逐圈/逐记录条件）→ **`COUNT(*)` 记录行数**（fan-out），别 `COUNT(DISTINCT 实体)`。
- 「which year has the fastest lap time」→ **列出所有有 fastestLapTime 记录的年份**（`fsts_lp_tm IS NOT NULL`，返回全部行），**别理解成「最快的那一年」**（别 ORDER BY + LIMIT 1）。

## 10. 输出列补充

- 「when / when was ...」→ 返回 **`rcs.dt`**（日期），别返回 `ref2`（年份）。
- 「what time did ... took place」→ 返回 **`rcs.dt` + `rcs.tm`**（日期 + 时间两列），别只返回 `tm`。
- 「which driver ... give his reference name / id / code」→ 返回 **名字（frnm+srnm）+ ref/id/code 列**（如 frnm+srnm+drvr_rf），别只返回 ref 一列。
- 「which driver has the fastest lap time ... give name」→ 返回 **名字 + 时间列**（如 frnm+srnm+fsts_lp_tm），别漏掉时间列。
- 「indicate the time in milliseconds」→ 返回 **`mlls` 一列**，别加 race name、别用 tm 字符串。
- 「best lap time (min milliseconds)」→ SELECT **`mlls`** 列（毫秒值），别 SELECT `tm` 字符串（evidence 说 milliseconds 时，输出列也用 mlls）。

## 11. 字符串数值列排序（别 CAST）

- `rslt.fsts_lp_spd`（最快圈速 km/h）是 **text** 列，gold 按**字符串**排序（`ORDER BY fsts_lp_spd DESC`），**别 `CAST(... AS REAL)`**——文本字典序会把 '9…' 排最前，跟数值排序结果不同。

## 12. NULL/空串排除（时间列求极值）

- 字符串时间列（`q1/q2/q3`、`lp_tm.tm`、`rslt.fsts_lp_tm`、`rslt.tm`）有 NULL 和空串（''），求「最快/最短/earliest」要加 **`IS NOT NULL AND != ''`** 过滤，否则 NULL/空串排最前、被误当最小。
- 尤其 `qlfy.q3`：没进 Q3 的车手 q3 是 NULL，`ORDER BY q3 ASC` 会把 NULL 排最前返回错人。

## 13. fastest lap 圈号 vs 时间

- 问「which was the fastest lap / 最快圈是第几圈」→ 返回 **`fsts_lp`**（圈号，整数），别用 `fsts_lp_tm`（圈速时间字符串）。

## 14. race number / race ID

- 「race number / race ID number / 第几场 race」→ 指 **`rcs.rc_id`**（raceId，如 `rslt.ref4`），**别理解成 `rcs.rnd`**（round，赛季内的场次序号）。
