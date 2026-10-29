# BIRD dev gold 质量审计与修复记录

> 范围:formula_1(172 题)+ financial(106 题)= 278 题。
> 判分口径:`results_equal_relaxed`(同 works_cycles)。
> 审计方式:全量交叉验证(原 SQL 跑 sqlite vs 混淆 SQL 跑 MySQL 结果一致)+ 结构审计(聚合+非聚合列无 GROUP BY / 空结果 / 非确定) + 抽样数据核实。

## 汇总

| 库 | 总题 | gold 可判分 | 修复 | 排除(非确定) |
|---|---|---|---|---|
| formula_1 | 174 | 172 | 5(Q159/Q165/Q125/Q128/Q140) | 2(Q2/Q63) |
| financial | 106 | 106 | 7(Q21/Q13/Q83/Q92/Q80/Q97/Q53) | 0 |

空结果(退化 gold):**0 题**。

## 修复:formula_1 Q159

**题面**:How many wins was achieved by the oldest racer? Indicate his/her full name.

**原 gold SQL**(语义错):
```sql
SELECT SUM(T1.wins), T2.forename, T2.surname
FROM driverStandings AS T1 INNER JOIN drivers AS T2 ON T1.driverId = T2.driverId
ORDER BY T2.dob ASC LIMIT 1
```
- 结果 `[7890, 'Lewis', 'Hamilton']` —— 错在两点:
  1. `SUM(wins)` 是全表累计求和(7890 = 所有车手 wins 之和),不是"最老车手"的个人胜场;
  2. `ORDER BY dob ASC LIMIT 1` 在无 GROUP BY 时取任意行,Lewis Hamilton(1985 年生)根本不是最老。

**修复后 SQL**:
```sql
SELECT MAX(T1.wins), T2.forename, T2.surname
FROM driverStandings AS T1 INNER JOIN drivers AS T2 ON T1.driverId = T2.driverId
WHERE T2.dob = (SELECT MIN(dob) FROM drivers)
GROUP BY T2.forename, T2.surname
```
- 结果 `[0, 'Philippe', 'Étancelin']` —— 最老车手(非 NULL 最小 dob = 1896-12-28),0 胜。
- 理由:`MIN(dob)` 聚合天然忽略 NULL(数据里 Ray Reed dob=NULL);`MAX(wins)` 是生涯累计胜场(非 SUM)。
- 落地:写进 `scripts/prep_bird.py` 的 `GOLD_FIXES`,enrich 时应用、重跑自动生效。

## 修复:financial Q21

**题面**:How many clients opened their accounts in Jesenik branch were women?

**原 gold SQL**(语义错):
```sql
SELECT COUNT(T1.client_id) FROM client AS T1 INNER JOIN district AS T2
ON T1.district_id = T2.district_id WHERE T1.gender = 'F' AND T2.A2 = 'Jesenik'
```
- 结果 `26` —— 错在:用 `client.district_id`(客户**居住地** district)答「在 Jesenik **branch 开户**」,但题面指**账户开户分支**(`account.district_id`)。两者不总一致(26 vs 25)。

**修复后 SQL**(账户分支链):
```sql
SELECT COUNT(T1.client_id) FROM client AS T1 INNER JOIN disp AS T3 ON T1.client_id = T3.client_id
INNER JOIN account AS T2 ON T3.account_id = T2.account_id INNER JOIN district AS T4
ON T2.district_id = T4.district_id WHERE T1.gender = 'F' AND T4.A2 = 'Jesenik'
```
- 结果 `25`。理由:「opened accounts in branch」= account.district_id(开户分支),经 clnt→disp→acct→dstr 链;数据无 fan-out(每 client 至多一个 Jesenik 账户),COUNT 无需 DISTINCT。

## 修复:其余(gold 客观错误)

| 题 | 客观错误 | 修法(结果) |
|---|---|---|
| formula_1 Q165 | 「lap record」=最快,但 gold 没取最快(无 ORDER BY);且 time 字符串排序跨分钟会错(19:16 < 1:07) | `ORDER BY milliseconds ASC LIMIT 1` → `'1:07.411'` |
| formula_1 Q125 | 「earliest lap time」=lapTimes,但 gold 错用 pitStops 表;且问「list drivers」应返回名字 | lapTimes + `GROUP BY driverId` + `MIN(milliseconds)` + forename/surname |
| formula_1 Q128 | 「latest lap time」=lapTimes,gold 错用 pitStops;问「list drivers」应返回名字 | lapTimes + `GROUP BY driverId` + `MAX(milliseconds)` + forename/surname |
| formula_1 Q140 | 问「who」应返回名字,gold 返回 driverId | JOIN drivers + forename/surname |
| financial Q80 | 「opened accounts in the district」=账户分支,gold 用 home district | 分支链(同 Q21)→ 50.39% |
| financial Q97 | 「accounts at Prague branch」=分支,gold 用 home district | 分支链(同 Q21)→ 49.78% |
| financial Q53 | 「which districts」应返回名字(A2)非 id;且「transactions > $10,000」自然读法=单笔,gold 用 SUM(总额) | `DISTINCT A2` + `WHERE amount > 10000` |

> 另 financial Q13(LIMIT 截断 315 平局)、Q83(evidence 方向矛盾)、Q92(IDs 歧义补 evidence)已在 `GOLD_FIXES` 落地,详情见 `prep_bird.py` 的 reason 字段。

**通用原则(贯穿这批修复)**:① 问实体(who/list drivers/districts)→ 返回可读名字,别返回内部 id;② 题面自然读法优先于 gold 的机械口径(单笔 > 总额、branch > home)。这两类是 BIRD gold 标注的常见不合理之处。

## 留作硬地板(gold 口径不一致,不改)

| 题 | 原因 |
|---|---|
| financial Q44/91/98 | typ='OWNER' 该不该加、home vs branch 属主观口径(gold 无客观错,是 agent 过度过滤) |
| formula_1 Q49/113/118 | gold 正确(evidence 明确 mlls 或字符串排序),是 agent 排序错 |
| formula_1 Q110/161/166 | 复杂 CTE 时间换算,非 gold bug |

## 排除:formula_1 Q2 / Q63(非确定 gold)

| 题 | 题面 | 非确定根因 |
|---|---|---|
| Q2 | race 19 排位 Q2 最快者的 surname | `ORDER BY q2 ASC LIMIT 1`,q2 有 **6 个 NULL**(未进 Q2 的车手),NULL 排序 sqlite/MySQL 不一致 |
| Q63 | 圈数最多的一圈(车手+赛道+位置) | `ORDER BY lap DESC LIMIT 1`,最大 lap=78 有 **135 行并列**,平局取任意 |

这类是 gold 本身歧义(题面未给 tiebreaker),notes 无法修复,直接排除并标注在 `gold_errors.json`(reason = 非确定 gold)。

## 审计过、确认正确的题(曾误判)

| 题 | 题面 | 结论 |
|---|---|---|
| Q52 | 胜场最多的车手 + 其 MAX points | ✅ 正确:Schumacher(COUNT wins>=1 = 200 最多),148 = 他的 MAX(points)。曾误以为该拿 Vettel 的 397(那是"积分最多",非"胜场最多") |
| Q149 | Monaco 1980-2010 积分最多车队 | ✅ 正确:套上 1980-2010 年份过滤后 McLaren 218.5 确实是第一(曾未套年份过滤,拿 Ferrari 全历史 427.5 误判) |

## 待办(可选)

结构性审计只抓"聚合+非聚合列无 GROUP BY"这类显式错。works_cycles 曾发现 BIRD **train** 43.9% 的题有 gold 问题(修 35 处);BIRD **dev** 是评测集、疑似更干净,但若要做更深语义审计(逐题核对 WHERE/语义),可作为后续独立工作。
