# REPLAY_GUIDE_tabred.md — TabReD weather（ML 方向，Python + R）复现指南

> 从零复现论文 §5.2 / §5.3 的 **TabReD weather** 机器学习实验：
> 数据获取 → Python LightGBM 全流程 → R（rtorch MLP + float32 直通道 GBDT）→ 结果对照。
> 这是「LLM × ML 乘法」的跨数据集复现（默认参数、非调参 SOTA 冲刺），与 SQL/Cypher 的「题/gold/判分」体系不同。
> 资产：`data/tabred/`、`scripts/`。

---

## 0. 定位与口径（先读）

- **数据域**：ML（表格回归），TabReD benchmark 的 `weather` 数据集（16,951,828 行 × 104 列，目标 `fact_temperature`）。
- **机制意义**：LLM 无法独自拟合千万行 GBDT；本实验证明「持久 kernel（Python/R）承接 LLM 语义指令、执行精确计算」的乘法成立——且跨数据集（TabReD）复现、跨引擎（Python/R）对齐。
- **诚实边界**：本实验用**默认参数**复现，**不冲调参 SOTA**（vs TabReD 论文调参 SOTA 落后 +5.6%）；调参是资深专家的高技能工作，属另一维度（论文 §5.2 诚实边界）。
- **运行环境**：全量 16.95M 峰值内存 ~7GB（Python）/ ~10.5GB（R GBDT），需在 24G 笔记本跑（本机 7.5G 跑不动）。

---

## 1. 数据源与下载

- **源**：TabReD（A Benchmark of Tabular Machine Learning in-the-Wild），数据集 `weather`。
  - 仓库：<https://github.com/yandex-research/tabred>
  - 下载：`uvx tabred download`（需 Kaggle 账号），得到 `weather.parquet`。
- **本仓库已含**：`data/tabred/chat-*.html`（5 个脱敏对话记录，展示对话驱动全流程）。
- **本仓库不含**：`weather.parquet`（原始数据，大）、`weather_10pct.parquet`（10% 抽样，由脚本生成）。

---

## 2. Python 全流程（LightGBM，全量）

```bash
# 全量 16.95M：float32 + 时间切分(train<2023-07-01 / test>=) + LightGBM 默认参
/usr/lib64/anaconda3/envs/graphrag/bin/python scripts/spike_tabred_weather_full.py
#   数据源 data/tabred/weather.parquet；目标 fact_temperature
#   结果：test RMSE 1.5450 / R² 0.8408（fit 346s）
```

- 相关脚本：`spike_tabred_weather_full_mem12.py`（12G 内存版）、`spike_tabred_weather.py`（10% 抽样冒烟）、`spike_tabred_weather_torch_fixed_10pct.py`（Python torch 10% 对拍）。

---

## 3. R GPU 深度学习（rtorch MLP，10% 抽样）

```bash
# 10% 抽样(1.7M) + MLP(3×256) + AdamW + MSE，default 时间切分；数据全程常驻显存
Rscript scripts/spike_tabred_weather_torch_10pct.R
#   结果：test RMSE 1.5419°C（5 epoch 3.3 min）；Python GPU 对拍 1.5387
```

- 10% 抽样：`weather_sample_10pct.py` 一次性落盘 `weather_10pct.parquet`（脚本检测缺失会自动调用）。
- 与 Python 版逐项对齐：N_EPOCHS=5、BATCH_SIZE=1024、N_BLOCKS=3、D_BLOCK=256、SEED=0、meta 列剔除 lat/lon/station_id。

---

## 4. R float32 直通道 GBDT（全量）

```bash
# 全量 16.95M：float32 直通道（C++ gbdt_float.cpp），峰值内存 ≤10GB
/usr/bin/time -v Rscript scripts/run_gbdt_float_full.R   # VmHWM 记峰值 RSS
#   结果：test RMSE 1.5449（峰值 10.56 GiB）
```

- 依赖：`scripts/gbdt_float.cpp`（Rcpp sourceCpp 编译）+ `scripts/spike_lgb_float32.cpp`（float32 LightGBM 冒烟）。

---

## 5. 结果对照

| 引擎 | 方案 | 数据 | 结果 |
|---|---|---|---|
| Python | LightGBM 默认参（全量） | 16.95M | RMSE 1.5450 / R² 0.8408 |
| Python（对拍） | torch MLP（10%） | 1.7M | RMSE 1.5387 |
| R | rtorch MLP（10%） | 1.7M | RMSE 1.5419°C |
| R | float32 直通道 GBDT（全量） | 16.95M | RMSE 1.5449（峰值 10.56 GiB） |

> 官方口径：TabReD weather 全量 test RMSE 1.5450 / R² 0.8408（默认参）；10% 抽样 ≈ 全量（差 0.0011，10% 已饱和）。精确数字以 `analysis/tabred-weather-ml-benchmark-spec.md` 与 chat 记录为准。

---

## 6. chat 日志（脱敏）

- `data/tabred/chat-*.html`（5 个）：对话驱动全流程的脱敏记录（密钥/密码/Token 已 [REDACTED]），展示「取数 → 探索 → 特征重建 → 10% → 全量」的对话式过程。

---

## 7. 相关文件清单

**数据（`data/tabred/`）**：`chat-*.html`（5 个脱敏对话）。

**脚本**：`scripts/{spike_tabred_weather_full,spike_tabred_weather_full_mem12,spike_tabred_weather,spike_tabred_weather_torch_fixed_10pct}.py` + `scripts/{spike_tabred_weather_torch_10pct,spike_tabred_weather_lightgbm_mlr3,spike_tabred_weather_lightgbm_tidymodels,run_gbdt_float_full}.R` + `scripts/{gbdt_float,spike_lgb_float32}.cpp`。

**说明**：原始 `weather.parquet` 从 TabReD 下载（Kaggle），不随仓。
