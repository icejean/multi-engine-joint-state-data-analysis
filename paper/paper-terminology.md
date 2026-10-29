# 论文术语中英对照表

> 用途：写作与翻译时锚定术语、防漂移（Jean 定调：先中文打磨定稿，再译英文）。
> 规则：**方法术语夹英文原词不译**；**叙事概念首次出现双语标注**，之后只用中文。
> 关联：`paper-draft-zh.md`、[[jean-paper-writing-chinese-first]]。

---

## 一、方法术语（夹英文原词，不译）

| 中文 | 英文原词 | 口径 / 说明 |
|---|---|---|
| single-shot（S 轴） | single-shot | 单发、一次性注入，无执行反馈、无迭代；S0 裸 / S1 +字典 / S2 +字典+ER |
| 纯探索（M 轴） | pure-exploration agent | agent 自迭代、执行反馈闭环；M0 裸 / M1 +字典 / M2 +字典+ER |
| M+S | M+S | agent + `schema.json`/`notes.md` 资源文件一次性注入（M 主 S 辅）；**schema 不限定有没有 ER——有 ER 就加，M 轴 agent 执行反馈闭环有效利用注入的元数据（区别于 single-shot S2 的 ER 反诱漂移）** |
| grounding | grounding | 确定性锚定：`schema.json` + `notes.md` + evidence，把语义歧义消成确定性 |
| 平均准确率 | avg accuracy | 三轮准确率平均（能力口径）；即 378 次作答中答对的占比 |
| 并集准确率 | union accuracy | 三轮里至少一次答对的题占比（能力上界） |
| 三轮全对 | all-3 accuracy | 三轮全对的题占比（可靠性下界） |
| schema.json | `{库名}_schema.json` | 数据字典 + 外键引用关系，自动生成（打包 `sys_tables`/`sys_table_fields`/`sys_foreignkeys`）；§4.1 的 S0/S1/S2 梯度 = 把它拆成「裸 schema / +字典 / +字典+ER」三档做消融 |
| notes.md | `{库名}_notes.md` | SQL 生成注意事项，迭代积累，分层可插拔 |
| evidence | evidence | 题级证据（grounding 的一部分，逐题核定的正确 SQL/口径） |
| EX | execution accuracy | 执行准确率（结果集等价比对） |
| relaxed / strict | relaxed / strict | 放宽（结果集等价）/ 严格口径 |
| dirty 库 | dirty databases | BIRD dev 里唯二被标「脏数据」的库（financial、formula_1） |
| 结果集等价比对 | result-set equivalence | 判分方式：非 SQL 比对、非 LLM-as-judge |
| 漂移题占比 | drift-question ratio | 三轮里 1~2 次答对的题占比（= 并集 − 三轮全对），衡量「漂移题」的多少 |
| 轮间漂移率（翻转率） | flip rate | Σ相邻轮对翻转次数 ÷（题数 × 轮对数），即相邻两轮答案翻转的概率；与「漂移题占比」是两个不同量，勿混 |
| gold-v4 | gold-v4 | 最终 gold 的第 4 轮修定版（正文曾写 pass4；与「三轮全对」无关，勿混） |
| live kernel（有状态内核） | live kernel / stateful kernel | 单引擎内 DataFrame/变量/模型跨轮存活（JetBrains/Snowflake/marimo 正商品化） |

## 二、叙事概念（首次出现双语标注，之后只用中文）

| 中文 | 英文 |
|---|---|
| 持久上下文 | Stateful Data Analysis |
| 多引擎联合上下文数据分析 | Multi-engine Joint State Data Analysis |
| 数据上下文 | data context（state） |
| 对话上下文 | conversational context（words） |
| 确定性收敛 | deterministic convergence |
| 弱模型放大器 | weak-model amplifier |
| 机制外推 | mechanism generalization |
| 知识飞轮 | knowledge flywheel |
| 组合机制 | combination mechanism |
| 执行反馈闭环 | execution-feedback loop |
| 业务领域 / 数据域 | business domain / data domain |
| Know-what / Know-how / Action | 知识闭环三层：know-what = 关系数据走 SQL（洞察，不限于 SQL 引擎）；know-how = 图走 Cypher（领域知识）；Action = 行动 |
| 信创 | Domestic ICT Innovation（按意思表达最贴切，强调国产化；论文正文用此译法） |

> **「State → 上下文」翻译口径（Jean 定调）**：核心新概念的 **State 译「上下文」，不译「态」**。理由——LLM/AI 语境里 State 一般指 context（上下文）；加 Data 进一步明确是「数据上下文」：计算引擎里做数据分析用的上下文，**不是**对话聊天用的上下文（words）。故 Multi-engine Joint State → **多引擎联合上下文**，全称「多引擎联合上下文数据分析」（断句 =「多引擎联合上下文」+「数据分析」）。派生规则：单字「态」作概念名一律 →「上下文」（联合态→联合上下文、单引擎态→单引擎上下文、ML 态→ML 上下文、关系型态→关系型上下文、图态→图上下文、跨数据域持久态→跨数据域持久上下文）；双字「状态 / 有状态 / 无状态」作普通词保留（状态流动、有状态内核、无状态）。「数据上下文 / 对话上下文」靠「数据 / 对话」前缀区分 state / words，不再用「（态）/（词）」标注。

> **架构图引擎标签口径（Jean 定调）**：中文 `.mmd` 架构图的引擎标签用「数据」而非「上下文」（ML 数据 / 关系型数据 / 图数据）——图中单独讲「上下文」易被误读为对话上下文，用「数据」更易懂；英文版对应 **ML context / relational context / graph context**（英文 context 无此歧义、且与正文术语一致）。论文正文 prose 仍统一用「上下文」/ context，二者不冲突（图给「数据」标签、文做「上下文」论述）。

> **层级关系（Jean 定调）**：**持久上下文（Stateful Data Analysis）** = 底层——单引擎的上下文跨轮存活（Python/R ML 引擎是持久的数据上下文），是与「一次性沙箱执行模型」的本质区别；**多引擎联合上下文数据分析（Multi-engine Joint State Data Analysis）** = 上层——Stateful Data Analysis 的**升级**、持久上下文的跨引擎增强（多引擎 + 状态流动 + grounding 复用）。「数据上下文」是「持久上下文」所持久的东西，二者同指底层。

> **RDB × GraphDB（乘法二）口径（Jean 定调）**：RDB 与 GraphDB 属**同一业务领域、不同数据域**——关系型（join/聚合/事务）承载 know-what（业务状况洞察，走 SQL 但**不限于 SQL 引擎**、Python/R 引擎也能直接执行 SQL），图（路径/遍历/关系推理）承载 know-how（领域知识，走 Cypher，**不属于 know-what**）；同一 LLM 上下文做**跨数据领域语义打通**，通往 Action（及时行动）。不是「两套无关工具、两个业务」，是「同一业务的两个数据域」。

## 三、基准 / 参照系

| 名称 | 说明 |
|---|---|
| BIRD AdventureWorks（works_cycles） | 65 表、~74 万行，126 题（96 官方 + 30 自拟） |
| BIRD dev | 官方 dev 集 11 库；其中 financial（106 题）、formula_1（172 题）为 dirty 库 |
| MCI-SQL | BIRD dev single-shot SOTA，metadata-complete 预注入，EX 76.41%（跨系统参照，非同设置 A/B） |
| CypherBench | 图引擎基准（movie 子图 401 题） |
| TabReD weather | ML 基准（16.95M 行） |

## 四、模型口径

| 模型 | 角色 |
|---|---|
| deepseek-v4-flash | 主模型（三机制对比、收敛曲线） |
| glm-5.2 | 跨模型验证：single-shot S2 77.8% → M+S 平均 91.8% / 三轮全对 85.7%（+14.0pp，弱模型放大器中间点） |
| glm-5.1（GLM-5-Pro） | 弱模型放大器证据（S 48~54% → M+S 81%） |

> 维护提醒：新增术语先在本表登记再写入正文；翻译英文时按「方法术语保留原词、叙事概念按本表英译」执行。
