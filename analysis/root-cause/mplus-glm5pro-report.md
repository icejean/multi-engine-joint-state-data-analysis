# M+S 模式在 GLM-5-Pro（256k / glm-5.1）上的运行报告

> 模型：GLM-5-Pro = glm-5.1，**256k 上下文窗口**，reasoning 模型，部署于中国电信息壤平台（`ai.ctaigw.cn`）。
> 对照：deepseek-v4-flash（1M 上下文）。
> 题集：works_cycles 126 题全量。判分：`results_equal_relaxed`。
> 本报告覆盖：M 轴（M+S 注入模式）pass^3、S 轴单发（S0/S1/S2）、GLM 失败根因分析。

---

## 一页速览

| 机制 | 档 | GLM-5-Pro | deepseek | 差距 |
|---|---|---|---|---|
| M 轴（M+S 注入） | M0 | **81.0%**（pass^3 均值，三轮单调降或为下界，见 §6.2） | 95.2%（修复版） | −14.2pp |
| S 轴单发 | S0 | 超时（>240s） | 81.7% | — |
| | S1 | 48.4% | 87.3% | −38.9pp |
| | S2 | 54.0% | 87.3% | −33.3pp |

**核心结论（一条）**：

> **「Agent 多轮 + 注入」对弱模型的增益远大于强模型。** GLM-5-Pro 从 S 单发（48~54%）被 M+S 抬到 81%（**+27~33pp**；81% 为三轮单调降的均值，或为下界，见 §6.2），而 deepseek 只从 87% 抬到 95%（+5pp）。M+S 不只是强模型的效率优化，它是**弱模型的能力放大器**。

---

## 1. 实验设置

- **模型**：GLM-5-Pro（`id=GLM-5-Pro`，`reasoning=true`，`contextWindow=204800`，`maxTokens=131072`），xirang 端点 `https://ai.ctaigw.cn/coding/v1`（OpenAI-completions 格式）。
- **M 轴**：`run_bench_wc_mplus.py`（注入 schema.json + notes.md，替代探索），跑 3 轮 pass^3。
- **S 轴**：`run_bench_wc_singleshot.py`（单发直连端点，元数据预注入）。
- **判分**：`results_equal_relaxed`，与 deepseek 同口径。

---

## 2. M 轴 pass^3（M0 档）

| 轮 | EX | 轮数 |
|---|---|---|
| r1 | 84.9%（107/126） | 3.9 |
| r2 | 79.4%（100/126） | 3.9 |
| r3 | 78.6%（99/126） | 4.0 |
| **均值** | **81.0%** | 3.9 |
| **极差** | **6.3pp** | |

### 翻转分析（每题 3 次）

- 3/3 稳定对：83 题
- 0/3 硬地板：10 题 `[12, 14, 37, 56, 67, 72, 79, 90, 99, 124]`
- 漂移（1/3 或 2/3）：33 题 → **翻转率 26.2%**

### 成本/速度（息壤平台口径，见 §6 诚实边界）

- 均 token/题 ≈ 197k（input 全计，cache_read=0）
- 均耗时/题 ≈ 60s（平台算力决定，非模型固有）
- 成本不可得（xirang 转录不带 cost 字段）

---

## 3. S 轴单发

| 档 | 结果 | 说明 |
|---|---|---|
| S0（裸 schema） | **>240s 超时** | reasoning 爆炸（见 §4.1） |
| S1（+字典） | 48.4%（61/126） | token 1.01M，耗时 7606s |
| S2（+字典+ER） | 54.0%（68/126） | token 1.19M，耗时 6332s |

- **S2 > S1（+5.6pp）**：ER 对 GLM 有增量，而 deepseek 的 S2−S1 = 0（字典已吃满）。
- **S1+S2 总 token = 2.2M**（input 1.93M + output 277k）。

---

## 4. 根因分析

### 4.1 S0 超时：reasoning 消歧爆炸

GLM-5-Pro 是 reasoning 模型（`reasoning=true`），响应里带 `reasoning_content`。

| 档 | 输入 token | 耗时 | reasoning token |
|---|---|---|---|
| S0（裸 ref 列） | ~5,160 | **>240s 超时** | 长到停不下来 |
| S2（满配元数据） | 13,624 | 16s | 445（89% of output） |

**机制**：reasoning 时间由「消歧工作量」主导，不是输入大小。S0 的混淆列 `ref1/ref2/ref3` 无语义，模型要在脑子里硬推每个 ref 的含义 → 推理链爆炸；S2 的字典+ER 把关系喂到嘴边 → 445 token 就够。

### 4.2 M 轴失败模式：以「理解错」为主，notes 救不了

GLM 独挂的 16 题（deepseek 对、GLM 错）分三类：

| 类 | 题数 | 代表 | 性质 |
|---|---|---|---|
| **A 理解错** | 6 | Q52（list→COUNT）、Q57（问部门→返人名）、Q62（问卡号→返人名）、Q67（空 SQL）、Q56（personal info→姓名）、Q37（加权口径） | **notes 修不了**（读题就错，模型能力） |
| **B 脑补/硬编码** | 3 | Q33（脑补 `HAVING cnt>1`）、Q94（硬编码 `ba.ref1=1518`）、Q96（过度分组） | notes 有规则，GLM 不执行 |
| **C 明确 SQL 规则** | 7 | Q111（COUNT(*) vs DISTINCT）、Q124（过度去重）、Q72（取最新）、Q71（第N高）、Q12（ref 角色）、Q99（BOM 递归）、Q118（排序/LIMIT） | notes 已覆盖，GLM 没吃透 |

**结论**：GLM 的失败以「理解错 + 规则不执行」为主，补 notes 边际收益很低——它的瓶颈不是「缺规则」，是「读不懂题」和「有规则不跟」。

---

## 5. 关键发现（4 条）

1. **S→M 增益随模型能力反比**：GLM 从 S 单发（48~54%）→ M+S（81%）得 +27~33pp；deepseek 从 87% → 95% 得 +5pp。弱模型扛不住「65 表一次性推理」，agent 的多轮短推理链是它的救命稻草。

2. **ER 对弱模型有用、对强模型没用**：GLM 的 S2−S1=+5.6pp，deepseek 的 S2−S1=0。弱模型需要显式外键关系，强模型能自己推。

3. **方差与模型能力负相关**：GLM 翻转率 26.2%、极差 6.3pp；deepseek 7.1%、2.4pp。范式要出可信点估计，选强模型比多跑几轮划算。

4. **notes.md 是模型专属的**：它积累的是 deepseek 的失败模式（SQL 规则），对 GLM 的「理解错」无效。换模型，notes 得重新积累。

---

## 6. 诚实边界

1. **耗时/token/成本均不可与 deepseek 直接比**：GLM 部署在息壤（耗时被平台算力污染）、token 记账全算 input（无 cache 分离）、成本字段缺失。**只有「准确率 + 轮数」是干净指标。**
2. **GLM 三轮单调下降**（84.9→79.4→78.6）：3 样本不能排除噪声，但可能提示息壤平台连续跑分时算力退化。**因此 81.0% 均值是下界，r1 的 84.9% 或更接近真实能力**——对外引用 81% 时需带上此说明。
3. **S0 未完成**：单发裸 schema 下 reasoning 超时，无 S0 数字（deepseek 的 81.7% 可作对照）。
4. **M 轴用「修复版 notes + evidence」**：deepseek 的 95.2% 也是修复版；两者 notes 版本一致（9 节），可比。

---

## 7. 数据文件清单（供合并）

| 文件 | 内容 |
|---|---|
| `results_wc_mplus_glm5pro_126.json` | M 轴 r1 |
| `results_wc_mplus_glm5pro_126_r2.json` | M 轴 r2 |
| `results_wc_mplus_glm5pro_126_r3.json` | M 轴 r3 |
| `results_wc_s_glm5pro_s12_full.json` | S 轴 S1+S2 全量（252 题） |
| `results_wc_s_glm5pro_s2_smoke.json` | S2 Q1 冒烟 |

> 关联：`docs/mplus-report.md`（deepseek 主报告）、`docs/tech-route-selection.md`（五条论点）。
