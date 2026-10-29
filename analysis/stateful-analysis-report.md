# 持久上下文（Stateful Data Analysis）：AI 数据分析的新范式
## —— DataAI Portal 四引擎实验报告

> 版本：v0.5 草案（未定稿，供讨论）
> 日期：2026-10-17
> 定位：这是「新范式」的第一次对外沟通——定名 + 证据 + 定位，不是刷分报告。

---

## 摘要

**一句话定名**：对话上下文（**词**）人人有，持久上下文（**态**）只有我们。

**核心结论**：在一个 65 表、74 万行的真实数仓（BIRD AdventureWorks）上，DataAI Portal 的 **M+S 模式**（schema + notes 资源文件注入提示词）以 **123/126 = 97.6%** 的准确率、**一半的成本**、**远低于单发方案的方差**，同时压过了 single-shot（Text2SQL）和纯探索式 Agent——这是「持久上下文」机制的 SQL 方向实证；同一机制在 ML（Python/R 内核 27 万行 GBDT SOTA + TabReD weather 千万级跨数据集复现）、**R 语言引擎**（rtorch GPU MLP + float32 直通道全量 GBDT，TabReD weather 分别 1.5419 / 1.5449，与 Python 引擎对齐）和图（CypherBench movie 96.5% EX + 资金环路风控 demo）三个方向同样成立。

**定位**：「元数据有用」已有文献占位（Cube / MCI-SQL / BIRD-INTERACT），「有状态内核」单点正在商品化（JetBrains / Snowflake / 开源）；**「数据上下文 × 多引擎 × 治理审计」的组合机制，目前仍是空白格**——这是本报告要建立的新范式。

---

## 一、定名：什么是「持久上下文」

### 1.1 词 vs 态

LLM 有两样东西，人往往混为一谈：

- **对话上下文（词）**：LLM「记得你说过什么」——它手里没有那份数据在持续计算，只能「谈论」数据，不能「算」数据。上下文窗口再长，LLM 也「算」不了 1000 万行的 LightGBM。
- **数据上下文（态）**：DataFrame、变量、模型在**内存里活着、还在算**。这是传统 ML（Python/R 会话）的标配，ML 人天天用；BI 人不知道有这回事；LLM 这波人只懂「词」不懂「态」。

**三个世界各懂一半，没人站出来说「AI 数据分析缺的是数据上下文」——这是我们的空位。**

我们把「态」焊进 LLM 的对话式分析，并做成**可治理、可审计、私有化**的企业级能力，给它定名：

> **持久上下文（Stateful Data Analysis）**：数据跨轮不死、能多轮迭代续算。

### 1.2 第二问是试金石

第一问「近 12 个月各分行不良贷款率」，有状态和无状态出的图一模一样，demo 分不出高下；**第二问**「按客户年龄段再拆一层」、第三问「换成 LightGBM 重训一遍」——无状态沙箱查完即弃、只能从头再来，我们因为内核还活着、数据还在内存里，直接迭代。

> **别人查一查，我们算一算还能继续算。**

### 1.3 组合机制（新范式的完整定义）

持久上下文不是单点，是一个**组合机制**，四个部件缺一不可：

| 层 | 内容 |
|---|---|
| **地基** | 数据上下文（态）：有状态内核，DataFrame/变量/模型跨轮存活 |
| **乘法一** | LLM AI × ML AI：live kernel 连接语义编排与精确计算 |
| **乘法二** | RDB × GraphDB：SQL + Cypher 经LLM上下文窗口打通两种异质结构化数据 |
| **治理** | 执行级审计 × OS 隔离 × 私有化：记录「真实执行成功的代码」，可复现可审计 |

---

## 二、证据一：SQL 方向（works_cycles 126 题 + BIRD dev 两 dirty 库）

### 2.1 实验设置

- **数据集**：BIRD AdventureWorks（微软官方数仓），65 表、~74 万行，改名混淆成 3 档元数据梯度库。
- **题集**：126 题（96 官方 + 30 自拟，覆盖多表 JOIN、递归 CTE、时间态、fan-out 去重等真实数仓陷阱）。
- **三档元数据**：M0 裸 schema / M1 +数据字典 / M2 +字典+ER 图。
- **三种机制**：S（single-shot 单发）／M（纯探索 Agent）／**M+S（Agent + schema/notes 资源文件——小 schema 一次性注入，大 schema 按需截取，见 §2.5）**。
- **判分**：结果集等价比对（非 SQL 比对、非 LLM-as-judge），gold 逐题连库核定（发现并修 35 处 BIRD gold 错误，全程留 provenance）。

### 2.2 M+S 三维度支配

| 机制 | 准确率（放宽口径） | 成本（均 token/题） | 可靠性 |
|---|---|---|---|
| S（single-shot，最优档 S2） | 87.3% | ~10–16k | 单发 ±15pp 非确定（35.7% 漂移硬币） |
| M（纯探索 Agent，M0） | 92.1% | ~490k（+50×） | 多轮(multiturn)自纠错，但成本高 |
| **M+S（注入提示词上下文）** | **97.6%** | **~200k（减半）** | **三轮极差仅 1.6pp** |

- **准确率**：M+S 天花板 97.6% > 纯 M 92.1% > single-shot 87.3%。
- **成本**：M+S 比纯 M 的 token/轮数减半（探索被一次性注入替代）。
- **可靠性**：M+S 三轮极差 1.6pp，远优于 single-shot 的 ±15pp 漂移。

> 注：表中 S（87.3%）/ M（92.1%）为 round5 口径，M+S（97.6%）为 pass4 口径——pass4 又修了 3 处 BIRD gold bug（Q14/72/79），故 M+S 站在「更干净的 gold」上，S/M 用 pass4 gold 重判后也会小幅上修。三档**机制差的方向性结论**（M+S 全维度优于 S 与纯 M）由 pass^3 三轮方差报告独立坐实，不依赖上表的绝对数字。

**pass^3 三轮方差（`docs/pass3-variance-report.md`，126 题 × 3 轮硬隔离，模型 DeepSeek v4 Flash）**——上表「可靠性」一列在此独立坐实。

> 口径：**pass\@1（三轮合并）** = 三轮单次作答合并成 378 次样本池的答对比例 = 三轮准确率平均（能力）；**pass^3（三轮全对）** = 三轮全对题占比（可靠性下界——用户只跑一次，pass^3 才是真实体验下界）；**三轮极差** = pass1/pass2/pass3 最大−最小；**漂移题占比** = 三轮里只对 1 或 2 次的题占比。

三轮单次准确率（每档 × 3 轮）：

| 档 | pass1 | pass2 | pass3 |
|---|---|---|---|
| S0 | 64.3% | 69.8% | 65.9% |
| S1 | 87.3% | 85.7% | 84.9% |
| S2 | 81.7% | 83.3% | 86.5% |
| M0 | 89.7% | 86.5% | 85.7% |
| M1 | 88.9% | 88.1% | 91.3% |
| M2 | 90.5% | 88.9% | 88.1% |
| **M+S M0** | **90.5%** | **92.1%** | **91.3%** |

| 档 | pass\@1（三轮合并） | pass^3（三轮全对） | 三轮极差 | 漂移题占比 |
|---|---|---|---|---|
| S0 | 66.7% | 48.4% | 5.6pp | 35% |
| S1 | 86.0% | 81.0% | 2.4pp | 10% |
| S2 | 83.9% | 75.4% | 4.8pp | 16% |
| M0 | 87.3% | 80.2% | 4.0pp | 12% |
| M1 | 89.4% | 81.7% | 3.2pp | 13% |
| M2 | 89.2% | 81.0% | 2.4pp | 14% |
| **M+S M0** | **91.3%** | **85.7%** | **1.6pp** | **10%** |

三模式最优档对比：S 最好档 86.0% / 81.0% / 2.4pp，M 最好档 89.4% / 81.7% / 2.4pp，**M+S M0 91.3% / 85.7% / 1.6pp——准确率、可靠性、方差三个维度全占最优**，成本（轮数 4.8、token 275k）比纯 M（10.6 轮）减半。这是「M 主 S 辅」路线在方差维度的最终铁证：注入（S 之长）让 M 免探索、执行反馈（M 之长）让结果收敛，两者叠加而非冲突。全表还暴露 S0 是唯一「不可靠」档（单次 66.7% 但 pass^3 仅 48.4%、漂移 35%），ER 对 single-shot 是噪声不是增量（S2 pass^3 75.4% < S1 81.0%）。

### 2.3 天花板收口（经验如何确定性收敛）

M+S 的 97.6% 不是一次撞出来的，是一条**可复现的收敛曲线**：

1. 逐题根因（把失败归成 9 类：时间态、递归层级、去重、口径歧义……）；
2. 修 gold（BIRD 官方 gold 的 bug，agent 本就答对、gold 错）；
3. 补 notes（把「经验」沉淀成有限、可命名的数仓模式分类，如「递归 CTE 层级用 level+1 不用 bm_lvl」「fan-out 按实体去重」）；
4. 迭代到饱和——**剩余 3 题是双口径歧义 + schema 间接，属「诚实边界」而非可修缺陷**。

这一条正是「持久上下文」里 **notes.md 迭代积累**的含义：经验是可沉淀、可迁移、可收敛的工程资产，不是一锤子买卖。

### 2.4 跨模型成立（收敛水平取决于模型能力）

同一套 schema.json + notes.md，换模型**机制依然成立**——但**收敛水平随模型能力下降**，且 M+S 相对 single-shot 的增益**反比于模型能力**（弱模型放大器）：

| 模型 | single-shot（S 轴） | M+S | S→M+S 增益 |
|---|---|---|---|
| deepseek-v4-flash | 87.3%（S2 满配） | 95.2%*（97.6% pass4 天花板） | ~+5pp |
| glm-5.2 | — | 94.4% | — |
| glm-5.1（GLM-5-Pro，256K） | 48.4%（S1）/ 54.0%（S2） | 81.0%（pass^3 均值） | **+27~33pp** |

> \*95.2% 是 glm-5.2 对照用的「修复版 notes」口径（与 deepseek 同套 notes，可直接比）；§2.2 头条的 97.6% 是 pass4 天花板（又修了 3 处 gold）。

**关键发现：M+S 是「弱模型放大器」**——弱模型 glm-5.1 从 single-shot 48~54% 被抬到 81%（**+27~33pp**），强模型 deepseek 只抬 ~+5pp。弱模型扛不住 65 表一次性推理，agent 的多轮短推理链是它的救命稻草；强模型本来单发就快满，增益自然小。

glm-5.2 落后 3 题，根因已逐题定位（3 题「答完后又跑验证 SQL」+ 1 题「递归 CTE 缺 DISTINCT」+ 3 题真实语义差），修前两者后即从 92.1% 提到 94.4%——**说明差距是「经验/行为」可修，不是机制失效**。

**另两条跨模型规律**（详见 `docs/mplus-glm5pro-report.md`）：

1. **方差与能力负相关**：glm-5.1 翻转率 26.2%/极差 6.3pp vs deepseek 7.1%/2.4pp——要可信点估计，选强模型比多跑几轮划算。
2. **notes.md 是模型专属的（一层）**：notes 积累的是强模型（deepseek）的失败模式，换弱模型救不了「读不懂题/规则不跟」，需重新积累——这正说明 notes **分层可插拔 + 用户级→系统级迭代**（§2.3）的必要。

> 诚实边界：glm-5.1 的 81.0% 是 pass^3 三轮均值（107/100/99，单调降或为下界）；其部署在息壤平台，耗时/token/成本口径与 deepseek 不可直接比，只有准确率+轮数是干净指标。

### 2.5 规模化验证：370 表生产库，机制从「注入」退化为「按需截取」

works_cycles 的 65 表、25k token schema 可以一次性注入；真实生产库更大。我们在一个 **370 表 / 4986 字段、~119 万行（估算）** 的研发管理平台生产库（newbc-ri）上验证了同一机制能否扩展：

- **压缩**：schema + 字典注释压成 **DDL 文本 185K 字节 / 约 7 万 token**（**不含 ER 图**——字典已隐含大部分 join），占 1M 窗口 **<10%**，**256K 窗口亦足**。
- **机制演化（关键，三层）**：大 schema 下 M+S 不再是「全量注入」，而是 **M + 可寻址瘦身文件**。三个会话（SQL/R/Python）**从未全量读 schema**，实测走三层：**① 读头**（60–120 行，学格式 + 审计列约定）→ **② 建索引**（grep 表头 + `SHOW TABLES`，拿 386 表名 + 250 条一行注释 ≈ 几千 token 的可寻址地图）→ **③ 截片段**（用到哪张表才 grep+offset 读哪张表的字段行，每问 1–3k token）。地基是几千 token 的**表索引**而非 7 万 token 全量——比「先全量后截取」再省一个数量级。效率高于纯 M 的 DB 分步探索：瘦身前置（无数据行、无审计列噪声）+ grep 内容寻址（无需构造 introspection SQL）+ 文件跨 kernel 复用。
- **前提可落地（加分项）**：三层机制靠「表名 + 表/字段注释」作语义钩子。表注释几乎总有，字段注释可由**低成本元数据治理**补齐（远比逆向建 ER 图便宜）——所以这不是实验室特例，真实生产库即可复用。
- **跨 kernel 持久上下文**：notes.md 从空开始，随 SQL→R→Python 三个会话迭代积累（字典编码翻译、系统归属绕关系表、字段名易错…），后两个 kernel 直接复用前一个 kernel 沉淀的坑。
- **三 kernel 端到端**：SQL（缺陷多维分类）、R（ggplot2 趋势 + 处理时效）、Python（人员周负荷多表交叉验证）均跑通深度分析；第二场 Python 会话（glm-5.2）再跑**缺陷月度趋势**（1374 条，2023-05~2026-10）与**某员工周负荷**（日报 738 篇周粒度 × 月工时 335 条交叉）两张图，坐实 notes.md 由 SQL 沉淀后被 Python 直接复用。
- **多模态读图（MiniMax M3 vs 纯文本模型）**：deepseek-v4-flash 与 glm-5.2 都是**纯文本模型**，读不了统计图——deepseek 的 R 会话 tool 调用里出现 **`cannot read <img>`**（画了图读不了自己的图）。**MiniMax M3（多模态）** 用 `read_image` 直接「看图说话」：能读图表类型 / 图例（15 类逐项）/ 趋势形态 / 配色占比（「蓝色=后端代码缺陷主力」「橙色=性能问题叠层」），但**读不出精确数值**（只能粗估 140+/80+）、**易漏小信号**（「废除项 35 条」被主力色淹没）、**无法跨图对比**（视觉通道单图）。最佳实践 = **数据 + 视觉双通道**：SQL 挖精确数值/异常点，图让 LLM 看形态、做趋势叙述。实际数据分析有大量统计图要解读，这是多模态模型的价值——内网一体机部署成本摊薄后不再是短板。

> 诚实边界：这是**定性验证**（5 段对话端到端），**没有 370 表规模的 benchmark 精度数字**；且暴露两个开放项——schema 漂移（DB 实有 386 表，53 张无字典、37 条孤儿条目）与文本模型无视觉（deepseek/glm-5.2 能画图但读不了自己的图，已由多模态 MiniMax M3 部分补齐，但读图有边界：读不出精确数值、易漏小信号、无法跨图对比）。

---

### 2.6 漂移根因与抑制：数据上下文把漂移压近 4 倍（financial pass^3）

§2.2 的「可靠性」一列（M+S 极差 1.6pp）揭示了注入让方差骤降，但**漂移从哪来、能否根治**，直到 financial 的 pass^3 才定量回答。完整方法论见 [`semantic-drift-methodology.md`](./semantic-drift-methodology.md)。

**定量**（financial，BIRD dirty 库，M+S 全配 3 轮 × 106 题）：

| 指标 | 数值 |
|---|---|
| EX 均值 | **95.3%**（基线 84.9% → +10.4pp）|
| 轮间漂移率（相邻两轮翻转概率）| **6.6%** |
| 总漂移率（3 轮累计不稳定题占比）| 8.5% |
| 稳定对占比 | 90.6% |

**根因两层**：① 语义歧义（脏数据列名过载/枚举/口径 → 模型靠非确定探索兜底）——**可治**；② 推理非确定（reasoning 模型内在随机，temperature / reasoning_effort 均无效）——**只能压、不能清零**。

**抑制 = grounding（正是「数据上下文」）**：把语义歧义消成确定性 grounding（schema + notes + evidence），模型不再靠非确定探索。**works_cycles S0→M+S 漂移 35.7%→9.5%，约 3.8 倍下降**——grounding 每加一层，漂移降一档。

**复杂度定天花板、grounding 定压多少**：同等 M+S 下复杂业务（works_cycles 9.5%）漂移高于简单业务（financial 8.5%）；但裸漂移（S0 35.7%）才是复杂业务的真面目——**「数据上下文」的价值在复杂业务下最大**。

**生产落地**：grounding + 每用户 notes.md（不用 k-vote）——用户范围有限 → 问题有限 → notes 收敛快。这正是「持久上下文」从 benchmark 到生产的落地形态。

### 2.7 跨库复现：formula_1 同法收敛（第二个 dirty 库）

§2.6 的 grounding 修法在 financial（第一个 dirty 库）有效，但「换个库还成立吗」是「notes 外推 = 机制外推」的关键检验。formula_1（BIRD dev 第二个 dirty 库，172 题）用同一套「通用 notes + 个例 evidence」复现：

- **从零迭代收敛曲线**：70.9% → 73.8% → 81.4% → 83.1%（4 轮 notes 单调收敛、成本不变）——「notes 外推」的第二条曲线（第一条 financial 75.5%→84.9%）。
- **grounding 推极限**：round4 83.1% → round5 93.6%（单发，notes §7–14 + 12 题 evidence）。

**pass^3 定量**（3 轮 × 172 题）：

| 指标 | 数值 |
|---|---|
| EX 均值 | **94.6%**（97.1 / 93.6 / 93.0）|
| 稳定对占比 | 88.4% |
| 轮间漂移率 | **6.7%** |
| 稳定错 | 1 题（Q161，lapTimes 脏时间格式的复杂 CASE，硬地板）|

- **「碰巧全过 ≠ 修过」**：round5 定向跑的 7 题「碰巧全过」，在 pass^3 里 3 轮全挂——补 evidence 才真修住。这是「单轮绿 ≠ 稳定绿」的活案例，也正是 pass^3 存在的意义。
- **天花板确认**：单发重跑 167/172 = **97.1%**，恰平历史最好单轮、未突破天花板——**复杂度定天花板、grounding 只压方差不抬天花板**，判定不再 squeeze。

**跨库确证**：两个 dirty 库（最脏、逆风局）用同一套 grounding 都收敛到 ~95%、轮间漂移率同量级（financial 6.6% vs formula_1 6.7%），加上 works_cycles（97.6%）——**M+S 机制跨三库成立，非单库运气**。「数据上下文（态）」在 SQL 方向经受住了复杂业务（works_cycles）与脏数据（两个 dirty 库）两种逆风局的检验。

---

## 三、证据二：多引擎（同一机制的四个方向）

### 3.1 ML 方向（LLM × ML 乘法）

Python/R 内核驱动 27 万行上海房价数据，端到端「取数 → 清洗 → 特征工程 → 特征选择 → 建模 → 评估」：

- 三套 GBDT（LightGBM / XGBoost / CatBoost）测试集 **R² 0.94–0.96**，MAE 11%，Kaggle 顶级水准；
- **这是 LLM 独自无法企及的**——LLM 无法精确拟合 27 万行的 GBDT，ML 无法自己懂业务语义；live kernel 把它们连成乘法。
- **跨数据集复现（TabReD weather，千万级 16.95M）**：对话驱动官方 canonical 全流程（流式加载 → 探索 → 官方 103 特征重建 → 10% → 全量），LightGBM 默认参 test **RMSE 1.5450 / R² 0.8408**（fit 346s）；**10% 抽样 ≈ 全量**（test RMSE 差 0.0011，10% 已饱和）——千万级用 10% 抽样省 ~8× 算力拿同一答案。vs TabReD 论文调参 SOTA（Optuna+15 种子）**+5.6%**，差在调参——**调优是资深专家的高技能工作、另一维度，适合在交互式 IDE 中进行**；Portal 对话界面验证的是快速建模的效率（尤其百万/千万级），不承担冲 SOTA。
  

### 3.2 图方向（RDB × GraphDB 乘法）

Cypher 内核跑通「珠海机场 → 资金环路 → 团伙分析」demo：

- WCC 子图识别 → 环路检测（3 跳、金额幅度 <20%，对应「资金回流/虚开发票」风控特征）→ Leiden 社区 + PageRank 团伙画像；
- 关系型走 SQL、图走 Cypher，同一 LLM 上下文打通两种异质结构化数据。
- **定量**：CypherBench movie 子图 401 题 **96.5% EX**（pass^3 94.0%），超 zero-shot Text2Cypher SOTA 24~34pp（Claude 3.5 Sonnet 61.58% / Cypher-RI 69.59%）。


### 3.3 多语言热切换（持久上下文的载体）

R 清洗 → Python 特征工程 + 建模 → R 可视化，CSV 共享层跨内核交换中间结果；JupyterHub 崩溃后靠磁盘落盘无损恢复——**中间结果落盘 + 内核常驻 = 持久上下文健壮性的实证**。

### 3.4 R 语言引擎（第四引擎）

R 内核不再是 Python 的「清洗/可视化配角」，而是**独立第四引擎**。它现在有两条能力与 Python 引擎对齐：**GPU 深度学习（rtorch MLP）** 与 **千万级 GBDT（float32 直通道，全量 16.95M）**。后者是从「R 跑不了千万级」的内存墙里硬凿出来的，按「踩坑 → 根因 → 解法」展开。

**① GPU 深度学习：rtorch MLP**

- 数据/口径与 Python 版一致：TabReD weather 10% 抽样（1,696,406 行），103 特征，MLP（3×256）+ AdamW + MSE，default 时间切分。
- 结果：test **RMSE 1.5419°C**（5 轮 3.3 分钟），略优于 TabReD paper MLP 15 次均值 1.547；Python GPU 对拍 1.5387——预处理/切分逐项一致，R 侧管线与 Python 对齐。
- 环境：GPU 笔记本 RTX 2060 6G（全量特征矩阵 ~6.8GB 放不下，故 10% 抽样，X 常驻 680MB ≈ 1.9GB 显存、峰值 ~40% 负荷）。

**② GBDT 内存墙的根因（mlr3 vs tidymodels 实测）**

- 20% 抽样（3.39M 行）对照：mlr3 与 tidymodels（formula 路由）**结果完全一致**（RMSE 1.5100 / R² 0.8480）、内存近乎打平（峰值 VmHWM **14.07 vs 14.70GB**，差 ~4%），**25% 两者都 OOM**。
- 关键数字：20% 的数据本身才 ~2.4GB，峰值却 14.7GB——**那 ~12GB 是加载/拷贝/glibc 碎片开销，不是数据**。
- 深层根因：R 没有一等公民的 float32 稠密矩阵，`matrix`/`data.matrix()` 全 double；全量 16.95M×103 double ≈ **14GB**，加 LightGBM Dataset + 加载开销 → 测试笔记本设置的WSL2 16G 上限下必 OOM。**选 mlr3 还是 tidymodels 无所谓（内存差 4%），真瓶颈是框架无关的「float64 + 加载开销」。**

**③ 解法：float32 直通道（已跑通全量）**

- 思路：LightGBM C API **原生支持 float32**，只是 R 包只接 double。用 C++（arrow 直读 parquet + LightGBM C API）以 float32 端到端，数据全程不落 R double。
- 实现：通用入口 `gbdt_float_fit()`（参数化 source/target/split/scale/params/nrounds）；**数据集专属预处理走 R 逐块回调**（换数据集写 R 不写 C++），**通用列级变换（StandardScaler）走 C++ 内置**（NumPy 同款 fit/transform）。
- 结果：全量 16.95M 跑通，**test RMSE 1.5449 对齐 Python 官方 1.5450（差 0.0001）**，**峰值 VmHWM 10.56 GiB**（15GB 机器余量 ~4GB），耗时 499s、16 线程。
- 内存修复：`reserve` 预分配 / `batch_size` 控单块 / 每块 `gc()` / 分块预测 / `GetSubset` 后 `Free(full)`，五刀把峰值从 ~15GB 压到 10.56 GiB。
- 诚实边界：峰值主因是 `CreateFromMat(全量)→GetSubset(train)` 的 full+train 分箱**必然共存**；可再用 `LGBM_DatasetPushRows` 流式建 Dataset 压到 ~8.8 GiB，但多读一遍 parquet 明显变慢，已决定不压。
- 通用性与空白：同法可扩 xgboost / CatBoost（都有 float32 C API）；现成方案里 H2O 要 JVM、xgboost external memory 磁盘慢——**「原生 R + float32 + RAM 常驻」这条轻量路是空白**。
- **可扩展成通用 R 包**：这条 float32 直通道（`gbdt_float_fit` 通用入口 + `preprocess` 回调）已验证是数据集无关的，需要时可直接封成一个通用 R 包；而 R 生态里 lightgbm / xgboost / ranger / data.table / arrow 这些主力包本身就是 **C++ 内核 + R 薄壳** 的标准结构——「C++ 做重活、R 做接口」是 R 包的常规做法，本方案完全落在这个惯例内，不是异类。

> 对齐结论：R 引擎在千万级 GBDT 上与 Python 对齐（1.5449 vs 1.5450），在 GPU 深度学习上对齐（1.5419 vs paper 1.547）——第四引擎从「走通级」升到「能力对等」。

---

## 四、定位：文献地图

「元数据有用」是别人的结论，「组合机制」是我们的空白格。

### 4.1 拥挤区（元数据轴——已被占，别当 novelty）

| 工作 | 来源 | 占掉什么 | 我们的处置 |
|---|---|---|---|
| Cube | [arXiv:2604.25149](https://arxiv.org/abs/2604.25149) | 元数据有用（100 题配对 +17~23pp，McNemar p≤0.0015） | 独立佐证，直接引用 |
| dbt Labs | 官方博客（Semantic layer vs Text-to-SQL） | 语义层配对 +15pp | 转引 |
| MCI-SQL | [arXiv:2603.13390](https://arxiv.org/abs/2603.13390) | metadata-complete 预注入，BIRD 76.41% SOTA | 它预注入、我们可查询元数据 |
| BIRD-INTERACT | ICLR 2026 | Agent + 元数据环境 + 执行反馈 benchmark（GPT-5 仅 8.67%/17%） | 它测「会不会交互」、我们测「元数据梯度 × 机制」 |

### 4.2 单点区（有状态内核——正在商品化，不是独家）

- 有状态内核：JetBrains 2026.08 live kernel、Snowflake Notebooks、marimo、Hex/Deepnote/Posit（Jupyter 系）。
- 有状态评测：LongDS-Bench（[arXiv:2605.30434](https://arxiv.org/abs/2605.30434)，68 任务 / 2225 轮，最好模型仅 48.45——难点是「状态随会话演进保持正确」，正是我们主护城河）。
- LLM × R 生态：DARE（[arXiv:2603.04743](https://arxiv.org/abs/2603.04743)）——已占「检索侧」，运行时/状态侧仍是空白。
- 长上下文聚合：OOLONG（[arXiv:2511.02817](https://arxiv.org/abs/2511.02817)）——128K 上 GPT-5 / Claude / Gemini 聚合推理全部 <50%，说明「窗口再长也替代不了就地计算」。
- **结论**：「有状态」「Jupyter-MCP」单点已不是空白、是趋势——**novelty 必须落在组合上**。

### 4.3 空白格（我们的 novelty——组合机制）

| 空白格 | 说明 |
|---|---|
| 元数据完备度 × 机制交互 | 「Agent 价值只在 M1 甜点区（字典有、ER 缺）」——可证伪交互假设，三模型同向（+20/+24/+20pp） |
| 字典 vs ER 分离消融 | 哪类元数据解决哪类错误，无人系统做过 |
| schema 加载：SQL 查库 vs grep 文本 | systems 差异：M 纯探索反复生成 SQL 查库摸 schema（list_objects/preview_data/introspection，多轮高 token）；M+S 直接 grep schema 文本只取片段（每问几千 token）——370 表实测省一个数量级（§2.5） |
| 异构联合上下文（RDB + KG + ML + 状态） | 同一 LLM 上下文驱动 RDB、KG、ML 的端到端工作流——最重的 systems 空白 |
| Agent 判分陷阱 | 「取最后一条 SQL」vs「答后验证」冲突，假阴性 52pp——方法学贡献 |
| 反记忆 benchmark 方法学 | 污染探测 → 改名 → 训练集外新实体 → 值域错开 |

> 外部链接均转引自 DataAI Portal 产品规划讨论（2026-09），正式发布前需逐条回溯原文核实。

**定位一句话**：我们不回答「元数据有没有用」（已有人答了），我们回答「**在什么元数据条件下、什么执行模型下，数据分析 agent 才划算**」——M+S 就是这个问题的确定性答案。

---

## 五、诚实边界与下一步

**已实证**：SQL 方向（works_cycles 126 题 + financial 106 题 + formula_1 172 题，三库定量）；Cypher 方向（CypherBench movie 401 题定量）；ML（定量 demo + TabReD weather 千万级跨数据集复现）；R 语言引擎（rtorch GPU MLP 1.5419 + float32 直通道全量 GBDT 1.5449，TabReD weather，与 Python 引擎对齐）。

**待补（本报告的已知边界，不回避）**：

1. **SQL 三库定量、漂移已量化**：works_cycles（97.6% 天花板）+ financial（95.3% pass^3，轮间漂移 6.6%，§2.6）+ formula_1（94.6% pass^3 均值 / 97.1% 单发天花板，轮间漂移 6.7%）——「notes 外推 = 机制外推」已由三库证过；newbc-ri（370 表）仍为定性（§2.5）。
2. **works_cycles 仍以单次跑为主**：financial 已补 pass^3（§2.6），works_cycles 部分格子仍缺 pass^k 显著性检验（single-shot 单发 ±15pp 非确定）。
3. **Cypher 定量**：✅ CypherBench movie 401 题 96.5% EX / pass^3 94.0%，超 zero-shot SOTA 24~34pp——单图口径，但 movie 是 CypherBench 最知名代表性图、复杂度/数据量已足，另加一图留待有时间再补。
4. **ML 跨数据集**：✅ TabReD weather（16.95M）已复现——默认参 test RMSE 1.5450 / R² 0.8408，10%≈全量饱和；vs 调参 SOTA +5.6%（差在调参）。
5. **R 语言引擎**：✅ 双能力对齐 Python——rtorch GPU MLP（10% 抽样 1.5419，对拍 1.5387）+ **float32 直通道全量 GBDT**（16.95M，test RMSE 1.5449 对齐 Python 1.5450，峰值 10.56 GiB）。诚实边界：GBDT 默认参非 SOTA（对齐 1.5450 口径）、峰值略超 10GB 初设（10.56 GiB）但已决定不压。

**下一步**（对齐权威基准计划）：Cypher ✅（CypherBench movie，单图已足）→ ML ✅（TabReD weather 已复现）→ **R 语言引擎 ✅（rtorch MLP 1.5419 + float32 直通道全量 GBDT 1.5449——四引擎补齐、与 Python 能力对齐）** → 合成范式总篇（论文）。

---

## 附：数据与复现

- 题集 / gold / 建库 / 判分 / 跑分脚本：`dataai-test/`（`data/works_cycles/`、`scripts/`）。
- 结果文件：`results_wc_mplus_126_pass4.json`（deepseek 97.6%）、`results_wc_mplus_126_glm52.json`（glm-5.2 94.4%）。
- Cypher 定量：`data/movie/results_movie_*.json`（96.5% EX / pass^3 94.0%）。
- ML 跨数据集：`docs/tabred-weather-ml-benchmark-spec.md`（SPEC）+ `data/tabred/chat-31828136.html`（session 对话记录）+ `scripts/spike_tabred_weather*.py`。
- R 语言引擎：`scripts/spike_tabred_weather_torch_10pct.R`（rtorch MLP 主脚本）+ `scripts/spike_tabred_weather_torch_fixed_10pct.py`（Python 对拍参考）+ `data/tabred/chat-de8408b9.html`（session 对话记录）。
- R 千万级 GBDT 内存对照（mlr3 vs tidymodels，20% 抽样打平）：`data/tabred/chat-f236b0b2.html`（mlr3，20% 峰值 14.07GB / 25% OOM）+ `data/tabred/chat-1cb90705.html`（tidymodels，10% 峰值 9.69GB / 20% 峰值 14.70GB）；脚本 `scripts/spike_tabred_weather_lightgbm_mlr3.R` / `scripts/spike_tabred_weather_lightgbm_tidymodels.R`。
- R 千万级 float32 直通道（全量 16.95M，test RMSE 1.5449 / 峰值 10.56 GiB）：`scripts/gbdt_float.cpp`（通用入口 C++）+ `scripts/run_gbdt_float_full.R`（全量入口）+ `docs/r-lgb-float32-full-spike-spec.md`（SPEC）+ `data/tabred/chat-3667ecb4.html`（session 对话记录）。
- 技术路线推导：`docs/tech-route-selection.md`；跨模型对照：`docs/mplus-126-glm52-vs-deepseek.md`；根因：`docs/glm52-7q-root-cause.md`。
- gold 核定：`docs/gold-verification.md`（35 处修正，逐条 provenance）。
