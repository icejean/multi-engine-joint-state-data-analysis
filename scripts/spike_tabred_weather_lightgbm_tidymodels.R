#!/usr/bin/env Rscript
# ======================================================================================
# spike_tabred_weather_lightgbm_tidymodels.R
#   TabReD weather · tidymodels + LightGBM 基准（抽样率可参数化）
#
# 抽样/切分与 mlr3 版完全一致（arrow 流式随机掩码 + 时间切分），只换建模框架。
# 模型：parsnip boost_tree(engine="lightgbm"，由 bonsai 提供)，trees=300 / num_leaves=31
#       / learn_rate=0.1 / seed=42，经 workflow() + add_formula() 拟合。
#
# 用法：
#   Rscript spike_tabred_weather_lightgbm_tidymodels.R 0.25     # 25% 抽样
#   Rscript spike_tabred_weather_lightgbm_tidymodels.R          # 默认 0.25
#
# ⚠️ 内存：tidymodels 的 formula 预处理（hardhat::mold）会把 data.frame 也复制成模型矩阵
#   （double），再加 bonsai → lgb.Dataset 的引擎格式，与 mlr3 一样有 2~3 份拷贝，
#   大数据集训练同样受限。25% 峰值 ~8GB，可跑。
# ======================================================================================

WORKDIR <- "/home/ubuntu/.dsh/workspace"
.libPaths(c(file.path(WORKDIR, "Rlibs"), .libPaths()))

suppressPackageStartupMessages({
  library(tidymodels)
  library(bonsai)          # 提供 boost_tree 的 lightgbm 引擎
  library(arrow)
  library(data.table)
})

# ------------------ 可调参数 ------------------
SRC          <- "/mnt/d/jeanye.cn/weather.parquet"
SAMPLE_FRAC  <- 0.25      # 抽样率：0.10/0.25/0.50…
SEED         <- 42L
N_ESTIMATORS <- 300L
N_THREADS    <- 16L
TARGET       <- "fact_temperature"
EXCLUDE      <- c("fact_time", "apply_time_rl", "fact_station_id", TARGET)
CUT          <- as.numeric(as.POSIXct("2023-07-01", tz = "UTC"))

ca <- commandArgs(trailingOnly = TRUE)
if (length(ca) >= 1) SAMPLE_FRAC <- as.numeric(ca[1])

t_start <- Sys.time()
cat(strrep("=", 78), "\nTabReD weather · tidymodels + LightGBM（抽样率参数化）\n", strrep("=", 78), "\n")

# ------------------ 1. 流式抽样（随机掩码，全时段均匀） ------------------
set.seed(SEED)
ds <- arrow::open_dataset(SRC)
nms <- ds$schema$names
types <- vapply(nms, function(x) ds$schema$GetFieldByName(x)$type$ToString(), character(1))
feats <- setdiff(nms[grepl("double|float", types, ignore.case = TRUE)], EXCLUDE)

t0 <- Sys.time()
reader <- Scanner$create(ds)$ToRecordBatchReader()
frames <- list()
repeat {
  b <- reader$read_next_batch()
  if (is.null(b)) break
  d <- as.data.frame(b)
  keep <- runif(nrow(d)) < SAMPLE_FRAC
  if (any(keep)) frames[[length(frames) + 1L]] <- d[keep, , drop = FALSE]
}
df <- data.table::rbindlist(frames)
rm(frames, reader, ds); invisible(gc())
cat(sprintf("[load] 抽样 %.0f%% → %s 行 × %d 列 | %d 特征 | %.0fs\n",
            SAMPLE_FRAC * 100, format(nrow(df), big.mark = ","), ncol(df),
            length(feats), as.numeric(difftime(Sys.time(), t0, units = "secs"))))

# ------------------ 2. 时间切分 ------------------
tsec <- as.numeric(df$fact_time)
tr <- which(tsec < CUT); te <- which(tsec >= CUT)
train_df <- df[tr, c(feats, TARGET), with = FALSE]
test_df  <- df[te, c(feats, TARGET), with = FALSE]
rm(df, tsec); invisible(gc())
cat(sprintf("[split] train=%s test=%s\n", format(nrow(train_df), big.mark = ","),
            format(nrow(test_df), big.mark = ",")))

# ------------------ 3. tidymodels 训练 ------------------
spec <- boost_tree(trees = N_ESTIMATORS, learn_rate = 0.1) %>%
  set_engine("lightgbm", num_threads = N_THREADS, seed = SEED, num_leaves = 31) %>%
  set_mode("regression")
wf <- workflow() %>%
  add_model(spec) %>%
  add_formula(reformulate(feats, response = TARGET))

t0 <- Sys.time()
fit <- wf %>% fit(train_df)
dt_fit <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
pred <- predict(fit, new_data = test_df)
truth <- test_df[[TARGET]]; p <- pred$.pred
rmse <- sqrt(mean((p - truth)^2)); mae <- mean(abs(p - truth))
rsq  <- 1 - sum((truth - p)^2) / sum((truth - mean(truth))^2)

cat(strrep("-", 78), "\n")
cat(sprintf("[fact_temperature] RMSE=%.4f°C | MAE=%.3f°C | R²=%.4f\n", rmse, mae, rsq))
cat(sprintf("[fit] 训练 %s 行 | %.0fs | 总耗时 %.1f 分钟\n", format(nrow(train_df), big.mark = ","),
            dt_fit, as.numeric(difftime(Sys.time(), t_start, units = "mins"))))
cat(sprintf("[mem] R Vcells 峰值 ≈ %.1f GB（仅 R 堆；LightGBM C++ 内存另计）\n",
            sum(gc()[, "max used"]) / 1024))

invisible(list(fit = fit, rmse = rmse, mae = mae, rsq = rsq, feats = feats))
