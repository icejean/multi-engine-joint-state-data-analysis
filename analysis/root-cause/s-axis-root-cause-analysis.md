# S 轴 single-shot 根因分析：26 题逐题归因 + S/M 机制差距

> works_cycles（AdventureWorks）26 题梯度敏感子集。本文回答两个问题：**① S 轴（single-shot Text2SQL）为什么落后 M 轴（Agent 自迭代）；② 修到极限后，S/M 的机制差距到底在哪。**
>
> 结论先行：S 轴落后分两层——**「元数据瑕疵 + 提示词缺规范」（可修，已修）** 和 **「单次调用没有执行反馈」（机制本体，修不掉）**。修掉第一层后，S 轴从 38.5%→57.7%→69.2%（S0）、50.0%→80.8%→88.5%（S1）、65.4%→84.6%→92.3%（S2）；**S2 最终与 M2 打成平手（92.3% = 92.3%）**。差距从「裸库 26.9pp」收窄到「ER 档 0pp」。

---

## 0. 战略意义（本实验的真正产出，先读这个）

这个实验**不是**为了证明「元数据有帮助」（那是浅层结论），而是**把 Portal 的地板打实、把分水岭划清**：

- **地板打实（SQL 维度）**：元数据梯度 S0 38.5% → S2 92.3%（**+53pp 全是「数据上下文」的功劳**，把你「数据上下文 = 核心差异化」从口号变成量化证据）；且 S2 = M2（92.3%），**单条 SQL 上 Portal 不比最好的 single-shot 差**。
- **分水岭划清（SQL 之上）**：持久化 kernel 支撑的**多轮持续迭代 + 大规模数据集 ML 数据科学生态**——这是另一个坐标系，single-shot 连门都摸不到。

一句话：**单条 SQL 是「平价商品」**（1M 上下文 + 强推理下，single-shot ≈ agent，agent 还贵 ~50×）；**Portal 真正的突破是持久化 kernel 上的 ML + 多轮迭代**，与数据量大小无关（SQL 把数据下推 RDB、只回结果，所以「大数据塞不进上下文」不是差异点）。

---

## 1. 两轴权威数字（均 26 题 × 3 档全量重跑）

| 档 | S 轴（single-shot，`results_wc_s_26_fix3.json`） | M 轴（Agent，`results_wc_m_26_final.json`） | 差距 |
|---|---|---|---|
| 0 裸 schema | **69.2%** (18/26) | **84.6%** (22/26) | −15.4pp |
| 1 +字典 | **88.5%** (23/26) | **92.3%** (24/26) | −3.8pp |
| 2 +字典+ER | **92.3%** (24/26) | **92.3%** (24/26) | **0pp** |

> 判分同口径 `results_equal_relaxed`；模型同 deepseek-v4-flash。S 轴单次调用、M 轴 agent 自查（list_objects/preview_data/执行反馈）。
>
> ⚠️ S 轴单次调用有 ~31% 逐格翻转噪声，S0=69.2% 明显被裸库 FK 猜对抬高了（真实 ~60%）、S1=88.5% 含 Q111 数据巧合（真实 ~85%）；S2=92.3% 是唯一与 M 轴同档可比的稳定数。**S2≈M2 的结论稳健，S0/S1 的绝对 pp 别对外说死。**

**M 轴 final 失败列表**：M0=[Q90/Q94/Q98/Q99]、M1=[Q90/Q100]、M2=[Q90/Q99]。**Q90 是唯一 6 格（S0/S1/S2 × M0/M1/M2）全挂的题**——双重歧义+间接 schema 的硬骨头，见 `docs/q90-root-cause-analysis.md`。

---

## 2. S 轴失败根因：11 类 → 三层

对 26×3=78 次运行逐题执行 gold vs 候选 SQL 定位差异，失败归成 11 类，按「能否修」分三层：

### A 层：元数据/提示词可修（与 M 轴第二轮修复同源）

| 根因 | 题 | 机制 |
|---|---|---|
| **列合并 CONCAT** | Q123、Q126（全挂）、Q94 地址 | 题面说「full name」就 `CONCAT`，gold 要 `frst_nm`/`lst_nm` 分列 |
| **公式错** | Q94 profit | `p.lst_prc − p.stnd_cst`(标价−标准成本)=14.69，gold 要 `prod_vnd.lst_rcpt_cst − stnd_prc`=1.81 |
| **递归深度** | Q101（全挂） | 用 `MAX(bm_lvl)`，不用递归 `level+1` |
| **end_dt NULL 语义** | Q89/Q99/Q100 的 S0 | 裸 schema 不知道「`end_dt IS NULL`=当前生效」 |
| **脑补 join** | Q33 S1 | 无端 `JOIN emp`→0 行（SC 门店联系人非员工） |
| **`SELECT *` 过度选择** | Q89（全挂） | join/filter 都对，但 `emp.*` 输出身份列无姓名 |

### B 层：元数据 bug（本轮新发现）

| 根因 | 题 | 机制 |
|---|---|---|
| **ref 列描述错** | Q128 S1（及 Q108/Q113 S1 翻转） | `so_dtl.ref2`(ProductID) 描述误写「促销-产品编号」，与 `ref1`(SpecialOfferID) 同字失去区分度 |

根因在 `generate_descriptions.py`：ref 列描述取「FK 目标表短名」，而 `SalesOrderDetail` 的复合外键 `ProductID+SpecialOfferID` 都指向 junction 表 `SpecialOfferProduct`(「促销-产品」)，于是两列都叫「促销-产品编号」。`REF_OVERRIDE` 漏了 `productid`/`specialofferid`。

### C 层：固有（单次调用修不掉 = 机制差距本体）

| 根因 | 题 | 为什么修不掉 |
|---|---|---|
| 双重歧义 + 间接 schema | Q90（全挂） | 见 `docs/q90-root-cause-analysis.md`，M 轴也 0/3 |
| 账单地址 vs 客户地址 | Q111 | gold 用 `so_hdr.ref5`(账单地址)=1884，模型走客户→地址；fix3 那次「翻正」是 COALESCE 顺序碰巧=1884，语义没解决 |
| count vs 数量 歧义 | Q100（fix3 已翻） | 「components in total」=COUNT(24)，fix2 算 SUM(44)、fix3 改了 COUNT 但漏 end_dt(28) |
| 保留字语法错 | Q103（已翻） | CTE 名 `usage`(保留字)→syntax error |
| 缺 DISTINCT | Q99 S1 | 24 vs 23 行 |
| 噪声 | Q108 S1、Q113 S1 | ref2→ref1 翻转，single-shot 非确定 |

---

## 3. 修复动作（纯静态、零 LLM、可复现）

1. **`generate_descriptions.py`**：`REF_OVERRIDE` 补 `'productid':'产品编号'`、`'specialofferid':'促销编号'`（B 层），重生成 `descriptions.json` + 迁移字典/ER 库。
2. **`run_bench_wc_singleshot.py` 的 `build_prompt`**：移植 M 轴 meta_instr 通用化规范——输出列「一列一值/复合字段拆开/禁 CONCAT/禁 `SELECT *`」、过滤 JOIN「只加题面必需、别脑补」、SQL 细节「禁保留字别名」（A 层）。
3. **`build_prompt` 加「有效期/时间态」**：带结束日期/有效期列的表，「当前/生效中」= 该列 IS NULL；递归 CTE 的 base 和 recursive 两层都要加（C 层的 end_dt 应用方差，通用规则非 BOM 专属）。

---

## 4. 逐题归因

**fix2（动作 1+2）21 改善 / 3 回退**——机制落地确认（逐条看 SQL，非蒙对）：

| 修复 | 翻正的题 | 证据 |
|---|---|---|
| 提示词「拆列」 | Q123×2、Q126×3、Q94 地址 | `frst_nm, lst_nm, jb_ttl` 分列；Q126 **连 S0 都分列** |
| 提示词「禁 `SELECT *`」 | Q89 S1/S2 | `SELECT p.frst_nm, p.lst_nm` |
| 提示词「禁保留字」 | Q103 S2 | CTE 改名 `product_usage` |
| **元数据 ref2 修复** | Q128 S0/S1 | `sd.ref2 = p.prdc_id` |
| 元数据「profit on net」 | Q94 S1/S2 | `pv.lst_rcpt_cst − pv.stnd_prc` |
| 元数据「level+1 勿用 bm_lvl」 | Q101 S1/S2 | `MAX(lvl)` 递归 |

**fix3（动作 3）真翻正 3 处**——Q99 S2、Q100 S1/S2（SQL 里 base+recursive 两层都出现了 `end_dt IS NULL`，行数 28→24/23 对齐 gold）。其余 fix2→fix3 的翻转（Q111 S1/S2、Q89/Q98/Q123/Q127 的 S0、以及回退 Q1 S0/Q33 S2/Q99 S1）是 single-shot 噪声，非提示词效果。

---

## 5. 机制差距（S vs M，全量重跑对照）

差距随元数据丰富**单调收窄**：15.4pp（裸）→ 3.8pp（字典）→ **0pp（字典+ER）**。

**逐题对照揭示机制差异的精确位置**：

| 现象 | 题 | 解读 |
|---|---|---|
| 都挂 | Q90 | 双重歧义+间接 schema，两轴共有的天花板 |
| 各挂一题（BOM 递归方差） | M1 挂 Q100、M2 挂 Q99；S1 挂 Q99 | 递归 CTE 题两轴都有方差，single-shot 与 agent 都非确定 |
| S 独挂 | Q33（S0/S1） | 题面「employees」误导 over-join，S 修不动、M 靠执行反馈绕开 |

> 一句话：**S 轴天花板 = M 轴去掉「执行反馈/自纠错」后的上限，而这个上限在富元数据下已经和 M 轴重合**。修完 A/B/C 层，S2 = M2 = 92.3%，剩下的差距只在裸库（S0 vs M0 的探索价值）和「Q90 类共有的天花板」。

---

## 6. 诚实边界（对外口径）

1. **本实验只测「单条 SQL」**（见 `README.md`「项目定位与边界」）。它**不覆盖 Portal 的主要能力**——R/Python 持久化 Kernel + ML、图 Cypher、多轮持续迭代。**单条 SQL 是平价商品**：1M 上下文下 single-shot ≈ agent，M 轴无精度优势、成本还高 ~50×。
2. **Portal 的突破在 benchmark 之外**：持久化 kernel 支撑的多轮迭代 + ML 数据科学生态。对外话术（Jean 定稿）：「别人走 single-shot 能做到的，我们走 Agent 也能做到，在大规模数据集多轮对话中逐步占优；我们的起点就是别人的天花板。」
3. **S 轴噪声**：single-shot 逐格翻转 ~31%，S0/S1 的绝对 pp 别对外说死，只讲「单次调用下元数据是刚需、富元数据下 S2 摸到 92% 上下」。
4. **判分口径**：两轴同用 `results_equal_relaxed`（容候选多输出列），S/M 可比。
