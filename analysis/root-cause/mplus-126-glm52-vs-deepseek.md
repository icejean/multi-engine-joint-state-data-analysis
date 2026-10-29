# M+S M0 · 126 题 · glm-5.2 vs deepseek-v4-flash 模型对比

> 数据集：works_cycles（BIRD AdventureWorks，65 表 / ~74 万行）。题集：126 题全量（`question_set_final_obfuscated.json`）。
> 模式：M+S（`run_bench_wc_mplus.py`，一次性注入 schema.json + notes.md）。档位：M0（裸库 `works_cycles`，硬隔离）。
> 判分：`results_equal_relaxed`（放宽口径，允许多余列）。gold 一致，rescore 0 翻转。
> 模型：glm-5.2（openclaw 后端 `zai/glm-5.2`） vs deepseek-v4-flash（同链路历史 pass^4 终态）。
> 结果文件：`data/works_cycles/results_wc_mplus_126_glm52.json` / `results_wc_mplus_126_pass4.json`（+`results_wc_mplus_rerun_29_71.json`）。

---

## 一页速览

| 指标 | glm-5.2 | deepseek-v4-flash | Δ |
|---|---|---|---|
| EX（放宽） | 116/126 = **92.1%** | 123/126 = **97.6%** | **−5.5pp** ⬇ |
| EX（严格，无多余列） | 109/126 = 86.5% | 117/126 = 92.9% | −6.4pp |
| 失败题 | 10 | 3 | +7 |
| 带多余列 | 7 | 6 | +1 |
| 总 token | 22.92M | 36.35M | **−37%** ⬇ |
| 总成本 | $12.59 ≈ **90.6 元** | $1.68 ≈ 12.1 元 | **+7.5×** ⬆ |
| 均轮数 | 3.3 | 5.0 | −34% |
| 均耗时/题 | 55s | 40s | +37% |

**一句话结论**：glm-5.2 用 **37% 更少的 token** 跑完同一题库，却花了 **7.5 倍的钱**，准确率还低 5.5pp——「更省 token」换来的是「更早停手、更多错」，而 glm 的单价高 deepseek 近一个数量级，性价比全面落后。

---

## 1. 实验设置

与 `docs/mplus-26q-m0-report.md` 完全同链路、同资源文件（schema.json + notes.md）、同判分，唯一变量是**模型**：

- glm-5.2：`openclaw agent --model zai/glm-5.2`（zai / bigmodel 端点，单价与 glm-5.1 相同，见 §3）。
- deepseek-v4-flash：pass^4 全量 + Q29/Q71 notes 修复定向重跑（`results_wc_mplus_rerun_29_71.json` 两题均 pass），合成为「终态 123/126」。

M 档 → 库映射不变：M0 → `works_cycles`（裸库，65 表，无 sys 表）。两模型跑分均硬隔离 M0（注册表只留 `works_cycles`）。

---

## 2. 准确率对比

| 口径 | glm-5.2 | deepseek-v4-flash | Δ |
|---|---|---|---|
| EX（放宽） | 92.1% (116/126) | 97.6% (123/126) | −5.5pp |
| EX（严格） | 86.5% (109/126) | 92.9% (117/126) | −6.4pp |

### 2.1 domain 分布

| domain | glm-5.2 | deepseek-v4-flash |
|---|---|---|
| BOM（递归 CTE） | 5/6 | **6/6** |
| Geography | 7/7 | 7/7 |
| HR | 49/51 | **50/51** |
| Product | 19/21 | **21/21** |
| Purchasing | 13/14 | **14/14** |
| Sales | 23/27 | **25/27** |

glm-5.2 在 Product（−2）、Purchasing（−1）、Sales（−2）三个「多表 JOIN / 语义消歧」重灾区系统性落后；BOM/HR 各差 1 题。

### 2.2 失败题

- **3 题共享天花板**（两模型都挂）：`Q56 / Q90 / Q107`——pass^4 已定性的「样板题」（双口径歧义 + schema 间接），glm-5.2 同样摸不到，符合预期。
- **7 题 glm-5.2 独挂**（deepseek 做对、glm-5.2 做错）：`Q6, Q37, Q82, Q96, Q99, Q111, Q124`。
- **0 题 deepseek 独挂**：glm-5.2 通过集 ⊂ deepseek 通过集，被**严格支配**。

7 题独挂均为**语义答错**（有 final_sql、结果集与 gold 不符，非空答/超时/执行错误）。根因待逐题分析（见 §5 待办）。

---

## 3. 成本与 token 结构（核心发现）

### 3.1 token 总消耗

| | glm-5.2 | deepseek-v4-flash |
|---|---|---|
| input（未缓存） | 6,155,492（26.9%） | 4,545,645（12.5%） |
| output | 313,588（1.4%） | 618,968（1.7%） |
| cache_read（缓存读） | 16,455,360（**71.8%**） | 31,189,120（**85.8%**） |
| reasoning | 269,273 | 509,089 |
| **总（4 项）** | **22,924,440** | **36,353,733** |

glm-5.2 的 token 更省（−37%），但结构更「贵」：

- **input 更多**（6.16M vs 4.55M，+35%）：glm 的 prompt 缓存命中率更低，每题的未缓存输入更长。
- **cache_read 更少**（16.46M vs 31.19M）：deepseek 把 schema.json 的重复内容大量走缓存读，glm 走得更少。
- **output 更少**（0.31M vs 0.62M）：glm 推理更短、更早停手（与轮数 3.3 vs 5.0 呼应）。

### 3.2 成本

| | 单价（USD / 百万 token） | 本轮成本 |
|---|---|---|
| | input / output / cacheRead | |
| glm-5.2 | $1.2 / $4 / $0.24（= glm-5.1） | **$12.59 ≈ 90.6 元** |
| deepseek-v4-flash | $0.14 / $0.28 / $0.028 | $1.68 ≈ 12.1 元 |

glm-5.2 的 91 元（API Console 实付）可精确对上 glm-5.1 单价：

```
input       6.155M × $1.2  = $7.39
output      0.314M × $4.0  = $1.26
cache_read 16.455M × $0.24 = $3.95
────────────────────────────────
合计 ≈ $12.59 ≈ 90.6 元  ✓
```

**为什么「token 更少」却「花钱更多」**：差额完全来自**单价**，不是 token 量。glm-5.2 的 input 单价是 deepseek 的 **8.6 倍**（$1.2 vs $0.14），output 14.3 倍、cacheRead 8.6 倍；叠加 glm 的未缓存 input 占比更高（27% vs 12.5%，全按全价 $1.2 计），最终成本 7.5 倍。

> 注：deepseek 的 $1.68 是按其 openclaw.json 单价（$0.14/$0.28/$0.028）估算。此前「91 元是 deepseek 3 倍多」里的 deepseek ~30 元是 **M 轴**（纯自迭代探索，非本表口径）成本，不是 M+S 轴；M+S 轴 deepseek 成本更低（上表 $1.68 ≈ 12 元量级）。故 glm-5.2 对 deepseek 的 **M+S 轴成本比是 ~7.5×**，不是 ~3×。

### 3.3 效率 vs 准确率

| | glm-5.2 | deepseek-v4-flash |
|---|---|---|
| 均轮数 | 3.3 | 5.0 |
| 均耗时/题 | 55s | 40s |
| 元/题 | 0.72 | 0.10 |

glm-5.2 **收敛更快**（3.3 轮 vs 5.0 轮）但**生成更慢**（55s vs 40s，token 少反而慢，说明其推理吞吐低）。更早停手的代价是 7 题没探够就下了错误结论。

---

## 4. 结论

1. **准确率**：glm-5.2（92.1%）显著低于 deepseek-v4-flash（97.6%），被严格支配——它失败的 10 题里，deepseek 只有 3 题（共享天花板）也失败。
2. **成本**：glm-5.2 便宜在 token 量（−37%），贵在单价（约 8.6×）；净成本 7.5×，性价比明显落后。
3. **行为模式**：glm-5.2 是「快刀斩乱麻」型——轮数少、输出短、更早收敛，但草率；deepseek 是「多探几轮」型——token 多但更稳。
4. **可迁移结论**：在 M+S 一次性注入的机制下，**模型能力（而非元数据/机制）成为准确率瓶颈**；glm-5.2 的「少轮收敛」无法弥补其单发准确率缺口。

---

## 5. 待办

- [ ] **7 题独挂根因**（Q6/37/82/96/99/111/124）：区分「模型能力差」vs「M+S prompt 对 glm 有可调偏差点」，判断 glm-5.2 能否靠调教追平。
- [ ] （可选）跑 glm-5.2 的 **M 轴对照**（`run_bench_wc.py`）：deepseek 的 M 轴 ~30 元是纯探索口径，补一个 glm-5.2 M 轴才能凑齐「M vs M+S」四象限、看 glm 在纯探索下的成本/准确率。

> 已完成：glm-5.2 的 `cost_usd` 已回填进结果文件（$12.59/轮），`openclaw.json` 的 `zai/glm-5.2.cost` 已补成 glm-5.1 同款。
