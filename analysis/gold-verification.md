# works_cycles（BIRD AdventureWorks）gold 核定与修改报告

> 本文档记录对 `data/works_cycles/question_set_final(_obfuscated).json` 中 gold SQL 的逐题核定过程与全部修改。
> 题集最终 **126 道题（96 官方 BIRD + 30 自拟）**——原 98 道官方题中有 2 道（Q88/Q92）因 ill-posed 已删除（详见 §3）。
> 目的：保证评测基线（gold）本身正确——因为 gold 一旦有错，会同时污染「准确率」与「元数据边际收益 Δ₄」两个信号。

---

## 1. 背景：为什么要逐题核 gold

works_cycles 是 BIRD 官方 train 集中微软 AdventureWorks（65 表 / ~74 万行）的子集。我们对 BIRD 官方 474 题筛选出 98 题（73 道多表 join + 27 道富特征 1-join，去掉 2 道 PersonPhone bug 题），再加 30 道自拟题补足 BOM 递归 / Sales 长链等缺口。

在跑 S/M 两轴（single-shot vs agent）评测时，我们发现「失败题」里混着大量 **gold 本身错误** 的情况——即 agent 答对了、gold 反而是错的。这迫使我们逐题核 gold。核完的结论是：

> **98 道官方题里，43 道（43.9%）的 gold 或题面存在需要修改的问题，其中 29 道是明确的「gold bug」（gold 结果错）。** 这个错误率远超「权威基准」应有的水平，值得所有使用 BIRD 的人警惕（详见 §8）。

---

## 2. 核验方法

对每一道题，依次做以下检查：

1. **读题面 + evidence 字段**：确定 BIRD 原始意图（evidence 常写死「MakeFlag=1 表示自制」这类口径）。
2. **读 gold SQL**：对照 obfuscation_map 还原列名，检查 JOIN 链、过滤条件、聚合口径、输出列。
3. **执行 gold SQL**：拿结果集，与「题面语义 + 数据事实」比对。
4. **交叉验证**：用独立 SQL 从数据里重新算一遍「正确答案」，确认 gold 是否一致。

判「错」的准绳：**gold 的结果 / 输出形状 / 语义口径与题面要求不一致**（哪怕和 evidence 一致，只要 evidence 本身写错也算）。凡判错的，一律在 `question_set_final(_obfuscated).json` 的 `note` 字段留 provenance，并同步修正 `SQL`（原名）与 `SQL_obfuscated`（混淆名）两处。

---

## 3. 结果总览

| 指标 | 数值 |
|---|---|
| 题集总题数（评分集） | **126**（96 官方 + 30 自拟） |
| 从 BIRD 官方 98 题中删除的 ill-posed 题 | 2 道（Q88/Q92，答案恒空/0） |
| 带 note 的题 | **52**（41 官方 + 11 自拟） |
| 官方题 gold 问题率（按原 98 题计） | **43 / 98 = 43.9%** |
| 其中明确「gold bug」（结果错） | 29 道 |
| gold SQL 病句（结果碰巧对，但 SQL 错） | 4 道 |
| gold 补全（题面问两样，gold 只给一样） | 4 道 |
| 补时间态/在职重叠过滤 | 6 道（官方）+ 6 道（自拟 BOM） |
| 题面消歧 / 空集退化处理 | 4 道 |
| 已核验但保留的 BIRD 原生态问题 | 3 道（见 §6） |

> **Q88/Q92 删除说明**：Q88「Engineering 2007 在职员工的信用卡同年过期」与 Q92「离职 Finance 员工的信用卡号」，因 AdventureWorks 员工（BusinessEntityID 1..290）无信用卡（`prsn_crd` 从 person 293 起全是客户），答案恒为 0/空集，属 ill-posed，无法用于区分 agent 正确性，故从题集删除，由自拟 Q127/Q128 补位。

---

## 4. gold 问题分类（六类）

核出的问题集中在以下六类，都属「长尾难句」重灾区：

### 4.1 聚合口径错（COUNT vs SUM vs DISTINCT、返回形状错）
- **布尔塞 ORDER BY**：`ORDER BY COUNT(comments)>10` 把「>10 评论」当排序键，返回「名字列表」而非「多少个」——Q6、Q21。
- **SUM(CASE) 返评论数而非产品数**：Q7、Q8。
- **COUNT 不去重**：员工有多条薪资/部门历史被重复计数——Q5、Q42。
- **COUNT(布尔) 计数=数全部行**（应 SUM）：Q80。

### 4.2 无谓 JOIN 造成 fan-out（按行加权而非按实体）
- 把 `emp_pay_hist`（一人多行）join 进来后 COUNT/AVG，按薪资历史行加权而非按员工数——Q2（百分比虚高）、Q9（平均薪资加权错）、Q27（计数虚高）。

### 4.3 列混淆 / 硬编码
- **rt(率) 当 py_frqn(频)**：Q11、Q31。
- **mx(最大) 当 mn(最小)**：Q48 的 MOQ。
- **clss='M'(中) 当 'H'(高)**：Q42 的 "high-class"。
- **ID 当 number / 名当 code**：Q67（crdt_crd_id vs crd_nmbr）、Q51（省名 vs 税率名）。
- **硬编码子查询/ID**：Q60（subcat=3）、Q85（IN (212,274)）。

### 4.4 日期/时间态口径错
- **误用非任期列**：Q39 用 `Department.ModifiedDate`（全 2008）而非员工任期 `StartDate/EndDate`。
- **漏当前态过滤（end_dt IS NULL）**：Q88、Q89、Q92、Q95、Q98，以及自拟 BOM 题 Q99–Q104。
- **取最新（薪资/时薪）**：Q27、Q98（未取 RateChangeDate 最新）。

### 4.5 gold 不完整（题面问两样，gold 只答一样）
- Q35（只返最年轻个体，没算每部门平均年龄）、Q55（缺 rate 列）、Q91（缺 sales person 名）、Q97（缺组织层级分布）。

### 4.6 畸形 SQL / 题面歧义 / 空集退化
- **畸形 JOIN**：Q28 的 `INNER JOIN Person ON T1.BusinessEntityID` 缺 `= T3.BusinessEntityID`（BIRD 原句就缺）。
- **题面歧义**：Q1（'Add' 被读成求和）、Q90（sales rep 双重歧义）。
- **空集退化**：Q21、Q60 的正确答案是空/0，若保留「list」题面，空 gold 会让任何空答案判对——已把题面改成「How many」。

---

## 5. 完整修改清单（50 题）

> 每题的具体修改理由已写入 `question_set_final(_obfuscated).json` 的 `note` 字段（provenance）。下表为清单索引。`kind` 标记：🐛=gold bug（结果错）、🧹=SQL 病句（结果碰巧对）、➕=补全、⏱=时间态、❓=题面消歧/退化处理、📝=自拟 provenance。

| Q | 域 | kind | 一句话 |
|---|---|---|---|
| 1 | Geography | ❓ | 题面 'Add' 歧义，改写为「两个独立计数」 |
| 2 | HR | 🐛 | 无谓 join emp_pay_hist 造成 fan-out，百分比虚高 81.64→80.69 |
| 5 | HR | 🐛 | COUNT 不去重，70→66 |
| 6 | Product | 🐛 | 布尔塞 ORDER BY 返名列表非计数，→0 |
| 7 | Product | 🐛 | SUM(CASE) 返评论数非产品数，→1 |
| 8 | Product | 🐛 | SUM(CASE) 返评论数非产品数，→1 |
| 9 | HR | 🐛 | 平均薪资按全历史行加权，应取每人最新，→[19.23,17.76] |
| 11 | HR | 🐛 | rt(率) 当 py_frqn(频) + LIMIT1，→126 行 |
| 17 | Product | 🐛 | 混历史价比现价均值，改现价，→368 |
| 20 | Product | 🐛 | GROUP BY+LIMIT1 返最常见价，应 list all，→3 |
| 21 | Product | 🐛 | 布尔塞 ORDER BY 返「有任何评论」，改 HAVING>10 + 改题面，→0 |
| 23 | Product | 🐛 | 取最高而非次高，→'HL Mountain Pedal' |
| 25 | Product | 🐛 | INNER JOIN 排除无评论产品，漏利润最高，→'All-Purpose Bike Stand'+NULL |
| 26 | HR | 🧹 | 补 DISTINCT（结果不变） |
| 27 | HR | 🐛 | 未取最新薪资，82→66 |
| 28 | HR | 🧹 | 畸形 JOIN 补 `=T3.BusinessEntityID`（答案仍 0） |
| 29 | HR | 🐛 | MAX-AVG 按全薪资历史行加权，改「每人最新薪资」，33.94→33.02 |
| 31 | HR | 🐛 | rt 当 py_frqn（答案仍 0，仅语义纠正） |
| 32 | Purchasing | 🐛 | 漏 mountain 过滤，→0 |
| 34 | Purchasing | 🧹 | `=1 AND 3` → `BETWEEN 1 AND 3`（答案仍 3） |
| 35 | HR | ➕ | 补每部门平均年龄，→16 行 |
| 39 | HR | 🐛 | 误用 ModifiedDate，改任期重叠，0→3 |
| 42 | Purchasing | 🐛 | clss='M'→'H' + DISTINCT，19→7 |
| 43 | HR | 🐛 | 「in 2009」用开区间漏边界，改在职重叠，1→5 |
| 48 | Purchasing | 🐛 | MOQ 用 mx(最大)，改 mn(最小)，29→6 |
| 51 | Sales | 🐛 | 返省名非税率名，→'United Kingdom Output Tax' |
| 55 | HR | ➕ | 补 rate 列 |
| 57 | HR | 🐛 | 返 DepartmentID 非部门名，改返名，→Purchasing/Marketing |
| 60 | Product | 🐛 | 硬编码 subcat=3 + 漏 salable，改类目名 + 改题面，→0 |
| 65 | HR | 🐛 | 补 2007 在职重叠 + AVG 改「每人最新薪资」，26.36→36.56 |
| 67 | Sales | 🐛 | 返 ID 非信用卡号，→'11111462416609' |
| 80 | HR | 🧹 | COUNT(布尔)→SUM（答案仍 Production） |
| 81 | HR | 🐛 | 题面「evening」写成 Night，改 Evening（答案仍 Production） |
| 85 | HR | 🧹 | 硬编码 IN(212,274) 改 join job_cand（答案不变） |
| 86 | Geography | 🐛 | 返联系类型非人名，→Gustavo Achong |
| 89 | HR | ⏱ | 补 end_dt IS NULL（结果不变） |
| 90 | Sales | 🐛 | sales rep 误映射 Customer.PersonID，34→74；题面消歧 |
| 91 | Sales | ➕ | 补 sales person 名 |
| 95 | HR | ⏱ | 补 end_dt IS NULL + evidence 写错列改 BirthDate |
| 97 | HR | ➕ | 补组织层级分布，→5 行 |
| 98 | HR | ⏱ | 三处错（无 GROUP BY/join 错列/漏历史过滤），重写为每部门最新时薪 |
| 99 | 自拟 BOM | ⏱ | 补 end_dt IS NULL（28→23 行） |
| 100 | 自拟 BOM | ⏱ | 补 end_dt IS NULL（28→24 行） |
| 101 | 自拟 BOM | ⏱ | 补 end_dt IS NULL（结果不变） |
| 102 | 自拟 BOM | ⏱ | 补 end_dt IS NULL（结果不变） |
| 103 | 自拟 BOM | ⏱ | 补 end_dt IS NULL（结果不变） |
| 104 | 自拟 BOM | ⏱ | 补 end_dt IS NULL（结果不变） |
| 105 | 自拟 Sales | ❓ | list 11k 过大改计数，→11095 |
| 109 | 自拟 Sales | ❓ | list 11k + LIMIT20 截断改计数，→11094 |
| 113 | 自拟 Sales | ❓ | 去 LIMIT20 截断，20→29 行 |
| 127 | 自拟 HR | 📝 | 补 Q88/Q92 剔除后的 HR 三外键空白（gold=22） |
| 128 | 自拟 Sales | 📝 | 5 表链 so_dtl→…→prod_cat（gold=36266202） |

---

## 6. 已核验但保留的 BIRD 原生态问题（3 题，不改）

以下 3 题核过，属于「BIRD 原始意图本身含糊/时间依赖」，我们**保留原样不修改**（改等于替 BIRD 重新定义题目），仅在此留档：

| Q | 问题 |
|---|---|
| Q19 | 题面「previous standard cost」应取相邻历史（LAG），gold 用「当前 vs 任意历史」，evidence 也这么写；若强行改成「最新历史价」答案退化为空集 |
| Q54 | 年龄用 `YEAR(CURRENT_TIMESTAMP)` 随当前年份漂移（evidence 本意 2022）；`ShiftID=3` 核过=Night 正确，不算错 |
| Q56 | 「personal information」= `Person.Demographics`（XML 大字段），语义可辩护但答非所问 |

---

## 7. 对评测数字的影响

gold 修正后，S 轴（single-shot）全量 126 题重判（不重跑 LLM，只换 gold 重判存储的 final_sql）：

| 档 | 原始 | **35 处全修后** |
|---|---|---|
| S0 裸 | 43.7% | **50.0%** |
| S1 +字典 | 53.2% | **64.3%** |
| S2 +字典+ER | 54.0% | **65.1%** |
| Δ₄(S1)/Δ₄(S2) | +9.5/+10.3 | **+14.3/+15.1** |

两点说明：

1. **修 gold 整体抬「诚实地板」约 +6~11pp**（agent 答对但被错误 gold 判错的题翻正）。
2. **修到后期 S0 略有回落是「变诚实」而非「变差」**——Q7/Q39/Q43/Q65 等之前是 agent 和错误 gold 同错造成的假通过，gold 修对后正确暴露为失败。

核心结论不变且更实：**single-shot 在 126 题全量分布下天花板 ≈65%，元数据梯度 +13pp，失败主体是低复杂度语义题（jc≤2），不是 join 导航。**

---

## 8. 结论

- **BIRD works_cycles 官方题的 gold 问题率约 44%**（43/98 需修改，其中 29 道是明确的结果错）。这是「权威基准 ≠ 零错误」的量化铁证——别人不核 gold，是因为跑分只需聚合 EX，1-2% 噪声对排序影响小、对所有模型公平；但我们要证明「元数据边际价值」，必须区分失败原因（gold 错 vs agent 错），才被逼着逐题洗 gold。
- 错误的**重灾区集中在长尾难句**（多表 join、语义歧义、日期/时间态口径、聚合口径），正是「简单题」之外的硬骨头。
- 本仓库 gold 现已逐题核定；每处修改都在 `note` 字段留 provenance，可复现（`gen_gold_wc.py` 重跑即得 gold.json）。

关联文档：`SPEC.md`（评测规范）、`exp-report-sql-metadata-gradient.md`（SQL 元数据梯度实验）、`s-axis-root-cause-analysis.md`、`q90-root-cause-analysis.md`。

---

## 9. 与 BIRD 官方 leaderboard 对照（结果校准）

> 本节把我们的 S/M 轴数字放到 BIRD 官方基准坐标里看，判断「LLM 的 SQL 能力处在什么水准」。**口径差异很大（见 9.3），数字只能校准方向，不能直接对标。**

### 9.1 BIRD 官方 leaderboard（EX = 执行准确率）

| 水平 | EX | 说明 |
|---|---|---|
| 人类专家 | 92.96 | BIRD 论文基线 |
| SOTA（test 集） | 81.67 | Agentar-Scale-SQL（test-time scaling）|
| SOTA（单模型微调） | 76.13 | Gemini 2.5-pro 微调 + 自洽 |
| 开源单模型 | 75.68 | RLVR（无专有模型）|
| 前沿模型 zero-shot | 46–52 | GPT-4 = 46.35、GPT-4o zero-shot CoT = 52.22 |
| 前沿模型 agentic | 59–65 | PV-SQL+GPT-4o 65.12、SCL-SQL 64.73、PAS-SQL 59.13、DIN-SQL+GPT-4 50.72 |

来源：[Agentar-Scale-SQL](https://arxiv.org/abs/2509.24403) · [Google Gemini](https://cloud.google.com/blog/products/databases/how-to-get-gemini-to-deeply-understand-your-database/) · [RLVR](https://arxiv.org/abs/2509.21459) · [DIN-SQL/GPT-4 基线](https://www.proceedings.com/content/075/075280-1577open.pdf)

### 9.2 我们的数字

| 轴 | 口径 | 结果 |
|---|---|---|
| S 轴 single-shot（deepseek-v4-flash） | 全量 126 题 | S0 50.0 → S1 64.3 → **S2 65.1** |
| M 轴 agent | 26 题精选子集（未全量） | M0 84.6 → M1 92.3 → **M2 92.3** |

### 9.3 口径差异（四处，必须诚实）

1. **题集不同**：BIRD leaderboard 是全量 dev/test（约 1.25 万题、95 库、平均难度）；我们只测 works_cycles 单库（AdventureWorks，65 表，偏难档），且 96 官方题是精选的多表 join 子集（73 多表 + 27 富特征），比 BIRD 全集平均难。
2. **方法不同**：S 轴 single-shot ≈ BIRD「zero-shot」基线；M 轴 agent ≈ BIRD「agentic」方法。S 轴不能对标 agentic SOTA。
3. **模型不同**：deepseek-v4-flash 是快/便宜档，非 GPT-4o/Gemini 前沿模型。
4. **gold 更严**：我们逐题核定 gold（见 §1–§6），判分比原 BIRD（含 ~44% 有问题的 gold）更严格。

### 9.4 校准结论

- **S 轴 single-shot 65%（S2）**：把「快模型 + 单次调用 + 元数据注入」放在难的 works_cycles 多表子集上做到 65%，≈ 前沿模型（GPT-4o）在 BIRD 全集上的 agentic 水平（59–65%）。**元数据注入把便宜的单次调用抬到了前沿模型全集的水平**——这是「数据上下文」价值的量化证据。
- **M 轴 agent 92%（M2，26 子集）**：已越过 SOTA 区间（76–82%），但属精选梯度敏感子集，不能外推，须等全量 M 轴跑完才能对标。
- **战略结论依旧成立**：单条 SQL 是「平价商品」——前沿模型 zero-shot 才 46–52%，我们用元数据 + 单次调用即达 65%，agent 又比 single-shot 高 27pp（26 子集 65→92）；真正拉开差距的是 agent 的迭代与 kernel 的 ML，不是单条 SQL 本身。
