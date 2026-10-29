#!/usr/bin/env Rscript
# ======================================================================================
# spike_tabred_weather_lightgbm_mlr3.R
#   TabReD weather · mlr3 + LightGBM 基准（抽样率可参数化）
#
# 抽样：arrow 流式读全量表 → 随机掩码抽 SAMPLE_FRAC（全时段均匀，保持时间结构）
# 切分：fact_time < 2023-07-01 训练 / >= 测试
# 模型：mlr3 lrn("regr.lightgbm")，n_estimators=300 / num_leaves=31 / lr=0.1 / seed=42
#
# 用法：
#   Rscript spike_tabred_weather_lightgbm_mlr3.R 0.25     # 25% 抽样
#   Rscript spike_tabred_weather_lightgbm_mlr3.R          # 默认 0.25
#   （在 Jupyter R kernel 里 source() 则直接改下面的 SAMPLE_FRAC）
#
# ⚠️ 内存：mlr3 的 regr.lightgbm 会 data.matrix() 深拷贝 + free_raw_data=FALSE，
#   训练期每特征约 21 字节（backend double + 矩阵 double + 引擎 float32/分箱）。
#   实测上限约 550 万行（~30% 抽样）；25% 峰值 ~8GB，可跑。观察内存建议 `time -v`。
# ======================================================================================

WORKDIR <- "/home/ubuntu/.dsh/workspace"
.libPaths(c(file.path(WORKDIR, "Rlibs"), .libPaths()))

suppressPackageStartupMessages({
  library(mlr3)
  library(mlr3extralearners)
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
cat(strrep("=", 78), "\nTabReD weather · mlr3 + LightGBM（抽样率参数化）\n", strrep("=", 78), "\n")

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

# ------------------ 3. mlr3 训练 ------------------
task_train <- as_task_regr(train_df, target = TARGET, id = "weather")
task_test  <- as_task_regr(test_df,  target = TARGET, id = "weather_test")
learner <- lrn("regr.lightgbm",
               objective      = "regression",
               num_iterations = N_ESTIMATORS,
               learning_rate  = 0.1,
               num_leaves     = 31L,
               num_threads    = N_THREADS,
               seed           = SEED)
t0 <- Sys.time()
learner$train(task_train)
dt_fit <- as.numeric(difftime(Sys.time(), t0, units = "secs"))
pred <- learner$predict(task_test)
rmse <- pred$score(msr("regr.rmse")); mae <- pred$score(msr("regr.mae")); rsq <- pred$score(msr("regr.rsq"))

cat(strrep("-", 78), "\n")
cat(sprintf("[fact_temperature] RMSE=%.4f°C | MAE=%.3f°C | R²=%.4f\n", rmse, mae, rsq))
cat(sprintf("[fit] 训练 %s 行 | %.0fs | 总耗时 %.1f 分钟\n", format(nrow(train_df), big.mark = ","),
            dt_fit, as.numeric(difftime(Sys.time(), t_start, units = "mins"))))
cat(sprintf("[mem] R Vcells 峰值 ≈ %.1f GB（仅 R 堆；LightGBM C++ 内存另计）\n",
            sum(gc()[, "max used"]) / 1024))

invisible(list(learner = learner, rmse = rmse, mae = mae, rsq = rsq, feats = feats))
