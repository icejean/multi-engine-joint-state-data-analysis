# BIRD dev：deepseek-v4-pro vs deepseek-v4-flash 强模型测试

> 背景：financial 第 3 轮后，剩余 14 题（9 个非确定翻转 + 5 个硬/gold quirk）改用更强的 deepseek-v4-pro 单跑，验证「强模型能否救回」。

## 结果

| 指标 | flash（round3，这 14 题） | pro（单跑 14 题） |
|---|---|---|
| 通过 | 0/14（其中 9 题 round2 曾对过） | **2/14 = 14.3%** |
| 均耗时 | ~40s | **143s（3.5×）** |
| 美元/题 | ~$0.005 | **$0.077（15×）** |

pro 修复的 2 题：Q3（返回年份而非列名）、Q30（count 加权而非 amount 加权）。

## 失败两类

**① 和 flash 相同的基础错（notes 没帮 pro 更多）：**
- Q53 name vs id、Q61 DISTINCT、Q22 硬编码日期 —— pro 犯了和 flash **完全相同**的错。

**② pro 特有的过度探索（Q64 典型）：**
- Q64 跑了 **16 轮**，最后一条 SQL 是探索查询（`SELECT d.dstr_id, d.a2, ..., (子查询 COUNT)`），不是最终答案（`AVG(a15)`）。
- 「答完即止」判分取最后一条 SQL，pro 越彻底越容易停在探索语句上 → 反被扣分。

## 结论（对 paper 有价值）

1. **notes 是模型专属的** —— 所有 notes 都在 flash 上迭代调出，换 pro 后几乎不生效（pro 照样犯 name-vs-id / DISTINCT / 硬编码）。实证 paper-spec §3.5「模型专属规则（换模型微调，幅度随能力差）」。
2. **更强 ≠ 更适配此判分** —— pro 的「更彻底」（16 轮探索）与「答完即止、最后一条 SQL 定胜负」的口径**冲突**；flash 的「快而直」在此口径下占优。

同 works_cycles 的 glm-5.2 vs deepseek 发现一致：强模型不一定强，notes 需按模型重调。

## 数据

- pro 结果：`data/financial/results_fin_pro14.json`
- flash round3 结果：`data/financial/results_fin_round3.json`
- 模型：`--model deepseek-v4-pro --backend openclaw`（其余 harness/notes/gold 与 flash 完全一致）
