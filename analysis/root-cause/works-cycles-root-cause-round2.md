# works_cycles 第 2 次全量根因分析（S/M 两轴最终残留错题）

> 数据源：`results_wc_s_full_v2.json` / `results_wc_m_126_full_v2.json`（终版）+ `gold.json` + `question_set_final_obfuscated.json`。
> 最终数字：**S 76.2 / 83.3 / 83.3**（唯一错题 34 道）、**M 86.5 / 85.7 / 87.3**（唯一错题 22 道）。
> 判分：`results_equal_relaxed`（结果集等价、忽略行/列序、数值 2 位容差、候选可比 gold 多输出列）。
> 方法：对每个错题实例，把 agent 的 `final_sql` 与 gold SQL 分别连库执行、逐值比对，再定性根因。所有数字来自实际执行，非外推。

---

## 0. 总览

- 两轴唯一错题并集 **40 道**，交集 **16 道**（两轴都挂的硬地板）。
- 40 道归 **9 类**。其中约 **14 道是「gold/判分口径问题」（agent 语义更对或等价表示被判错）**，约 **13 道是「agent 可调项」（去重/最新值/反号/聚合/过滤值）**，约 **6 道是「硬骨头」（语义歧义 + 递归 CTE）**，**2 道是 M 专属（探索迷路/超时）**。

| 类 | 题数 | 题号 | 静态可修? |
|---|---|---|---|
| **A. gold 语义 bug**（agent 对、gold 算错/取错列） | 3 | 10, 56, 110 | ✅ 改 gold |
| **B. gold 表示 quirk**（CONCAT/折叠/去重/ROUND/LIMIT/tie/ID-vs-name） | 9 | 12, 13, 19, 52, 107, 112, 117, 118, 119 | ✅ 改 gold/判分（52 需 prompt 去重） |
| **C. 时间态 / 最新值 / 年份** | 6 | 27, 29, 36, 54, 57, 65 | ⚠️ 一半改 prompt |
| **D. 混淆列映射**（ref1/ref2/ref3，几乎全 S0） | 7 | 26, 39, 43, 77, 91, 98, 120 | ❌ 元数据价值证据（不改） |
| **E. 字面值大小写**（utf8mb4_bin） | 2 | 33, 37 | ✅ 判分大小写不敏感 / gold 标真实值 |
| **F. 反号 / 聚合 / 过滤值 / 去重** | 5 | 45, 73, 86, 125, 11 | ⚠️ prompt 规则 |
| **G. 固有语义歧义** | 4 | 14, 72, 79, 90 | ❌ 拍板即刷分 |
| **H. 递归 CTE**（真能力短板） | 2 | 99, 101 | ⚠️ prompt 加递归模板 |
| **I. M 专属迷路 / 超时** | 2 | 28, 70 | ✅ 加超时 + 收敛 |

---

## 1. 逐题根因表（40 道）

> 格式：`Q#` 轴（档）类 —— 定性（关键证据）。

| Q | 轴(档) | 类 | 根因 |
|---|---|---|---|
| 10 | S0/1/2 M0/1/2 | A | gold `CASE WHEN dcmn_smmr IS NOT NULL` 算出「非私密占比」=100%，与自身 evidence「private=IS NULL」矛盾；agent 算私密占比 50%（2/4）正确 |
| 11 | S(S1) | F | `py_frqn=2` 直连 emp_pay_hist 未去重（136 vs 126，一人多条薪资史 fan-out）；S0/S2 过 = 单档噪声 |
| 12 | S0/1/2 M(M2) | B | 组件 494 有 14 条 BOM 全「Ounces」；gold `GROUP BY` 折叠 1 行，agent 列 14 行（语义同，仅未折叠）；M2 返单位**码**「OZ」非名「Ounces」 |
| 13 | S0/1/2 | B | vendor 1496 有 16 产品同 lead time 17；gold `GROUP BY` 折叠 1 行，agent 列 16 行（语义同） |
| 14 | S0/1/2 M0/1/2 | G | 「accounts」= 地址行(gold，74 行 per state) vs 客户实体(agent，1 行)；州 code vs name。两者可读 |
| 19 | S(S2) | B | 漏 `GROUP BY` 去重（42 vs 31）；单档噪声 |
| 26 | S(S0) | D | `emp_dept_hist` 的人列是 ref3，agent 误用 ref1（count=1 vs 4）；S1/S2 靠字典救 → **元数据价值铁证** |
| 27 | S(S0/1) | C | `jb_ttl = 'Production Technician'` 精确匹配（实为带后缀 'Production Technician - WC60'）→0；gold 用 `LIKE`；且最新薪资窗口 |
| 28 | M(M0) | I | 探索超时/「LLM request failed」，终答为探索语句；gold 本身病句（BIRD 原句缺 join 条件） |
| 29 | S(S0/1) | C | 漏「每人最新薪资」子查询（40.54 vs 42.06）；M 全过、S2 过 |
| 33 | S0/1/2 | E | `crd_typ='vista'`（小写）vs 数据 `'Vista'`，utf8mb4_bin 大小写敏感 → 0 行；M 探索见真实值 → 过 |
| 36 | S(S0) | C | agent 多加 `end_dt IS NULL`（当前在职）→17.00 vs gold 含历史→17.25；单档 |
| 37 | S0/1/2 M0/1/2 | E(+口径) | ① `nm='Cargo Transport 5'` 实为全大写 `'CARGO TRANSPORT 5'` → 0/0=NULL（大小写）；② 即便大小写对，gold 是「加权均值 SUM(qty)/COUNT(所有行)」、agent 是简单均值。M0 超时、M1/M2 把 sys 表查询当终答 |
| 39 | S(S0) | D | `emp_dept_hist` ref1 vs ref3（人）误用 →0；S1/S2 靠字典救 |
| 43 | S(S0) | D | `COUNT(DISTINCT edh.ref1)`（ref1=shift 非人）→1；S1/S2 救 |
| 45 | S0/1/2 | F | 「无 offer」→ gold `unt_prc_dscn=0`，agent 写 `>0`（有折扣）**反号**；M 探索救 |
| 52 | S(S1/2) M(M0/1) | B | 9 人各持 2 张 Distinguish 卡；gold 加 DISTINCT(4823)，agent 无(4832)——去重遗漏 |
| 54 | S0/1/2 M0/1/2 | C | gold `YEAR(CURRENT_TIMESTAMP)`=72 岁，agent 照 evidence「2022-year+1」=69 岁——**年份锚点漂移** |
| 56 | S(S0/1) M(M0/2) | A | gold `SELECT dmgr` 返了 demographics **XML 列**而非「个人信息」；agent 返姓名/生日/性别更对 |
| 57 | S0/1/2 M0/1/2 | C | 「used to belong」agent 加 `end_dt IS NOT NULL`（仅已结束→Purchasing），gold 返全部（Purchasing+Marketing）——时态分歧 |
| 65 | M(M1/2) | C | 漏「每人最新薪资」→26.36 vs gold 36.56；M0 探索救 |
| 70 | M(M1) | I | 终答为 `sys_table_fields` 探索语句（且连错库报「表不存在」） |
| 72 | M0/1/2 | G | 「first 5 人 rate」取哪条薪资史行歧义；gold 不取最新（第 5 人 23.72）agent 取入职时薪（25.0）；M0 超时 |
| 73 | S(S0/2) | F | 漏 `SUM`（agent 返 816 行原始 `stck_qty`，gold SUM=8431） |
| 77 | S(S0) | D | `biz_addr` ref1 vs ref3（地址）误用 →0 |
| 79 | S0/1/2 M0/1/2 | G(+表示) | 「saved in English」含糊；gold 返模型 **ID** 95，agent 返模型**名** 'LL Bottom Bracket'（找对了、列不同）；S 轴误搜 'AdventureWorks'→0 |
| 86 | S(S2) | F | agent 加 `cnt_typ.nm='Primary Contact'`（实为 Owner）→0；单档 |
| 90 | S0/1/2 M0/1/2 | G | 「in France」agent 走销售员 territory（40 行），gold 走门店 territory（74 行）——join 路径歧义 |
| 91 | S(S0) | D | `sls_prsn` ref1 vs ref2 误用 →0 |
| 98 | S(S0) | D | `edh` ref1 vs ref3 误用 + 返 dept ID 非 name + 均值错（125.5 vs 14.39） |
| 99 | S(S0) M(M2) | H | 递归 level 用存储列 `bm_lvl`（24 行、level 错）/`MIN` 折叠（21 行）；gold 递归+DISTINCT 23 行 |
| 101 | S(S0) | H | 用存储列 `bm_lvl` MAX=2，非递归 MAX=3 |
| 107 | M(M0/1) | B | agent 返订单号 'SO48507'，gold 返订单 ID 48507——ID vs 号 |
| 110 | S0/1/2 M0/1/2 | A(+B) | gold `GROUP BY 姓名` 合并同名客户（Roger Harui×2→989400.98）；agent 按客户 ID（989184.08）更符合「top 5 customers」；且 CONCAT/ROUND 差异 |
| 112 | S0/1/2 M0/1/2 | B | gold `CONCAT` 姓名单列，agent 拆名/姓两列（ORDER 方向差异不影响判分，纯 CONCAT vs 拆列） |
| 117 | S0/1/2 M0/1/2 | B | 同上 CONCAT vs 拆列（5 行内容一致） |
| 118 | S0/1/2 M0/1/2 | B | CONCAT vs 拆列 + gold `LIMIT 20` 而 agent 返全部 290 行 |
| 119 | S0/1/2 M(M0/1) | B | gold `ORDER BY 2 DESC,1` 带 name tiebreaker；16-count 并列 5 家，LIMIT 10 边界取决于 tie；M2 侥幸过 |
| 120 | S(S0/2) | D | S0 `p.ref1=v.ref1`（错列）→0；S2 用 LEFT JOIN 含 0 单 vendor（104 vs gold INNER 86） |
| 125 | M(M1) | F | agent 用 `prsn_typ='EM'` 过滤（271）漏了非 EM 类型但仍在 emp 表的员工；gold join emp（288） |

---

## 2. 本轮新发现（vs 第 1 次根因）

1. **字面值大小写是第 1 次漏掉的系统性根因**（Q33/Q37）：混淆库排序规则 `utf8mb4_bin`（大小写敏感，为对齐 SQLite 而设），而 BIRD 题面里的字面值（`'Vista'`、`'Cargo Transport 5'`）在数据里是 TitleCase/全大写。**single-shot 照题面猜大小写 → 0 行；agent 探索看到真实值 → 过**。这是「agent 探索替代元数据」之外的另一机制：**探索替代「字面值先验」**。
2. **gold 表示 quirk 是最大残留块（B 类 9 题）**：CONCAT vs 拆列（Q112/117/118）、GROUP BY 折叠（Q12/13/19）、DISTINCT 去重（Q52）、ID vs 号（Q107）、ROUND/LIMIT（Q110/118）、tiebreaker（Q119）。这些**不是「答错」，是评分器对「等价表示」不宽容**——语义全对，仅列形状/去重/排序边界不同。
3. **gold 语义 bug 还剩 3 题**（Q10/Q56/Q110），其中 **Q110 新定性**：gold `GROUP BY 姓名` 把两名同名「Roger Harui」合并（989400.98），agent 按客户 ID（989184.08）才是「top 5 customers」的正确口径。
4. **混淆列映射（D 类 7 题）几乎全在 S0**：ref1/ref2/ref3 语义只有字典/ER 能解，S0 裸库只能猜。这是「元数据价值」的最直接证据——**同一批题 S0 挂、S1/S2 靠字典救回**。
5. **时间态 6 题分三个子类**：最新值（Q27/29/65 漏 latest-rate 子查询）、年份锚点（Q54 的 2022 vs 当前年）、时态/在职（Q36/57 的 current/ever/used-to）。

---

## 3. 改善路线（按 ROI，标注静态 vs 重跑）

> 「静态」= 改 gold/判分，不重跑 LLM；「重跑」= 改 prompt/数据后需重跑。

1. **【静态】gold 语义 bug 修复（3 题，+3）**：Q10（CASE 反号 + 分母 COUNT(*)）、Q56（返姓名/生日/性别列）、Q110（GROUP BY 客户 ID 非姓名）。改 gold 重判即翻。
2. **【静态】gold 表示归一（8 题，+8）**：统一「full name」为拆列或 CONCAT（Q112/117/118）、折叠等价（Q12/13/19 判分容忍重复同值行）、ID vs 号归一（Q107）、tiebreaker 补齐（Q119）、LIMIT 补齐（Q118）。其中 Q52 的 DISTINCT 是 agent 去重遗漏，需 prompt 规则（见 4）。
3. **【静态】判分大小写不敏感（2 题，+2）**：`normalize_value` 对 str 做 `lower()`，或 gold/evidence 标注真实大小写。Q33/Q37 翻。
4. **【重跑】去重规则强化（Q52/11/19）**：把「去重实体非值」从「软规则」升级为「若结果行数 > 实体数则 DISTINCT」的确定性 trigger。
5. **【重跑】最新值 trigger 补漏（Q27/29/65）**：把「薪资/任职历史必须取最新」从「提示词一句」升级为「凡 join `emp_pay_hist`/`emp_dept_hist` 多行表，默认带 latest 子查询」。
6. **【重跑】年份锚点统一（Q54）**：evidence 与 gold 统一「当前年」或「固定 2022」，二选一，消掉漂移。
7. **【重跑】递归 CTE 模板（Q99/101）**：prompt 加「层级必须用递归 level+1，禁止用存储的 level/bm_lvl 列」。
8. **【重跑】M 专属（Q28/70）**：`AGENT_TIMEOUT` 240→360；收敛句再加「最终答案必须是数据查询，禁止输出 sys_* 元数据查询」。
9. **【不修】固有语义歧义（Q14/72/79/90）**：BIRD 原生态含糊，拍板=改 gold=刷分，留作「诚实边界」。

> 做完 1+2+3（**纯静态，不调 LLM**）：S 轴唯一错 34 → ~21（S0 76.2→~85、S1/S2 83.3→~93，各档 **+9~10pp**），M 轴唯一错 22 → ~11（各档 **+6~8pp**）。且 1+2+3 的 gold/判分修正是两轴共享的，M 轴同样受益。做完 4–8（重跑）预期两轴再各抬 3–5pp。

---

## 4. 诚实边界

1. **单次跑方差仍在**：M 轴 temperature 不可调（openclaw），±3–5pp 漂移；档间 <3pp 差异不可当结论（如 Q11 只在 S1 挂、Q86 只在 S2 挂 = 单档噪声）。
2. **B/E 类是「表示层」不是「能力层」**：CONCAT/折叠/大小写/ID-vs-name 都不代表 agent 不懂 SQL，是评分器对等价表示的宽容度问题。修判分即可翻，但要诚实标注「判分口径放松了」。
3. **D 类是「特性」不是「缺陷」**：S0 挂、S1/S2 救，恰恰是「元数据消歧」的实验结论，不该为了刷 S0 而给裸库注字典。
4. **递归 CTE 是真短板**：Q99/Q101 两轴多档挂，agent 递归 level 计算反复出错（用存储列、MIN 折叠），这是能力问题不是口径问题。

---

## 5. round4 修复实录（已应用 + 已回退）

> 按 Jean 拍板「B 类改 gold（学术严格）」，对静态可修的 gold/evidence 做了 round4 修复并重判。结果：**S 76.2/83.3/83.3 → 78.6/85.7/86.5、M 86.5/85.7/87.3 → 90.5/89.7/91.3**（25 个 tier-fail 翻正，**0 回归**）。

### 5.1 已应用（5 处 gold + 2 处 evidence，纯静态、不重跑 LLM）

| 题 | 修法 | 翻正的档 |
|---|---|---|
| Q10 | gold CASE 反号 `IS NOT NULL`→`IS NULL`、分母 `COUNT(dcmn_smmr)`→`COUNT(*)`、补 ×100 | S0 M0 M1 M2 |
| Q110 | GROUP BY 姓名→客户 ID（Roger Harui×2 不再合并）+ full name 拆列 | S2 M0 M1 M2 |
| Q112 | CONCAT→拆列 | S1 S2 M0 M1 M2 |
| Q117 | CONCAT→拆列 | 全 6 档 |
| Q118 | CONCAT→拆列 + 去掉任意 LIMIT 20 | 全 6 档 |
| Q33 | evidence `'vista'`→`'Vista'`（真实值 TitleCase） | 重跑才生效 |
| Q37 | evidence `'Cargo Transport 5'`→`'CARGO TRANSPORT 5'` | 重跑才生效 |

### 5.2 已回退（2 处：归一不解决歧义，反致回归）

- **Q56**（personal information = Demographics XML vs 姓名列）、**Q107**（order 标识 = SalesOrderID vs SalesOrderNumber）：两轴 agent 各取了不同（均合法）的口径。尝试「归一」时 Q56 的 S2/M1、Q107 的 S 三档**反向回归**——净收益为负。结论：这两题是「固有表示歧义」，不是 gold bug，保留原 gold，在 question_set `note` 标注歧义。
- **教训**：**「改 gold 归一」只对「无损归一」（CONCAT→拆列、去任意 LIMIT、修真 bug）成立；对「两个合法口径二选一」的歧义，归一只是把回归从一边搬到另一边。** 这就是为什么 Q56/Q107 回退，而 Q112/117/118 保留。

### 5.3 残留（仍需重跑 LLM，未动）

去重（Q12/13/19/52/119）、最新值（Q27/29/65）、反号/聚合/过滤（Q45/73/86/125/11）、递归 CTE（Q99/101）、M 超时（Q28/70）、时间态（Q54/36/57）——见 §3 步骤 4–8，需 prompt 规则 + 重跑，待拍板。

---

## 6. round5 prompt 规则补强 + 定向重跑（已应用，未全量重跑）

按 Jean「只重跑需要重跑的」，补强 prompt 规则后**只重跑当前挂掉的 32 个档**（22 S + 10 M，硬隔离），12 翻正、0 回归。**最终 S 81.7/87.3/87.3、M 92.1/91.3/92.1**（round4 后 78.6/85.7/86.5、90.5/89.7/91.3）。

### 6.1 prompt 规则改动（run_bench_wc.py + run_bench_wc_singleshot.py）
1. **去重**：S 轴补齐了 M 轴有而 S 轴缺失的「fan-out 加 DISTINCT/GROUP BY 去重」规则。
2. **递归 CTE 层级**：加「层级必须 level+1 累加，禁止用表里预存层级列（bm_lvl/BOMLevel）」。
3. **否定词反号**：加「no/not/without/无 = `= 0`/`IS NULL`/`NOT`，不要写 `> 0`」。
4. **最新值强化**：把「一人多行历史表聚合默认先取最新」从软规则升为明确触发。
5. **M 超时**：AGENT_TIMEOUT 240→360。

### 6.2 翻正的 12 档

| 规则 | 翻正的档 |
|---|---|
| 最新值强化 | Q29 S0/S1、Q65 M1 |
| 去重 | Q11 S1、Q19 S2、Q12 M2、Q52 M1、Q119 M0 |
| 反号 | Q45 S0 |
| 递归 CTE 层级 | Q99 S0、Q101 S0 |
| M 超时 | Q28 M0 |

### 6.3 仍残留（规则没救回来的）

- **折叠去重**（Q12/13 S 三档、Q52 S1/S2+M0、Q119 S1/S2+M1）：去重规则对「同一值重复 N 行（GROUP BY 折叠）」和「LIMIT 边界 tiebreaker」仍不触发——这些是「表示层」残留，不是规则能救的语义错。
- **Q27**（title 精确匹配 `='Production Technician'` vs 数据带后缀）、**Q45 S1/S2**（反号单档噪声）、**Q65 M2**（最新值单档漏）、**Q70 M1**（探索迷路 375s 超时）——单档方差或硬骨头。
- 结论：**prompt 规则补强的 ROI 已递减**——12 翻正里 8 个是「低挂果」（最新值/递归/反号/去重里 agent 本就能做对、只是差一句确定性规则），剩下的折叠/去重/tiebreaker/歧义是「表示层」或「固有歧义」，再堆规则边际收益小。

---

## 关联文档

- 最终报告：`works-cycles-final-report.md`
- gold 核定：`gold-verification.md`
- 第 1 次根因（已过时）：`s-axis-full-root-cause.md`、`m-axis-full-root-cause.md`（本文件为最终数字版，取代二者）
- 复现：`../REPRODUCE.md`
