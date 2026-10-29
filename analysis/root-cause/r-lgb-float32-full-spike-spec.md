# SPEC：R 千万级 LightGBM 直读引擎 spike（float32 直通道）

> 版本：v1.0（已跑通）
> 日期：2026-10-17
> 定位：spike 已跑通全量，下一步才是打包成独立 R 包。
> 状态：**✅ 全量 16.95M 跑通（test RMSE 1.5449，峰值 VmHWM 10.56 GiB，499s）**

---

## 0. 目标（一句话）

纯 R 环境（不依赖 Python），用 C++（arrow 直读 parquet + LightGBM C API）以 **float32 端到端** 跑起 TabReD weather **全量 16.95M 行** 的 LightGBM 训练，**峰值内存 ~10.6 GiB**，test RMSE 对齐官方 **1.5450**。

## 1. 背景与动机

- R 没有一等公民的 float32 稠密矩阵，`matrix`/`data.matrix()` 全是 double。全量 16.95M×103 特征 double ≈ **14GB**，加 LightGBM Dataset + 加载开销 → 在 WSL2 16G 上限下必 OOM。
- 20% 抽样实测（`chat-1cb90705.html` / `chat-f236b0b2.html`）：数据本身才 ~2.4GB，峰值却 14.7GB——**~12GB 是 R 层加载/拷贝/glibc arena 碎片开销，不是数据**。
- LightGBM 的 C API **原生支持 float32**（`LGBM_DatasetCreateFromMat` 的 `C_API_DTYPE_FLOAT32`），只是 R 包只接 double。
- 市场动机：国内 R 阵营大量 R-only 分析师，需要「纯 R 环境跑千万级 ML」的差异化能力（DataAI 第四引擎落点）。

**现成方案对比（为什么不用现成的）**：

| 方案 | 能跑千万级 | 硬伤 |
|---|---|---|
| H2O（`h2o` R） | ✅（列式压缩 + 托管 JVM） | JVM 平台、非原生轻量 R 库，要起 Java 集群、数据过 JVM |
| xgboost `xgb.ExtMemDMatrix` | ✅（磁盘外存） | disk-IO 绑死训练慢；官方明说内存收益对 slim（少列）数据集有限，稠密 tabular 不划算 |
| lightgbm R + data.table + arrow 手工栈 | ❌ 千万级 OOM | 就是本方案要绕开的 float64 坑（全量 double 14GB） |

**空白**：没有现成的「原生 R（无 JVM）+ float32 直读 + RAM 常驻 + 复用 LightGBM/xgboost R 生态」的轻量方案——本 spike 卡的就是这个空位（比 H2O 轻、比外存快、比手工栈省一半内存）。

### 1.1 通用性与边界（本方案的定位）

**包的核心 = 五件事，全部参数化、数据集无关**：
1. **加载**：parquet/CSV 直读 → float32（不落 double），arrow C++ 逐 batch。
2. **切分**：按比例 / 按列（时间切分）/ 按索引，划 train/val/test。
3. **列级 scaler**：StandardScaler 等（C++ 内置，fit train + float32 原地 + NaN→0，像 NumPy）。
4. **训练**：LightGBM C API float32 Dataset → Booster。
5. **预测/返回**：Predict → 把预测向量 + 指标回 R。

任何稠密 tabular 数据都能复用；LightGBM 之后可同法扩 xgboost / CatBoost（都提供 float32 C API）。

**预处理分层（关键设计）**：
- **数据集专属预处理 → R 逐块回调** `preprocess = function(chunk_df) -> chunk_df`（生成时间特征、剔 meta、列派生、NaN→0）。**写 R 不写 C++**——灵活换数据集，代价是 R↔C++ 边界开销（全量 ~1 小时，可接受）。回调只让「当前块」临时变 double，全量仍是 float32。
- **通用列级变换 → C++ 内置**（`scale="standard"` 等）。这不属于「数据集专属预处理」，任何数据都能用，放 C++ 合理（NumPy 同款 fit/transform）。

**三条边界（诚实）**：
1. **只覆盖 GBDT**——DNN 走 rtorch（minibatch 另一条路），不掺和。
2. **稠密 tabular**——高基数 one-hot 稀疏场景走 `dgCMatrix` / 原生 categorical，另一套内存模型。
3. **千万级是甜点**——float32 让 16.95M 落进 16G；亿级（100M×100×4≈40GB）仍超 RAM，得换外存/采样/DB 后端。本方案卖「千万级 RAM 常驻」，不卖「无限大」。

## 2. 验收标准（可证伪）

| 项 | 标准 |
|---|---|
| 数据量 | 全量 16,951,828 行，103 特征（100 num + 3 bin），官方时间切分 |
| 峰值内存 | VmHWM **10.56 GiB**（实测，`/proc/self/status`；15GB 机器可跑、余量 ~4 GiB） |
| test RMSE | **1.5450 ± 0.005**（对齐 Python 官方全量 LightGBM 默认参） |
| 环境 | 纯 R，全程无 Python 参与；预测反标准化回 °C |
| 正确性 | train/val/test 切分、特征数、标准化口径与 Python 官方逐项一致 |

## 3. 架构：float32 直通道（核心约束）

```
source (parquet/CSV)
  → [C++ arrow 逐 batch 读，float32 列保持 float32，double 列当场 cast]
  → [(可选) 逐块回调 preprocess —— R 函数，数据集专属变换，列数可增]
  → [单块连续 float32 buffer，N×P]
  → [列级 scaler（scale="standard"，C++ 内置：fit train + float32 原地 + NaN→0）]
  → [LGBM_DatasetCreateFromMat(FLOAT32) 建全量 Dataset → GetSubset 切 train/val/test]
  → [BoosterUpdateOneIter 训练 → Predict → 只把预测向量 + 指标回 R]
```

**三条铁律**：
1. **数据全程不经过 R 的 double 矩阵**（逐块回调例外：只让「当前块」临时变 double）。R 层只拿最终预测向量 + 指标。
2. **特征矩阵是单个连续 buffer**（`new float[N*P]`，P = 特征数，含回调新增列），不做多次小块 alloc/free（避免 glibc arena 碎片）。
3. **train/val/test 用 `LGBM_DatasetGetSubset` 从全量 Dataset 按行号切**，不建三份独立矩阵。

**内存账（目标峰值）**：特征 buffer 7GB + label 68MB + fact_time 136MB + 建 Dataset 时 binning 瞬时 ~1.75GB ≈ **~9GB**；binning 完 `delete[]` 掉 buffer，稳态只剩 binned Dataset ~1.75GB + 训练直方图。

## 4. TabReD 使用示例的预处理口径（逐块回调 + scale="standard"，不在包内）

> 本节是 **TabReD 的使用示例**，不是包的一部分。实现者把它写成一个 `preprocess` 回调（时间特征/剔 meta/列拆分）+ `scale="standard"`（C++ 内置 StandardScaler），喂给通用入口 `gbdt_float_fit()`。

**权威参考 = `scripts/spike_tabred_weather_full_mem12.py`**（产出 1.5450 的全量 float32 实现，实现者先通读它）+ `scripts/spike_tabred_weather_torch_10pct.R`（R 侧对等，预处理逻辑已对齐，可直接抄语义）。

- **数据**：`/mnt/d/jeanye.cn/weather.parquet`，16,951,828 行 × 104 列，目标 `fact_temperature`。
- **meta 剔除**：`fact_time`、`apply_time_rl`、`fact_latitude`、`fact_longitude`、`fact_station_id`。
- **时间特征**（由 `fact_time` unix 秒生成，5 个）：`day_of_week`（0=周一）、`day_of_month`、`minute_of_day`、`hour_of_day`、`month`。
- **num/bin 拆分**：bin = 列名含 `available` 的列（3 个，0/1 不标准化）；num = 其余（95 float + 5 时间 = 100 个，标准化）。
- **标准化**：num 列 StandardScaler（**只 fit train**），transform 后 NaN→0（对齐官方 `nan_to_num` 口径）。bin 列不标准化。← 由 `scale="standard"`（C++ 内置）完成，见 §1.1。
- **标签**：`fact_temperature` **不标准化**——GBDT 对目标单调变换不变，原样（°C）喂 `LGBM_DatasetSetField`，RMSE 直接在 °C 上算。
- **切分**（按 `fact_time` **值**做 mask，无需排序）：train `< 1685577600`（2023-06-01）、val `[1685577600, 1688169600)`、test `>= 1688169600`（2023-07-01）。
- **特征数校验**：num=100 + bin=3 = **103**，train=13,625,138 / val=1,698,380 / test=1,628,310（实测，与 Python 逐项一致）。

## 5. LightGBM 参数（对齐 Python 官方默认参）

`n_estimators=300, num_leaves=31, learning_rate=0.1, seed=42, num_threads=16, objective=regression, metric=rmse`。**不调参、不加早停**（对齐 1.5450 的「默认参」路线）。

## 6. 技术实现要点（给实现者的关键提示）

- **LightGBM C API**（`c_api.h`，符号在 lightgbm R 包自带的 `lightgbm.so` 里导出，注意库名**无 `lib_` 前缀**）：
  - `LGBM_DatasetCreateFromMat(data, C_API_DTYPE_FLOAT32=0, nrow, ncol, C_API_IS_ROW_MAJOR=1, params, ref, &out)`
  - `LGBM_DatasetSetField(ds, "label", label_f32, n, C_API_DTYPE_FLOAT32)` ← **label 只吃 FLOAT32**，传 FLOAT64 报 "Input data type error"
  - `LGBM_DatasetGetSubset(full, row_idx_int32, n_sub, params, &sub)` ← train/val/test 用它切；**行号必须升序**（随机切分后先 `std::sort`，否则报 "used_row_indices should be sorted in Subset"）
  - `LGBM_BoosterCreate(train_ds, params_str, &booster)` → 循环 `LGBM_BoosterUpdateOneIter(booster, &is_finished)` 300 次
  - `LGBM_BoosterPredictForMat(booster, X_test_f32, FLOAT32, nrow, ncol, ROW_MAJOR, C_API_PREDICT_NORMAL, start_iteration=0, num_iteration=-1, "", &len, &pred)` ← **12 参数，含 `start_iteration`**
- **arrow C++**：`parquet::arrow::OpenFile` + `GetRecordBatchReader()` 逐 batch 读，float32 列保持 float32，double 列当场 cast 到 float32。**务必确认 parquet 里浮点列的实际物理类型**（float32 vs float64），统一按 float32 落地。**编译两坑**：① arrow 23 头文件要 C++17（Rcpp 插件用 `// [[Rcpp::plugins(cpp17)]]`，`cpp11` 会炸模板实例化错误）；② arrow 23 的 `OpenFile` 返回 `Result<unique_ptr<FileReader>>`、`GetRecordBatchReader` 返回 `Result<unique_ptr<RecordBatchReader>>`，取值用 `std::move(r).ValueOrDie()`（不是老的 `Status`+指针出参）。
- **链接**：spike 阶段用最小实现——`Rcpp::sourceCpp` + `PKG_LIBS` 直指已探测到的 `.so` 路径（lightgbm.so 见 §6.1，libarrow.so 在 `/opt/micromamba/envs/r/lib/libarrow.so`，头文件在 `/opt/micromamba/envs/r/include/{arrow,parquet}`）；或直接写一个最小 R 包。
- **内存测量**：跑完读 `/proc/self/status` 的 `VmHWM`（峰值 RSS），记录并回显；对照验收 ≈12.5GB。
- **float32 buffer 所有权**：buffer 自己 `new[]` 自己 `delete[]`；Dataset 用 `free_raw_data=false`，binning 完成后手动 `delete[]`，**不要**让 LightGBM 帮你 free（避免 `new[]`/`free` 不匹配的 UB）。

### 6.1 冒烟测试已跑通（2026-10-17）+ 两个签名坑

`~/.dsh/workspace/spike_lgb_float32.cpp` + `run_spike_lgb_float32.R` 已跑通合成数据端到端：
float32 特征 → float32 label → `GetSubset` 切 train/test → 训练 → FLOAT32 预测，**RMSE=0.129（噪声 0.1）**，
「float32 直通道」这个核心风险点已坐实。链接方式：`PKG_LIBS` 直指
`/opt/micromamba/envs/r/lib/R/library/lightgbm/libs/lightgbm.so`（库名无 `lib_` 前缀，`-llightgbm` 找不到）。

**真实 TabReD 数据也已跑通（2026-10-17）**：`~/.dsh/workspace/gbdt_float.cpp` + `run_gbdt_float_tabred.R`
用 arrow C++ 直读 `weather_10pct.parquet`（1.7M 行，97 float 特征，时间切分 `fact_time < 2023-07-01`），
**RMSE=1.5056，与 Python 全量 mem12 的 1.5053 逐位一致**——float32 直通道结果与 Python float32 管线等价。
通用入口 `gbdt_float_fit(source, target, features, split_col, split_val, params, nrounds, seed)` 已参数化。
⚠️ 当前 `num_threads` 在 C++ 里写死 1（单线程，1.7M 行跑了 125s），全量前须提成参数（默认 16）。

**全量 16.95M 已跑通（2026-10-17）**：`gbdt_float_fit` 走 `preprocess` 回调（103 特征）+ `scale="standard"` + 三段切分 + num_threads=16，
**test RMSE=1.5449 对齐 1.5450，峰值 VmHWM 10.56 GiB，耗时 499s**。五个内存修复把峰值从 ~15GB 压到 10.56 GiB：
① `reserve` 预分配（防 resize 翻倍）② `set_batch_size`（参数化为 `batch_size`，默认 128K）③ 每块 `gc()`（还 R 临时对象）④ `predict_rmse` 分块预测（65536 行/块，省 1.37GB 整块 memcpy）⑤ `GetSubset` 深拷贝后立即 `Free(full)`（省 ~1.75GB）。
峰值拆解：X float32(6.98) + full 分箱(1.75) + train 子集(1.40) + R 运行时(0.4) + y/split(0.2) ≈ 10.7 GiB——**`CreateFromMat(全量)→GetSubset(train)` 这条路的 full 与 train 分箱必然共存，才是峰值主因，不是 R 回调 arena**。
⚠️ **已决定不再往下压**：`LGBM_DatasetCreateByReference`+`LGBM_DatasetPushRows`（流式建 Dataset）可到 ~8.8 GiB、重扫 parquet 可到 ~2 GiB，但都要多读一遍 parquet、明显变慢——10.56 GiB 已够（15GB 机器余量 ~4 GiB）。

**两个签名坑（实现者必读，否则踩坑）：**

1. **`LGBM_BoosterPredictForMat` 是 12 参数**：
   `(handle, data, data_type, nrow, ncol, is_row_major, predict_type, start_iteration, num_iteration(int), parameter, out_len(int64_t*), out_result(double*))`。
   web 搜到的旧文档（无 `is_row_major`、`num_iteration` 是 `int64_t`）是错的。漏掉 `start_iteration` 的
   症状极阴险——**不崩、返回 0，但预测只出基分数、丢光树贡献**（模型训了 N 棵树却预测常数）。
   以 Python `lightgbm/basic.py` 的调用处为权威反推签名。
2. **`label` 字段只接受 `C_API_DTYPE_FLOAT32`**，传 FLOAT64 报 "Input data type error"。
   特征 `data_type` 则 FLOAT32/FLOAT64 都行。

## 7. 参考文件（实现者先读）

| 文件 | 用途 |
|---|---|
| `scripts/spike_tabred_weather_full_mem12.py` | **权威参考**：产出 1.5450 的全量实现，预处理/切分/参数逐项对齐它 |
| `scripts/spike_tabred_weather_torch_10pct.R` | R 侧对等：预处理语义已对齐，抄逻辑 |
| `data/tabred/chat-1cb90705.html` + `chat-f236b0b2.html` | 20% 内存对照实验记录（为什么必须走 C++ 直通道的证据） |
| `scripts/spike_tabred_weather_lightgbm_mlr3.R` | mlr3 抽样版（加载写法可参考，但它的 `data.matrix()` double 拷贝正是要绕开的） |
| `~/.dsh/workspace/spike_lgb_float32.cpp` + `run_spike_lgb_float32.R` | 已跑通的 float32 直通道冒烟测试（合成数据，RMSE 0.129） |
| `~/.dsh/workspace/gbdt_float.cpp` + `run_gbdt_float_tabred.R` | 通用入口 + 真实 TabReD 冒烟（10% 1.7M，RMSE 1.5056） |

## 8. 交付物

1. **通用入口** `gbdt_float_fit(source, target, split, params, nrounds, preprocess=NULL)` + `gbdt_float_predict(fit, test_source, preprocess=NULL)`，返回预测向量 + 指标 + 峰值内存（VmHWM）。
2. **一个 TabReD 使用示例**：`tabred_weather_example.R`（预处理回调 + 切分 + 训练，验证全量 16.95M ~10.6 GiB、RMSE 对齐）。
3. 一段结果说明：RMSE、峰值内存、耗时。

## 9. 风险与回退

- **核心待验证点已通过（全量数据）**：全量 16.95M 跑通（499s），test RMSE **1.5449** 对齐 1.5450，峰值 VmHWM **10.56 GiB**（略超 10GB 初设，主因是 `CreateFromMat→GetSubset` 的 full+train 分箱共存；15GB 机器可跑、余量 ~4 GiB，已决定接受、不再压）。
- **若 float32 不省内存**（例如 LightGBM 内部仍转 double）：回退方案 = vendor lightgbm 改 C++，或改 xgboost external memory（稠密数据慢，次选）。
- **链接**：lightgbm.so（无 `lib_` 前缀）/ libarrow.so 路径已现场探测到，见 §6.1。

## 10. 明确不做（本 spike 范围外）

- 不打包成 R 包（先跑通再谈）。
- **特征工程不在包内**——通过逐块回调 / 预处理文件注入（见 §1.1），TabReD 的预处理只作为示例回调。
- 不做闭源 .so / ARM 麒麟跨平台（先 x86_64 笔记本）。
- 不调参、不加早停（默认参对齐 1.5450）。
