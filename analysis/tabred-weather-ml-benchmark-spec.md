# TabReD weather ML benchmark SPEC（v0.2）

> 状态：**完成**（2026-10-15 Jean 拍板 ML benchmark = TabReD weather；2026-10-16 参考实验复现跑通、测试目标达成）。

## 0. 定位

承接 `paper-spec.md` §8 ML 行。ML 引擎 benchmark **定稿 = TabReD weather**（NYC taxi、法国 DVF 已退役）。

**产品定位（Jean 10-16）**：本测试验证的是 DataAI Portal 在**自然语言对话界面中 AI 辅助快速 ML 建模的效率**——尤其**百万、千万级记录以上**的建模效率。Portal 对话界面的价值 = 人指挥 Agent 从原始数据快速走通标准 ML 全流程；**调优是资深专家的高技能工作、另一维度，适合在交互式 IDE 中进行**——对话界面只承担「快速建出来、跑通」，不承担冲 SOTA。

**探索路径**：NYC taxi（tip R²0.62 主观行为 / fare 0.98 背计价器确定性 / payment 无意义）→ 法国 DVF（R²0.67 政府登记数据缺面积/装修富特征）→ **TabReD weather（R²0.85，千万级+富特征=最优解）**。

## 1. 数据集

- TabReD（Yandex Research，arXiv 2406.19380）weather 子集，**16,951,828 行 × 104 列（95 浮点特征）**。
- 目标 `fact_temperature`（实测气温）；特征 = `cmc_*`/`gfs_*` 气象预报场 + `fact_latitude`/`fact_longitude` + `topography_bathymetry`(海拔) + `sun_elevation` + `climate_*` 等。
- 时间跨度 2022-07-01 ~ 2023-07-30（13 个月，单年度周期）。
- 许可 **CC BY-NC-SA 4.0（非商用）**——写论文（学术）合规，Portal 商用 demo 禁用。

## 2. 复现协议（对齐 TabReD 论文）

- **切分**：时间切分（前 12 月训练 / 后 1 月测试 = 预测未来；随机切分泄漏虚高）。
- **指标**：回归报 **RMSE**（非 R²）。
- **调参**：TabReD 用 Optuna 100 轮；我们保持**默认参数**路线（Jean 方法论：默认参数跑通即可，调参是另一维度）。
- **种子**：TabReD 15 种子平均；我们暂 1 种子。

## 3. 结果（2026-10-16 完成，官方 canonical 口径）

LightGBM 300 树 / 全默认参 / seed=42 / 16 线程，**未调优**。官方切分：103 特征、11 月训练 + 2023-06 val / 2023-07 test（时间切分）。早期冒烟口径不同、已废弃：随机 80/20 RMSE 1.497 / R² 0.8525；10% 分层 12月/1月 RMSE 1.5124 / R² 0.8481。

| 规模 | train | val RMSE | test RMSE | test R² | test MAE | fit |
|---|---|---|---|---|---|---|
| 全量 100% | 13,625,138 | 1.6125 | **1.5450** | 0.8408 | 1.1426 | 346s |
| 10% 抽样 | 1,362,514 | 1.6198 | **1.5461** | 0.8409 | 1.1462 | 44s |
| TabReD LightGBM（2.5% + Optuna 100 轮 + 15 种子） | 605K | — | **1.4625** | — | — | — |

**关键发现：10% ≈ 全量**——test RMSE 差 0.0011 / R² 差 0.0001 / MAE 差 0.0036，数据 1.36M → 13.6M 几乎不动（**10% 已饱和**）。对「千万级效率」的意义：10% 抽样即可拿到全量答案、省 ~8× 算力。

**对标**：我们默认参数 vs TabReD 调参 SOTA **+5.6%**（差的就是「调参」那一层）；vs 本项目旧基线（全量 12 月训练 / 95 特征 / 无 val）1.5053 → +2.7%（差在官方切分少 1 月训练）。

**结论**：测试目标达成——Portal 自然语言对话界面 AI 辅助 ML 建模的效率（百万/千万级）已验证；调优是资深专家另一维度工作、不进对话。产物 = session 对话记录（`data/tabred/chat-31828136.html`）+ 脚本对。

**R 语言引擎（第四引擎，同一基准）**：rtorch GPU MLP 在 10% 抽样（1,696,406 行）跑通 test RMSE **1.5419°C**（略优于 TabReD paper MLP 15 次均值 1.547；非 beat LightGBM，GBDT 本压 deep model），Python CPU 对拍 1.5387。环境=GPU 笔记本 RTX 2060 6G（全量特征矩阵 6.8GB 放不下故 10% 抽样）。R 侧若补 GBDT 全量，内存与框架无关——mlr3 与 tidymodels（formula 路由）20% 抽样实测近乎打平（峰值 14.07 vs 14.70GB、25% 都 OOM），正路=改抽样 + float32 + free_raw_data。详见 [[dataai-r-engine-ml-plan]] + stateful-analysis-report §3.4。

## 4. 方法论（ML 与 SQL/Cypher benchmark 本质不同）

ML 是**人主导的交互式任务**——人指挥 Agent(LLM) 在 Portal 里每个环节直接写代码（探索→清洗→特征→建模→评估），走通标准 ML 流程即验证；**不是** autonomous pipeline 达 SOTA、没有 gold 结果集可比。产物 = session 对话记录 + 精简脚本对（`~/python/*_Pre.py`+`*_LGBM.py`）+ 指标。**调优是资深专家的高技能工作、另一维度，适合交互式 IDE**（对话界面只承担「快速建出来、跑通」，不承担冲 SOTA）。价值 = 快速建模的效率，尤其百万/千万级。

## 5. 领域洞察（Jean）

气温是年度周期的时间序列问题，多年数据应走季节 ARIMA 而非 LightGBM；但只有 13 个月=单周期，SARIMA 估不出季节性，故 LightGBM（用 `sun_elevation`/`climate_temperature` 精确编码年内季节位置）是对的。这也解释了时间漂移弱（随机 1.488 → 时间 1.512 仅 +0.024）：模型从 1 周期学到季节规律，预测后 1 月≈回忆去年同月季节基线 + 预报场校正天气扰动。weather 的真实难度不在时间泛化、在「预报场→实测温度」的偏差校正；真正吃时间漂移的是 cooking-time / delivery-eta / maps-routing。

## 6. 脚本与数据

- `scripts/spike_tabred_weather.py`——100 万抽样冒烟版。
- `scripts/spike_tabred_weather_full.py`——全量 + 时间切分版（笔记本 24G）。
- `scripts/spike_tabred_weather_full_mem12.py`——全量 + 内存优化加载版：两次流式读 + 预分配 float32 直接路由 train/test（原 full 版 `parts[]+pd.concat` 双份拷贝峰值 ~13GB → 此版 ~8GB），**12GB 机器可跑**，结果与 full 版一致。
- 数据：`data/tabred/weather.parquet`（3.57GB 全量，转笔记本）；云端留 `weather_10pct.parquet`（564MB 分层抽样）。
- 下载：Kaggle `pcovkrd84mejm/tabred-weather`，用 `KAGGLE_API_TOKEN`（KGAT_ bearer token，见 `.env`）。
