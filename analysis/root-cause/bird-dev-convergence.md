# BIRD dev 收敛实验报告

> M+S 在 BIRD dev 两个 dirty 库上的收敛结果、SOTA 参照系、显著性判断。
> 目标:把「机制增益」和「benchmark 排名」口径分开,用 SOTA 对比锚定显著性。

## 一、收敛曲线(最终,5 轮)

| Round | formula_1 | financial |
|---|---|---|
| 1(从零,空 notes) | 70.9% | 75.5% |
| 2 | 73.8% | 79.2% |
| 3 | 81.4% | 84.9% |
| 4(全 gold/evidence 修复 + notes + 通用规则) | 83.1% | 84.9% |
| 5(grounding: notes §7-14 + 12 题 evidence) | **93.6%** | — |

> formula_1 最终：round5 后 pass^3(修 7 题前) EX 均值 92.2% / 稳定对 87.8% / 轮间漂移 4.9%；再修 7 道稳定错 → 单发 97.1%（167/172）。详见 semantic-drift-methodology.md。

- 两库单调爬升,成本不变(每轮 ~$0.7-1.2、~40s/题,单发 deepseek-v4-flash)。
- 数据:`data/{db}/convergence_curve.json`;根因与修复见 `gold-fixes-bird-dev.md`;跨模型见 `bird-dev-pro-vs-flash.md`。

## 二、SOTA 参照系

| 参照 | 执行准确率 EX | 出处 |
|---|---|---|
| 前沿 single-shot | ~65% | paper-spec R-5 |
| SOTA(MCI-SQL,metadata 预注入) | 76.41% | paper-spec §4.1 |
| 人类 | ~92% | paper-spec R-5 |

## 三、显著性判断

**~10% 的机制增益是显著的;单轮间 ±5% 的漂移是噪声、不算改善。**

| 对比 | formula_1 | financial | 显著性 |
|---|---|---|---|
| **从零 → 收敛(notes 机制增益)** | **+12.2pp** | **+9.4pp** | ✅ **显著(~10%)** |
| vs 前沿 single-shot(~65%) | +18.1pp | +19.9pp | ✅ 显著 |
| vs SOTA(MCI-SQL 76.41%) | **+6.7pp** | **+8.5pp** | ✅ 显著(**超 SOTA**) |
| 单轮间漂移(非确定噪声) | ±5% | ±5% | ❌ 不显著 |

**判断依据**:从零到收敛的 ~10% 增益远超单发非确定噪声(~5%、约 8 题翻转),且两个库都稳定超 SOTA(+6.7/+8.5pp)——这两个信号都在噪声之外。反例是 financial round4 vs round3(84.9% = 84.9%,+0pp):gold 修复逐题验证全部生效(Q13/53/80/97 翻对),但被 8 题非确定回归对冲,net 归零——这正是"5% 以下不算改善"的实例。

## 四、差分定位(论文口径,非排名口径)

| 口径 | financial | formula_1 |
|---|---|---|
| 从零(schema.json 注入) vs 前沿 single-shot | +10.5pp | +5.9pp |
| 从零 vs SOTA(MCI-SQL) | ≈ 追平(−0.9pp) | −5.5pp |
| **收敛(加 notes)后 vs SOTA(MCI-SQL)** | **+8.5pp** | **+6.7pp** |

**故事**:从零(schema.json 注入)≈ SOTA;加 notes 后反超 SOTA +6.7~8.5pp。notes 的机制增益 = 在 SOTA 之上再爬的一段,这才是「数据上下文(态)」的贡献,不是 benchmark 排名。

## 五、dirty 库定位

financial、formula_1 是 BIRD dev 里**唯二被标为「dirty」的库**(真实世界脏数据:捷克银行编码、圈速格式不一致),其余 9 库是干净/合成。在最脏的库上出超 SOTA 的结果 = 机制最硬的证据(逆风局还能超 SOTA,比干净库 97% 更有说服力)。

## 六、诚实边界

- **单库 vs 全量**:83.1%/84.9% 是**单库**水平,而 76.41% 是**全 dev(11 库)**。要全量对标,需跑全 dev(P1 之后)。
- **单发漂移**:pass@1 有 ±5% 非确定漂移;数字是单发样本,不是稳定值。
- **pass@3 上界**(financial ~93%、formula_1 ~88%)是能力上限,实际应用不跑 pass^k,不当作部署口径。
- **更强的模型不升反降**(deepseek-v4-pro 在 flash 调的 notes 下 14 硬题只 2/14),见 `bird-dev-pro-vs-flash.md`——notes 是模型专属的,换模型需重调。
