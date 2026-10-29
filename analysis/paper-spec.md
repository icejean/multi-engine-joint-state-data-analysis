# SPEC: AI 数据分析新范式论文（数据上下文 × 多引擎：live kernel（Python/R）+ SQL + Cypher）

| 项 | 值 |
|---|---|
| 状态 | **草案 v0.6** — 组合机制 = 新范式定稿 + 文献地图 + 数据上下文锚点 + CypherBench 定量补齐 + TabReD ML 跨数据集复现 |
| 日期 | 2026-10-16 |
| 工作名 | paper-new-paradigm（占位） |
| 目标 | 一篇**有影响力、有参考价值**的机制/范式论文 |
| Novelty | **组合机制**（数据上下文「态」× 多引擎乘法 × 治理审计），非 benchmark 分数、非任何单点 |
| 一句话 | 把数据上下文（态）焊进 LLM 对话分析 ×（live kernel→ML / SQL→RDB / Cypher→GraphDB）多引擎乘法 + 执行级审计治理；确定性方法（schema.json+notes.md）收敛到 ~90%+ |

---

## 1. 背景与问题陈述

### 1.1 核心张力：LLM 的语义强，精确处理弱

- **LLM AI** 擅长语义理解与推理，但无法独自精确处理大规模结构化数据（上下文限制、幻觉、数值精度、无法真正"算"）。
- **ML AI**（sklearn/xgboost/lgbm…）擅长大规模结构化数据的精确处理（训练/预测/统计），但语义理解与推理弱（特征、模型、业务解释都要人来定）。
- 二者各是半边，传统上割裂。

### 1.2 1M 上下文时代的新可能

1M 上下文窗口让「把 schema + 经验一次性注入 agent」成为可能——探索被注入替代。这是机制成立的时代前提。

### 1.3 非目标

- 不追求公开榜单 SOTA 排名（差分 + 外推才是卖点）。
- 本 SPEC 的**已验证贡献**覆盖 SQL 单条查询 + Cypher 单图定量（CypherBench movie，见 §7 验证状态矩阵）；ML 是机制的**同类推广**，实验见 §8。

---

## 2. 核心 Thesis（宽版）

> **新范式 = 组合机制**：把「数据上下文（态）」焊进 LLM 对话式分析——**LLM 作为语义理解/推理层（不做计算层），通过 1M 上下文窗口连接四个引擎**（live kernel→ML AI（Python + R 双内核）、SQL→RDB、Cypher→GraphDB），实现两重乘法（**「语义 × 精确计算」**、**「关系型 × 图」**），再叠加**执行级审计 × OS 隔离 × 私有化**的企业级治理。确定性工程方法（schema.json + notes.md 一次性注入）保证每个方向收敛到实用高准确率（~90%+）。
>
> **核心锚点（一句话钩子）**：**对话上下文（词）人人有，数据上下文（态）只有分析师有**——LLM 手里是 handle，内核里是 value；ChatBI 无状态查完即弃，我们是「有态 + 多引擎 + 可治理」。三个世界各懂一半，没人站出来说「AI 数据分析缺的是数据上下文」——这是我们的空位。
>
> 引擎之上是**知识闭环**：**Know-what**（关系数据分析走 SQL → 业务洞察/风控）→ **Know-how**（图分析走 Cypher / GraphRAG → 领域知识）→ **Action**（OpenClaw/DSH → 执行），DataAI Portal 作为**语义枢纽**串起三层。

四个承重词不变：**确定性 / 工程化 / 外推 / 收敛**。

---

## 3. 机制的构成（论文要点，Jean 定调）

> 地基 = **数据上下文（态）**（有状态内核），三个维度、一条方法都从它长出来。

### 3.1 突破一：LLM AI × ML AI（live kernel）

- live kernel（持久化 Python/R）把 LLM 与 ML 连成**乘法**：LLM 做语义理解 + 编排 + 解释，ML 做大规模结构化数据的精确计算，结果回传 LLM 继续推理。
- **不是加法是乘法**：单独 LLM 无法精确"算"大表，单独 ML 无法"懂"业务语义；连起来才闭合「理解业务 → 精确分析 → 解释结果」的完整链路。
- SQL 只是这条乘法里**突破最小的一个方向**（单步查询生成）；ML 才是 live kernel 真正拉开的维度。

### 3.2 突破二：RDB × GraphDB（SQL + Cypher，经上下文窗口）

- 关系型（join/聚合/事务）与图（路径/遍历/关系推理）是**性质完全不同**的两类大规模结构化数据，传统数据分析割裂成两套工具两套人。
- 但它们属**同一业务领域、不同数据域**：关系型承载 know-what（业务状况洞察）、图承载 know-how（领域知识）。LLM 上下文窗口 + SQL + Cypher 把它们连进**同一个 agent**，做**跨数据领域语义打通**，以便及时采取适当的行动应对。

### 3.3 维度三：Know-what → Know-how → Action 三层闭环（知识层）

- 引擎之上是**知识闭环**：**Know-what**（关系数据分析走 SQL → 业务洞察/风控；SQL 不局限于 SQL 引擎，R/Python 引擎也能直接执行 SQL 查询）、**Know-how**（图分析走 Cypher，GraphRAG 从组织文档构建知识图谱 → 领域知识/方法规程）、**Action**（OpenClaw/DSH → 自动化执行）。
- LLM 只做**翻译/编排/解释层**，不做计算层——大规模结构化计算、图算法、检索全由引擎完成。
- 三者在**一个对话上下文**中无缝衔接，DataAI Portal 是**语义枢纽**。闭环还**自增强**：know-how 层（如「虚开风险」实体模式）可反哺 know-what 的筛查规则。

### 3.4 治理层：执行级审计 × OS 隔离 × 私有化

- 记录「Kernel 里真实执行成功的代码」（非提问/结果元数据）——可复现、可 diff、可出合规审计报告。
- OS 层多租户隔离（每用户独立 Linux 账户）+ 私有化/信创适配——治理是「可治理数据上下文」区别于「个人沙箱」的关键。

### 3.5 确定性工程方法 M+S（让机制可落地）

- `schema.json`（自动生成：数据字典+外键）+ `notes.md`（迭代积累：有限、可命名的数仓模式分类）注入 agent，替代逐表探索。**schema 加载分规模**：小库（works_cycles 65 表）**一次性注入**（schema 为 JSON 格式）；大库（newbc-ri 370 表）schema 为 DDL text 格式，**分层按需截取**——读头 → grep 建表索引（≈几千 token）→ 用到哪表截哪表字段片段（每问 1–3k token），地基是表索引而非全量（报告 §2.5）。
- 这是「怎么把上面组合机制**工程化、确定性**地落地到 ~90%+」的答案——是机制的**方法论**，不是机制的**全部**。
- **notes.md 分层可插拔（免改代码）**：三层内容——**数仓通用规则**（跨库通用 SQL 规则）、**业务库特征**（主体，每库特有的注意事项）、**模型专属规则**（换模型微调，幅度随能力差）。用户业务域 / 用到的表子集 / 注意事项各异，故**只加载自己用到的部分**、不必背整本全系统手册——省时间、省 token、提准确率。落地只需配置资源文件 + 改提示词模板冷铺一次即生效。
- **用户级 → 系统级迭代路径**：按用户维度维护用户级 notes.md（只挂相关子集）→ 积累一段时间后综合提炼成系统级 notes.md → 循环迭代——把「经验累积」工程化成可复现的**知识飞轮**。
- **notes.md 外推 = 机制外推（非内容外推）**：外推对象不是「某库的 notes 内容」，而是「分层可插拔 + 从零迭代积累 + 收敛」这套方法——新库/新场景/新用户上，给定 schema.json + 空 notes.md，照样能在使用中沉淀该库特有的坑、随迭代收敛（works_cycles 65 表、newbc-ri 370 表均已从零迭代证过）。内容按三层取舍：数仓通用规则可跨库复用、业务库特征（主体）每库从零积累、模型专属规则同模型间复用。**可观测信号 = 准确率收敛曲线**。

---

## 4. 文献地图与定位（related work）

> 结论先行：**「元数据有用」已被占位（拥挤区）；「有状态内核」正在商品化（单点区）；「数据上下文 × 多引擎 × 治理」的组合仍是空白（我们的 novelty）。**

### 4.1 拥挤区（元数据轴——已被占，别当 novelty）

| 工作 | 占掉什么 | 我们的处置 |
|---|---|---|
| Cube（arXiv:2604.25149） | 元数据有用（100 题配对 +17~23pp，McNemar p≤0.0015） | 独立佐证，直接引用 |
| dbt Labs | 语义层配对 +15pp | 转引 |
| MCI-SQL（arXiv:2603.13390） | metadata-complete 预注入，BIRD 76.41% SOTA | 它预注入、我们可查询元数据（systems 差异） |
| BIRD-INTERACT（ICLR 2026） | Agent + 元数据环境 + 执行反馈 benchmark（GPT-5 仅 8.67%/17%） | 它测「会不会交互」、我们测「元数据梯度 × 机制」 |

### 4.2 单点区（有状态内核——正在商品化，不是独家）

- 有状态内核：JetBrains 2026.08 live kernel、Snowflake Notebooks、marimo、Hex/Deepnote/Posit（Jupyter 系）。
- Jupyter-MCP 桥：Ivanfangsc/jupyter-mcp、nteract PR #441 等开源实现。
- **结论**：「有状态」「Jupyter-MCP」单点已不是空白、是趋势——**novelty 必须落在组合上**。

### 4.3 空白格（我们的 novelty——组合机制）

| 空白格 | 说明 |
|---|---|
| 元数据完备度 × 机制交互 | 「Agent 价值只在 M1 甜点区（字典有、ER 缺）」——可证伪交互假设，三模型同向已有证据（+20/+24/+20pp） |
| 机制增益 × 模型能力交互 | S→M 增益反比于模型能力（弱模型 GLM +27~33pp vs 强模型 deepseek +5pp）——「Agent 是弱模型放大器」，把「元数据 × 机制」升成「× 模型能力」三维 |
| 字典 vs ER 分离消融 | 哪类元数据解决哪类错误，无人系统做过；★弱模型 ER 仍有增量（GLM S2−S1=+5.6pp vs deepseek 0）——「ER 边际增益小」只在强模型成立 |
| schema 加载：SQL 查库 vs grep 文本 | systems 差异：M 纯探索反复生成 SQL 查库摸 schema（list_objects/preview_data/introspection，多轮高 token）；M+S 直接 grep schema 文本只取片段（每问几千 token）——370 表实测省一个数量级（报告 §2.5） |
| 异构联合上下文（RDB + KG + ML + 状态） | 同一 LLM 上下文驱动 RDB、KG、ML 的端到端工作流——最重的 systems 空白 |
| Agent 判分陷阱 | 「取最后一条 SQL」vs「答后验证」冲突，假阴性 52pp——方法学贡献 |
| 反记忆 benchmark 方法学 | 污染探测 → 改名 → 训练集外新实体 → 值域错开 |

### 4.4 定位一句话

> **「元数据有用」是别人的结论；「数据上下文 × 多引擎 × 治理」的组合机制是我们的 novelty——我们回答的是「在什么元数据条件下、什么执行模型下，数据分析 agent 才划算」。**

---

## 5. 价值评估（诚实版）

| 维度 | 评估 | 依据 |
|---|---|---|
| 机制 novelty | ✅ **强** | 「数据上下文 × 多引擎 × 治理」组合，现有工作与竞品都没有（竞品矩阵四维打满的仅 Portal） |
| Timing | ✅ **好** | 1M 上下文 + LLM×ML×RDB×Graph 打通是当下热点交集 |
| 实用价值 | ✅ **清晰** | SQL 方向 ~90%+ 无 ER 已实证；ML/Cypher 是真实业务刚需 |
| 决定性质证据 | ✅ **补齐** | SQL 机制外推定量曲线已做（BIRD dev 两 dirty 库超 SOTA）+ CypherBench 定量已做（movie 96.5% 超 SOTA 24~34pp）+ ML 跨数据集已做（TabReD weather 16.95M） |

**结论**：宽版**够得上一篇有影响力、有参考价值的机制论文**——但它是「机制论文」不是「单库 benchmark 论文」，说服力取决于四引擎各有一个**已验证实例**。SQL ✅、Cypher ✅（CypherBench movie 96.5% / pass^3 94.0%）、ML ✅（跨数据集 TabReD weather 16.95M，默认参复现、10%≈全量饱和）、R ✅（rtorch GPU MLP 复现 TabReD weather 10%，test RMSE 1.5419，与 Python 对拍一致）。

---

## 6. 贡献陈述（按可验证性排序）

1. **范式/机制（组合）**：数据上下文（态）× 多引擎（live kernel→ML（Python + R 双内核）、SQL→RDB、Cypher→GraphDB）× 治理审计——统一机制，实现两重乘法连接。
2. **确定性工程方法（M+S）**：schema.json 自动生成 + notes.md 迭代积累，替代探索，SQL 方向已验证收敛 ~90%+。
3. **实证支配（SQL）**：M+S 在准确率/成本/可靠性三维度优于 single-shot 与纯探索；~90%+ 无 ER（强模型）；**跨模型：M+S 是弱模型放大器**（S→M 增益反比于能力，GLM +27~33pp vs deepseek +5pp）。
4. **收敛曲线**：notes 迭代单调逼近、把「经验累积」量化成可复现工程过程（works_cycles ~90%+；BIRD dev 两 dirty 库 70.9→83.1 / 75.5→84.9，超 SOTA）。
5. **（诚实性附带）**BIRD gold 质量审计 + 「好字典即可、ER 非必需」反直觉发现 + Agent 判分陷阱的方法学发现。

---

## 7. 核心 Claim + 验证状态矩阵

| 方向 | 引擎 | Claim | 状态 |
|---|---|---|---|
| SQL | SQL kernel → RDB | M+S 收敛 ~90%+，三维度支配 S/M，无 ER | ✅ works_cycles 126 题（deepseek 97.6% / glm 94.4%） |
| SQL 机制外推 | 同上 | notes.md 机制（分层可插拔 + 从零迭代收敛）跨库成立，收敛水平随库/模型变化 | ✅ BIRD dev 两 dirty 库：formula_1 70.9→83.1%、financial 75.5→84.9%，均超 SOTA（+6.7/+8.5pp） |
| 规模化（大 schema） | SQL/R/Python kernel → 370 表 RDB | 三层按需截取机制扩展到 370 表生产库、无 ER 依然成立、notes 跨 kernel 复用 | ✅ 定性（newbc-ri 370 表，SQL/R/Python 端到端 + MiniMax M3 多模态读图） |
| Cypher | Cypher kernel → GraphDB | 同机制，text-to-Cypher 收敛到高准确率 | ✅ CypherBench movie 401 题：96.5% EX（pass^3 94.0%），超 zero-shot SOTA 24~34pp |
| ML | Python/R kernel → ML | LLM×ML 乘法：语义编排 + 精确计算闭环 | ✅ **定量 demo**（27 万行上海房价，3 GBDT R² 0.94-0.96 SOTA，**LLM 独自无法**）+ **跨数据集复现**（TabReD weather 16.95M，默认参 test RMSE 1.5450，10%≈全量） |
| R | R kernel → ML（rtorch GPU） | 独立第四引擎：R 内核驱动 GPU DNN，与 Python 管线逐项对齐 | ✅ rtorch GPU MLP，TabReD weather 10% 抽样（1.7M），test RMSE 1.5419（Python 对拍 1.5387；走通级非 SOTA 级） |

**关键诚实边界**：Cypher 为单图定量（movie——CypherBench 最知名代表性图，M+S 口径非 zero-shot）；ML 跨数据集已复现但**默认参数 +5.6% 于调参 SOTA**（TabReD 论文用 Optuna+15 种子）——ML 要分两层写：「乘法定量证明」（上海房价 27 万行达 SOTA）+「跨数据集复现/流程效率」（TabReD weather 千万级，非 SOTA、差在调参那一下）。

---

## 8. 实验设计（四引擎，对齐既有权威基准计划）

| 引擎 | 数据集 | 角色 |
|---|---|---|
| SQL | works_cycles（✅）+ BIRD dev（✅）+ newbc-ri 370 表（✅ 定性） | 已验证 + 从零迭代收敛曲线（✅） |
| Cypher | CypherBench（megagonlabs，10,882 题 / 5 域 / 11 图 / 7.8M 实体） | ✅ movie 子图 401 题 96.5%（pass^3 94.0%）；movie 已是最知名代表性图、复杂度/数据量已足，另加一图留待有时间再补 |
| ML | 上海房价 27 万行（✅ 定量 demo）+ **TabReD weather**（✅ 千万级 16.95M） | LLM×ML 乘法（autonomous pipeline → SOTA，R²/MAE） |
| R | **TabReD weather 10% 抽样**（✅ 1.7M，rtorch GPU MLP） | 第四引擎走通 + Python 对拍（test RMSE 1.5419 vs 1.5387） |

> **ML 的评测范式不同于 SQL/Cypher**：没有「gold 查询」可比，其定量指标是「autonomous pipeline 是否达到 SOTA 精度」（R² 0.94-0.96 / MAE 11%）——这是 LLM 独自无法企及的（无法精确拟合 27 万行 GBDT），也正是乘法的定量证明。跨数据集（TabReD weather 16.95M）复现已完成——但按**默认参数**复现（10%≈全量、test RMSE 1.5450、vs 调参 SOTA +5.6%），它验证的是「对话驱动全流程 + 效率」（测试目标），而非「SOTA」。
>
> **产品定位（Portal 对话界面的价值边界）**：Portal 对话界面验证的是** AI 辅助快速 ML 建模的效率**——人指挥 Agent 从原始数据走通全流程，尤其**百万、千万级记录以上**；**调优是资深专家的高技能工作、另一维度，适合在交互式 IDE 中进行**——对话界面只承担「快速建出来、跑通」，不承担冲 SOTA。

模型：deepseek-v4-flash / glm-5.2（✅）+ deepseek-v4-pro / glm-5.1 / ≥1 西方模型。
指标：准确率（relaxed+strict）、成本、延迟、工具轮数、pass@k + 方差。
消融（SQL 方向先行）：schema 单独 / notes 单独 / 都无（纯 M）/ single-shot（S）。

---

## 9. 风险与诚实边界（R-1..R-7）

- **R-1 确定性 vs 模型非确定性**：方法确定性（schema 自动生成、notes 封闭分类）≠ 输出比特确定（temp=0 仍非确定、S0 ±15pp）。收敛 = 方法稳定钉在 90%+。★**方差与能力负相关**（GLM-5-Pro 翻转率 26.2%/极差 6.3pp vs deepseek 7.1%/2.4pp）——要可信点估计，选强模型比多跑几轮划算。
- **R-2 overfit 批评**：notes 单库特调之嫌。防御 = taxonomy 封闭性 + 机制外推（从零迭代，非内容搬运）+ 收敛曲线。
- **R-3 gold 质量**：BIRD gold 43.9% 有问题（修 35 处）。双报告 + provenance。
- **R-4 过度声明风险**：Cypher 单图定量（movie 1/11，但已是最知名代表性图）；ML 已跨数据集复现（TabReD weather），但**默认参非 SOTA**——别把「流程/效率验证」写成「ML 达 SOTA」，要写成「SQL/Cypher 已验证 + ML 乘法定量（上海房价 SOTA）+ ML 跨数据集复现（TabReD 千万级流程/效率）」。
- **R-5 「90%+」参照系**：对标 BIRD dev 人类 ~92%、前沿 single-shot ~65%。
- **R-6 范围爆炸**：四引擎全做是很大工作量，需分期（见 §11），且每期单独可发表。
- **R-7 「首先提出」的边界**：「有状态内核」「Jupyter-MCP」单点已被 JetBrains/Snowflake/开源占位——「首先提出并实现」必须精确落在**组合机制**（数据上下文 × 多引擎 × 治理审计）上，不落在任何单点。

---

## 10. 关联文档

- dataai-test：`tech-route-selection.md`（技术路线）、`findings.md`（结论推导）、`pass3-variance-report.md`（三维方差）、`mplus-126-glm52-vs-deepseek.md`（跨模型）、`glm52-7q-root-cause.md`（根因）、`gold-verification.md`（gold 审计）、`bird-dev-convergence.md`（BIRD dev 收敛）、`gold-fixes-bird-dev.md`（BIRD gold 修复）、`bird-dev-pro-vs-flash.md`（跨模型）、[[dataai-portal-performance-test-plan]]（四引擎权威基准计划）。
- dataai-portal（竞品/战略）：`竞品分析-DataAI-Portal.md`（主护城河=数据上下文、四维组合无对手）、`路演材料-DataAI-Portal.md`（「别人查一查，我们算一算还能继续算」）、能力 demo 3 篇（R语言ML / Cypher图引擎 / Kernel热切换）。

---

## 11. Roadmap（分期，每期单独可发表）

| 阶段 | 内容 | 产出 | 对应论文切片 |
|---|---|---|---|
| P1 | SQL 机制外推：BIRD dev 从零迭代 notes + 收敛曲线 | C4 ✅ 已完成 | SQL 机制外推（定量补强） |
| P2 | 统计补齐：多模型 × pass@k × CI | 图表 | SQL 严谨化 |
| P3 | CypherBench | 图引擎验证 | ✅ movie 子图已完成（96.5%）；单图已足，另加一图可选 |
| P4 | TabReD weather（LLM×ML 乘法，时间切分 RMSE 对标 TabReD 论文） | ML 验证 | ✅ 已完成（默认参 test RMSE 1.5450 / R² 0.8408，10%≈全量，vs 调参 SOTA +5.6%） |
| P5 | 合成：组合机制统一叙事 + 写作投稿 | 论文 | 范式全文 |

---

## 12. 待定项（O-1..O-3）

- **O-1 目标 venue**：CIDR（机制/范式友好）/ VLDB-SIGMOD agent workshop / EMNLP-ACL industry / 先 arXiv。
- **O-2 第三 SQL 数据集**：Spider（通用性）vs 真实客户 DW（落地性）。
- **O-3 一篇 vs 分篇**：「一论文覆盖四引擎」影响力大但周期长；「先发 SQL 单篇（元数据×机制交互）再发机制总篇」稳但碎片化。主叙事已定 = 组合机制，O-3 只决定发布节奏。
