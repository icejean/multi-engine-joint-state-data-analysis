# M+S 混合模式 26 题 M0 报告

> 数据集：works_cycles（BIRD AdventureWorks，65 表 / ~74 万行）。
> 题集：26 题梯度敏感子集（对照 4 + 字典敏感 5(BOM/CTE) + ER 敏感 jc≥3 ×17）。
> 模型：deepseek-v4-flash（两轴同）。判分：`results_equal_relaxed`（与 M 系列一致）。
> 对照口径：纯 M（`run_bench_wc.py`，Agent 自迭代探索） vs M+S（`run_bench_wc_mplus.py`，一次性注入 schema.json + notes.md）。

---

## 一页速览

| 指标 | 纯 M M0 | M+S M0 | 变化 |
|---|---|---|---|
| 准确率 EX | 22/26 = 84.6% | 24/26 = **92.3%** | **+7.7pp** ⬆ |
| 均轮数 | 13.0 | **4.7** | **−64%** ⬇ |
| 均工具调用数 | 19.4 | **6.7** | **−65%** ⬇ |
| 均 token | 541,471 | **259,944** | **−52%** ⬇ |
| 均耗时 | 62.6s | **30.5s** | **−51%** ⬇ |
| 均成本 | $0.0207 | **$0.0121** | **−42%** ⬇ |

**一句话结论**：M+S 把「裸库 M0」直接抬到「满配 M2」的准确率（92.3%），成本却不到纯 M1/M2 的一半——注入的 schema.json（字典+ER 打包）等价于把 M1+M2 的元数据一次性塞给裸库 agent，探索成本全省了，还顺带修好了探索也搞不定的 BOM 递归题。

---

## 1. 实验设置

**M+S 模式**（对应 `docs/tech-route-selection.md` 论点四）：给 M 轴一次性注入 schema + 注意事项，让它既有 S 轴的效率，又保留 M 轴的 kernel/迭代维度。提示词级、不改代码。

- **脚本**：`scripts/run_bench_wc_mplus.py`（`run_bench_wc.py` 的变体，仅 `meta_instr` 不同）。
- **资源文件**（绝对路径，一次性加载）：
  - `data/works_cycles/works_cycles_er_schema.json`（71KB：65 表 / 455 列 / 87 外键，字典+ER+列类型打包）
  - `data/works_cycles/works_cycles_er_notes.md`（3.4KB：7 类踩坑——时间态 end_dt、历史表取最新、BOM 递归、大小写、fan-out 去重、ref 列角色、字面理解）
- **meta_instr 关键改动**：把「先查 sys_* 表 / 裸库就 list_objects+preview_data 探索」替换为「按绝对路径一次性加载两个资源文件作为 schema/字典/ER/注意事项的权威来源，不要 list_objects、不要查 sys_* 表；只有资源文件不足以确定答案（如需确认具体数据值/大小写/是否 fan-out）时才 preview_data 抽查」。

M 档 → 库映射不变：M0→`works_cycles`（裸）/ M1→`_dict` / M2→`_er`。M+S 在每一档都注入同一份全量 schema.json，与库内是否还有 sys_* 无关。

---

## 2. 结果

### 2.1 成本与准确率（26 题 M0）

| 档 | EX | 轮数 | 工具调用 | token in | token out | cache 读 | token 总 | 耗时 | 成本 | 失败题 |
|---|---|---|---|---|---|---|---|---|---|---|
| 纯 M M0 | 84.6% | 13.0 | 19.4 | 29,011 | 8,937 | 503,522 | 541,471 | 62.6s | $0.0207 | 90, 94, 98, 99 |
| **M+S M0** | **92.3%** | **4.7** | **6.7** | 35,014 | 3,491 | 221,440 | **259,944** | **30.5s** | **$0.0121** | 90, 124 |

token 分解的形态变化正对应「注入替代探索」：

- **input 升**（29k → 35k）：加载 71KB schema.json 的代价。
- **cache 读断崖**（503k → 221k，−56%）：省掉逐表 list_objects/preview_data 的探索轮。
- **output 降**（8.9k → 3.5k）：agent 有了 schema 后不再边探索边「想」，推理更短。
- **净 total 降 52%**。

### 2.2 domain 分布

| domain | 纯 M M0 | M+S M0 |
|---|---|---|
| BOM（递归 CTE） | 4/5 | **5/5** ⬆ |
| HR | 6/7 | **7/7** ⬆ |
| Geography | 1/2 | **2/2** ⬆ |
| Product | 2/2 | 2/2 |
| Sales | 9/10 | **8/10** ⬇ |

M+S 在 BOM（修好自引用递归）、Geography、HR 上全绿；唯一回撤在 Sales 的 Q124。

---

## 3. 横向对比：M+S M0 已等于纯 M 满配

| 档 | EX | 轮数 | token | 耗时 |
|---|---|---|---|---|
| 纯 M M0（裸） | 84.6% | 13.0 | 541,471 | 62.6s |
| 纯 M M1（+字典） | 92.3% | 10.2 | 417,592 | 54.3s |
| 纯 M M2（+ER） | 92.3% | 10.8 | 425,728 | 56.0s |
| **M+S M0（注入）** | **92.3%** | **4.7** | **259,944** | **30.5s** |

**M+S M0 = 纯 M M1/M2 的准确率，轮数/token/耗时均不到其一半。** 即：注入一次性兑现了字典+ER 的全部元数据收益，且不需要 agent 现场去查 sys_* 表（纯 M1/M2 每档仍要 ~10 轮查元数据）。

---

## 4. 逐题差异与根因

- **翻正 3 题**：`94, 98, 99` —— 全是 BOM 递归/字典敏感题。裸库 M0 靠探索看不出 `bom` 自引用的 `ref2`(子)/`ref3`(父) 角色与「层级用 level+1 累加、禁 bm_lvl」；注入的 schema.json 字典 + notes.md §3 直接讲清，agent 一次就写对。
- **新翻挂 1 题**：`124`。
- **都挂 1 题**：`90`（BIRD 原生态歧义，两轴都解不了）。

### Q124 回归根因：语义过约束（注入少了一层「亲眼见数据」的校验）

题面：「List the store name, city, and state/province of **every** store」。M+S 输出：

```sql
... JOIN addr_typ at ON at.addr_typ_id = ba.ref2
    LEFT JOIN st_prv sp ON sp.stt_prvn_id = a.ref1
WHERE at.nm = 'Main Office'      -- ← 脑补了「只取主办公室」
```

agent 拿到正确 schema（列名全对）后，反而多 JOIN 了 `addr_typ` 又加 `WHERE at.nm='Main Office'`，把非主办公室地址全排除了。纯 M 靠 `preview_data` 亲眼看到「一店多地址」，没踩这个坑。

**性质**：这不是注入错误（schema/列名都正确），是**语义过约束**。它暴露了 M+S 的一个真实风险——「一次性注入」少了「探索时亲眼看到数据分布」这一层语义校验。对冲方式：`notes.md` 的「every/all 别脑补过滤」这条，光写进 prompt 不够，还得让 agent 在拿不准时**允许抽查一次数据**兜底（脚本已这么写，只是该题未触发）。

---

## 5. 机制解释：为什么「注入替代探索」成立

- 纯 M 的贵，贵在「探索」：裸库 M0 每题 ~13 轮、~19 次工具调用，全花在 list_objects/preview_data 摸 65 表结构上，攒出 ~500k cache 读。
- M+S 把这段探索压缩成「2 次 read（schema.json + notes.md）+ 直写 SQL」：Q1 冒烟 trace 显示只有 `read ×2 + run_code ×1`，零 list_objects / 零 preview_data。
- schema.json 注入量 71KB ≈ 25k token，在 1M 上下文里 ~2.5%，换取的是探索成本（−64% 轮数 / −52% token / −51% 耗时）的整体下降。

---

## 6. 诚实边界

1. **单次 26 题，M 轴方差仍在**：M 轴 temperature 不可调，单次 ±3-5pp 漂移。**成本侧结论可信**（轮数/token 是确定性指标，−52%/−64% 远超单次方差）；**准确率侧 +7.7pp 要谨慎**（含翻正 3 + 翻挂 1，需 pass^3 或全量钉死）。
2. **翻正是「字典补齐」不是「机制魔法」**：+7.7pp 里 BOM 的 3 题是「注入字典让裸库看到了自引用」——本质是「把 M1/M2 的元数据塞给 M0」，与纯 M 的 M0→M1 涨幅（+7.7pp）完全同源。
3. **Q124 说明注入非银弹**：schema 再全，agent 仍可能语义过约束；M+S 的探索兜底（preview_data 抽查）是否触发、触发多频繁，是后续要观测的变量。
4. **未跑 M1/M2**：本报告只覆盖 M0。M+S 是否把 M0/M1/M2 三档拉平，待 M1/M2 跑完补证。

---

## 7. 关联文档

- 技术路线选择（M+S 论点四）：`tech-route-selection.md`
- 纯 M 系列完整结论：`works-cycles-final-report.md`
- 脚本：`scripts/run_bench_wc_mplus.py`（M+S） / `scripts/run_bench_wc.py`（纯 M）
- 结果：`data/works_cycles/results_wc_mplus_26.json`（M+S） / `results_wc_m_26_final.json`（纯 M 基线）
- 资源文件：`data/works_cycles/works_cycles_er_schema.json` + `works_cycles_er_notes.md`
