#!/usr/bin/env Rscript
# ======================================================================================
# spike_tabred_weather_torch_10pct.R
#    TabReD weather · R (torch for R) MLP 冒烟测试 —— Python 版
#    spike_tabred_weather_torch_fixed_10pct.py 的 R 对等实现
#
# 数据：TabReD weather.parquet（16,951,828 行 × 104 列），目标 fact_temperature（回归）
#   抽样：10%（与 Python 版同款流式随机掩码，numpy RandomState(0)，逐 300k 行批）
#   预处理：按 fact_time 排序 → 生成 5 个时间特征 → 拆 num/bin
#           → default 时间切分（train<2023-06-01 / val 06-01..07-01 / test>=07-01）
#   → 数值特征 StandardScaler（NaN→0，对齐官方 noisy-quantile 的 nan_to_num 口径）
#   → 标签标准化
# 模型：MLP（[Linear+ReLU+Dropout]×n_blocks + head Linear），AdamW，MSE
#
# 与 Python 版逐项对齐：N_EPOCHS=5, BATCH_SIZE=1024, N_BLOCKS=3, D_BLOCK=256,
#   DROPOUT=0, LR=1e-3, WEIGHT_DECAY=1e-5, SEED=0, meta 列剔除 lat/lon/station_id
#
# R 侧说明：
#   • 10% 抽样由 weather_sample_10pct.py 一次性落盘 weather_10pct.parquet（本脚本
#     检测到缺失时会自动调用它），R 侧用 nanoparquet 读入后完全在 R 内做特征工程。
#   • 数据全程常驻显存（X float32 = 1.7M×103 ≈ 680MB），规避 R 端 DataLoader 开销。
#   • R 的逐 step 派发开销明显高于 PyTorch：batch=1024 时约 30~40 ms/step
#     （1 epoch ≈ 1330 步 ≈ 50s）；把 batch_size 调到 4096 可把 epoch 降到 ~15s。
#   • torch for R 0.17.0 / libtorch CUDA；本机 RTX 2060 6GB (sm_75)。
#
# 依赖：torch(0.17.0, R 自带)、nanoparquet(装在 workspace/Rlibs)
# 用法：
#   Rscript spike_tabred_weather_torch_10pct.R          # 命令行整跑
#   或在 Jupyter R kernel 中：source("spike_tabred_weather_torch_10pct.R"); main()
# ======================================================================================

WORKDIR <- "/home/ubuntu/.dsh/workspace"
.libPaths(c(file.path(WORKDIR, "Rlibs"), .libPaths()))

suppressPackageStartupMessages({
  library(torch)
  library(nanoparquet)
  library(matrixStats)
})

# ------------------ 可调参数（与 Python 版一致） ------------------
SRC_PARQUET   <- file.path(WORKDIR, "weather_10pct.parquet")
SAMPLE_SCRIPT <- file.path(WORKDIR, "weather_sample_10pct.py")
SAMPLE_FRAC   <- 0.10
N_EPOCHS      <- 5L
BATCH_SIZE    <- 1024L
N_BLOCKS      <- 3L
D_BLOCK       <- 256L
DROPOUT       <- 0.0
LR            <- 1e-3
WEIGHT_DECAY  <- 1e-5
SEED          <- 0L

TARGET <- "fact_temperature"
# TabReD 官方当 meta 剔除（含 lat/lon，与 LightGBM 基准口径不同）
META <- c("fact_time", "apply_time_rl", "fact_latitude", "fact_longitude", "fact_station_id")
CUT_VAL  <- as.numeric(as.POSIXct("2023-06-01", tz = "UTC"))   # unix 秒
CUT_TEST <- as.numeric(as.POSIXct("2023-07-01", tz = "UTC"))

# ------------------ MLP（镜像 paper MLP backbone） ------------------
MLP <- nn_module(
  "MLP",
  initialize = function(d_in, n_blocks, d_block, dropout) {
    self$blocks <- nn_module_list(lapply(seq_len(n_blocks), function(i) {
      nn_sequential(
        nn_linear(if (i == 1L) d_in else d_block, d_block),
        nn_relu(),
        nn_dropout(p = dropout)
      )
    }))
    self$head <- nn_linear(d_block, 1L)
  },
  forward = function(x) {
    for (i in seq_along(self$blocks)) x <- self$blocks[[i]](x)
    self$head(x)$squeeze(-1L)
  }
)

rmse_c <- function(pred, obs) sqrt(mean((pred - obs)^2))

# ======================================================================================
main <- function(sample_frac = SAMPLE_FRAC,
                 n_epochs    = N_EPOCHS,
                 batch_size  = BATCH_SIZE,
                 n_blocks    = N_BLOCKS,
                 d_block     = D_BLOCK,
                 dropout     = DROPOUT,
                 lr          = LR,
                 weight_decay = WEIGHT_DECAY,
                 seed        = SEED,
                 save_curve  = TRUE) {
  t_start <- Sys.time()
  cat(strrep("=", 78), "\n")
  cat("TabReD weather · R torch MLP 冒烟测试（10% 抽样）\n")
  cat(strrep("=", 78), "\n")

  # ---- 0. 设备 ----
  use_cuda <- cuda_is_available()
  device <- if (use_cuda) torch_device("cuda") else torch_device("cpu")
  cat(sprintf("[device] %s%s\n", if (use_cuda) "cuda" else "cpu",
              if (use_cuda) sprintf(" | %d 张卡", cuda_device_count()) else ""))

  # ---- 1. 数据（10% 抽样 parquet，缺失则调用 Python 流式抽样脚本） ----
  if (!file.exists(SRC_PARQUET)) {
    cat("[load] 未找到 10% 抽样文件，调用 weather_sample_10pct.py 生成…\n")
    if (!file.exists(SAMPLE_SCRIPT)) stop("缺少抽样脚本: ", SAMPLE_SCRIPT)
    st <- system2("/opt/venv311/bin/python", SAMPLE_SCRIPT)
    if (st != 0 || !file.exists(SRC_PARQUET)) stop("10% 抽样失败")
  }
  t0 <- Sys.time()
  df <- nanoparquet::read_parquet(SRC_PARQUET)
  cat(sprintf("[load] %s 行 × %d 列 | %.0fs\n", format(nrow(df), big.mark = ","),
              ncol(df), as.numeric(difftime(Sys.time(), t0, units = "secs"))))

  # ---- 2. 预处理（镜像 preprocessing/weather.py） ----
  df <- df[order(df$fact_time), , drop = FALSE]
  tt <- as.POSIXlt(df$fact_time, origin = "1970-01-01", tz = "UTC")   # fact_time 为 unix 秒
  df$day_of_week   <- (tt$wday + 6) %% 7      # 0=周一..6=周日（对齐 pandas weekday）
  df$day_of_month  <- tt$mday
  df$minute_of_day <- tt$hour * 60L + tt$min
  df$hour_of_day   <- tt$hour
  df$month         <- tt$mon + 1L

  bin_cols <- setdiff(grep("available", names(df), value = TRUE), c(TARGET, META))
  num_cols <- setdiff(names(df), c(bin_cols, TARGET, META))
  cat(sprintf("[feat] num=%d bin=%d (合计 %d，应≈103)\n", length(num_cols), length(bin_cols),
              length(num_cols) + length(bin_cols)))

  X_num <- as.matrix(df[, num_cols, drop = FALSE])
  X_bin <- as.matrix(df[, bin_cols, drop = FALSE])
  y     <- as.numeric(df[[TARGET]])
  tsec  <- as.numeric(df$fact_time)
  rm(df); gc(verbose = FALSE)

  # ---- 3. default 时间切分（数据已按 fact_time 排序，三段连续） ----
  tr_idx <- which(tsec <  CUT_VAL)
  va_idx <- which(tsec >= CUT_VAL & tsec < CUT_TEST)
  te_idx <- which(tsec >= CUT_TEST)
  cat(sprintf("[split] train=%s val=%s test=%s\n", format(length(tr_idx), big.mark = ","),
              format(length(va_idx), big.mark = ","), format(length(te_idx), big.mark = ",")))

  # ---- 4. 数值特征标准化（NaN 按列忽略；transform 后 NaN→0） ----
  Xtr <- X_num[tr_idx, , drop = FALSE]
  n_nan <- sum(is.na(Xtr))
  n_ok  <- nrow(Xtr) - colSums(is.na(Xtr))
  mu    <- colMeans(Xtr, na.rm = TRUE)
  s2    <- colVars(Xtr, na.rm = TRUE) * (n_ok - 1) / n_ok    # matrixStats 为 ddof=1，转 ddof=0
  sd_   <- sqrt(pmax(s2, 1e-12))
  rm(Xtr); gc(verbose = FALSE)
  cat(sprintf("[nan] 训练集特征 NaN=%s → 标准化后置 0（官方 nan_to_num 口径）\n",
              format(n_nan, big.mark = ",")))

  mu_t <- torch_tensor(mu,  dtype = torch_float32(), device = device)
  sd_t <- torch_tensor(sd_, dtype = torch_float32(), device = device)

  scale_num_to_gpu <- function(X, chunk = 400000L) {
    parts <- vector("list", ceiling(nrow(X) / chunk))
    for (i in seq_along(parts)) {
      r <- ((i - 1L) * chunk + 1L):min(i * chunk, nrow(X))
      xt <- torch_tensor(X[r, , drop = FALSE], dtype = torch_float32(), device = device)
      xt <- (xt - mu_t) / sd_t
      parts[[i]] <- xt$masked_fill(torch_isnan(xt), 0)      # NaN→0（=训练集均值）
    }
    torch_cat(parts, dim = 1L)
  }
  X <- torch_cat(list(scale_num_to_gpu(X_num),
                      torch_tensor(X_bin, dtype = torch_float32(), device = device)), dim = 2L)
  rm(X_num, X_bin); gc(verbose = FALSE)
  cat(sprintf("[tensor] X 常驻显存 %s | dtype=%s\n",
              paste(X$shape, collapse = "×"), X$dtype))

  # ---- 标签标准化（nn_baselines.py:274-277，numpy 的 ddof=0） ----
  y_tr <- y[tr_idx]
  y_mean <- mean(y_tr)
  y_std  <- sqrt(mean((y_tr - y_mean)^2))
  if (!is.finite(y_std) || y_std < 1e-6) y_std <- 1.0
  cat(sprintf("[label] mean=%.4f sd=%.4f\n", y_mean, y_std))

  # ⚠️ R torch 的 index_select / 张量下标是 1-based（不是原生 libtorch 的 0-based），
  #    torch_randperm 返回的 0-based 值要 +1 才能当位置用，全局行号也直接用 1-based。
  idx_gpu <- function(i) torch_tensor(as.integer(i), dtype = torch_int64(), device = device)
  tr_g <- idx_gpu(tr_idx); va_g <- idx_gpu(va_idx); te_g <- idx_gpu(te_idx)
  ytr_g <- torch_tensor(((y[tr_idx] - y_mean) / y_std), dtype = torch_float32(), device = device)

  # ---- 5. MLP + AdamW + MSE ----
  torch_manual_seed(seed)
  model <- MLP(X$shape[2], n_blocks, d_block, dropout)$to(device = device)
  opt   <- optim_adamw(model$parameters, lr = lr, weight_decay = weight_decay)
  n_par <- sum(vapply(model$parameters, function(p) p$numel(), numeric(1)))
  cat(sprintf("[model] MLP blocks=%d d_block=%d dropout=%.2f | 参数量=%s\n",
              n_blocks, d_block, dropout, format(n_par, big.mark = ",")))

  n_tr <- length(tr_idx)
  hist <- list(epoch = integer(), train_loss = numeric(), val_rmse = numeric(), test_rmse = numeric())

  torch_manual_seed(seed)          # 与 Python 的 gen=Generator().manual_seed(SEED) 对齐：全轮共用一条随机流
  for (epoch in seq_len(n_epochs)) {
    model$train()
    perm <- torch_randperm(n_tr, device = device) + 1L
    tot <- 0; n_seen <- 0L; t_ep <- Sys.time()
    for (i in seq(1L, n_tr, by = batch_size)) {
      j   <- min(i + batch_size - 1L, n_tr)
      pos <- perm[i:j]
      idx <- tr_g$index_select(1L, pos)
      opt$zero_grad()
      loss <- nnf_mse_loss(model(X$index_select(1L, idx)), ytr_g$index_select(1L, pos))
      loss$backward()
      opt$step()
      tot <- tot + loss$item() * (j - i + 1L)
      n_seen <- n_seen + (j - i + 1L)
    }
    model$eval()
    with_no_grad({
      pv <- as.numeric((model(X$index_select(1L, va_g)) * y_std + y_mean)$cpu())
      pt <- as.numeric((model(X$index_select(1L, te_g)) * y_std + y_mean)$cpu())
    })
    v_r <- rmse_c(pv, y[va_idx]); t_r <- rmse_c(pt, y[te_idx])
    hist$epoch <- c(hist$epoch, epoch); hist$train_loss <- c(hist$train_loss, tot / n_seen)
    hist$val_rmse <- c(hist$val_rmse, v_r); hist$test_rmse <- c(hist$test_rmse, t_r)
    cat(sprintf("epoch %d/%d | train loss=%.5f | val RMSE=%.4f°C | test RMSE=%.4f°C | %.0fs\n",
                epoch, n_epochs, tot / n_seen, v_r, t_r,
                as.numeric(difftime(Sys.time(), t_ep, units = "secs"))))
  }

  cat(sprintf("\n[done] test RMSE = %.4f°C（TabReD paper MLP 15 次均值 1.547；LightGBM 调参参考 1.4625）\n",
              tail(hist$test_rmse, 1)))
  cat(sprintf("[time] 总耗时 %.1f 分钟 | 设备 %s\n",
              as.numeric(difftime(Sys.time(), t_start, units = "mins")),
              if (use_cuda) "cuda" else "cpu"))

  # ---- 6. 训练曲线 ----
  if (save_curve) {
    try({
      suppressPackageStartupMessages(library(showtext))
      showtext_auto(); font_add("SimHei", "/usr/share/fonts/myfonts/simhei.ttf")
      png(file.path(WORKDIR, "weather_mlp_torch_R_curve.png"), width = 960, height = 560, res = 110)
      par(family = "SimHei", mar = c(4.2, 4.4, 3, 1.2))
      rng <- range(c(hist$val_rmse, hist$test_rmse))
      plot(hist$epoch, hist$val_rmse, type = "b", pch = 19, col = "#1f77b4", lwd = 2,
           ylim = rng, xlab = "epoch", ylab = "RMSE (°C)",
           main = "TabReD weather · R torch MLP（10% 抽样）")
      lines(hist$epoch, hist$test_rmse, type = "b", pch = 17, col = "#d62728", lwd = 2)
      legend("topright", c("val RMSE", "test RMSE"), col = c("#1f77b4", "#d62728"),
             pch = c(19, 17), lwd = 2, bty = "n")
      dev.off()
      cat("[plot] ", file.path(WORKDIR, "weather_mlp_torch_R_curve.png"), "\n", sep = "")
    }, silent = TRUE)
  }

  invisible(list(model = model, hist = hist, y_mean = y_mean, y_std = y_std,
                 num_cols = num_cols, bin_cols = bin_cols,
                 n_train = length(tr_idx), n_val = length(va_idx), n_test = length(te_idx)))
}

if (sys.nframe() == 0L) main()
