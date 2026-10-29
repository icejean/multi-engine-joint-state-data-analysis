#!/usr/bin/env Rscript
# run_gbdt_float_full.R — 全量 16.95M TabReD 冒烟：验证 float32 直通道峰值内存 ≤10GB
#
# 与 run_gbdt_float_tabred_preprocess.R 同款逻辑，只把 SRC 换成全量 weather.parquet。
# 建议用 /usr/bin/time -v 包一层读 VmHWM（峰值 RSS）。

SRC      <- "/mnt/d/jeanye.cn/weather.parquet"
TARGET   <- "fact_temperature"
VAL_CUT  <- as.numeric(as.POSIXct("2023-06-01", tz = "UTC"))
TEST_CUT <- as.numeric(as.POSIXct("2023-07-01", tz = "UTC"))

Sys.setenv(PKG_LIBS = paste0(
  "/opt/micromamba/envs/r/lib/R/library/lightgbm/libs/lightgbm.so ",
  "-Wl,-rpath,/opt/micromamba/envs/r/lib/R/library/lightgbm/libs ",
  "-larrow -lparquet"
))
Rcpp::sourceCpp("/home/ubuntu/.dsh/workspace/gbdt_float.cpp")

tabred_preprocess <- function(chunk) {
  tt <- as.POSIXlt(chunk$fact_time, origin = "1970-01-01", tz = "UTC")
  chunk$day_of_week   <- (tt$wday + 6) %% 7
  chunk$day_of_month  <- tt$mday
  chunk$minute_of_day <- tt$hour * 60 + tt$min
  chunk$hour_of_day   <- tt$hour
  chunk$month         <- tt$mon + 1
  chunk[, !(names(chunk) %in% c("apply_time_rl", "fact_latitude", "fact_longitude", "fact_station_id"))]
}

t0 <- Sys.time()
fit <- gbdt_float_fit(
  source     = SRC,
  target     = TARGET,
  features   = NULL,
  split_col  = "fact_time",
  split_val  = c(VAL_CUT, TEST_CUT),
  preprocess = tabred_preprocess,
  scale      = "standard",
  params     = list(objective = "regression", num_leaves = 31L, learning_rate = 0.1,
                    num_threads = 16L),
  nrounds    = 300,
  seed       = 42
)
dt <- as.numeric(difftime(Sys.time(), t0, units = "secs"))

cat(strrep("=", 60), "\n")
cat("TabReD weather · 全量 16.95M · 回调 + 标准化 + 三段切分\n")
cat(strrep("=", 60), "\n")
cat(sprintf("行数=%s 特征=%d train=%s val=%s test=%s\n",
            format(fit$n, big.mark = ","), fit$nfeat,
            format(fit$ntrain, big.mark = ","), format(fit$nval, big.mark = ","),
            format(fit$ntest, big.mark = ",")))
cat(sprintf("val RMSE=%.4f°C | test RMSE=%.4f°C | MAE=%.3f°C | 耗时 %.0fs\n",
            fit$val_rmse, fit$rmse, fit$mae, dt))
cat(sprintf("[验收] test RMSE 应对齐 ~1.5450；峰值 VmHWM 应 ≤10GB\n"))
