#!/usr/bin/env python3
"""TabReD weather · PyTorch MLP 冒烟测试（自包含，镜像 paper/bin/nn_baselines.py 的 MLP）。

镜像 TabReD 官方的 PyTorch 深度学习例子，直接吃 weather.parquet 原始表：
  数据：TabReD weather.parquet（16.95M 行 × 104 列），目标 fact_temperature（回归）。
  预处理：镜像 preprocessing/weather.py —— 流式采样 → 按 fact_time 排序 → 生成时间特征
           → 拆 num/bin → default 时间切分（train<2023-06-01 / val 06-01..07-01 / test>=07-01）。
  模型：MLP（[Linear+ReLU+Dropout]×n_blocks + head Linear），AdamW，MSE（标签先标准化）。

与 TabReD 官方口径一致，两点提醒：
  ① fact_latitude/fact_longitude 当 meta 列剔除（官方口径），
     与 scripts/spike_tabred_weather_full_mem12.py 的 LightGBM 基准（当特征）不同；
     想让 DL 也吃到这两个特征，把 META 里的这两列去掉即可。
  ② 数值特征用 StandardScaler 标准化（官方 weather MLP 用 noisy-quantile，更慢更贴原文），
     冒烟测管线用 StandardScaler 足够；要复刻见文件末尾注释。

【本副本对原脚本的唯一改动 / FIX】原 scripts/spike_tabred_weather_torch.py 直接
`scaler.transform(X_num)`，而 weather 的 cmc_*/gfs_* 列含大量 NaN（预报不可用），
StandardScaler 会原样透传 → MLP 整行 NaN → train loss / RMSE 全为 nan。
官方 noisy-quantile 分支在 transform 后做 np.nan_to_num，本副本对齐该口径（NaN→0）。

依赖：torch（未装则先 /opt/venv311/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu）
用法：/opt/venv311/bin/python spike_tabred_weather_torch_fixed.py
"""
import datetime
import time
import math

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

try:
    import torch
    import torch.nn as nn
except ImportError:
    raise SystemExit(
        "torch 未安装，先执行：\n"
        "/opt/venv311/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu"
    )
from sklearn.preprocessing import StandardScaler

# ------------------ 可调参数（冒烟用小值，跑通后再放大） ------------------
SRC = '/mnt/d/jeanye.cn/weather.parquet'  # 你的 parquet 绝对路径（或 data/tabred/weather.parquet 软链）
SAMPLE_FRAC = 0.10      # paper 用 0.025(~424k 行)；冒烟 0.01(~170k) 更快
N_EPOCHS = 5            # paper 用 early-stopping(patience=16)；冒烟固定 5 轮
BATCH_SIZE = 1024
N_BLOCKS = 3            # paper: 1~4（tuned）
D_BLOCK = 256           # paper: 128~2048（tuned）
DROPOUT = 0.0
LR = 1e-3               # paper: 1e-5~1e-3（tuned）
WEIGHT_DECAY = 1e-5
SEED = 0

TARGET = 'fact_temperature'
# TabReD 官方把这几列当 meta 剔除（注意含 lat/lon，与 LightGBM 基准口径不同）
META = ['fact_time', 'apply_time_rl', 'fact_latitude', 'fact_longitude', 'fact_station_id']


def ts(y, m, d):
    return int(datetime.datetime(y, m, d, tzinfo=datetime.timezone.utc).timestamp())


# ------------------ 1. 流式采样（镜像 spike 的随机掩码法，避免整表 OOM） ------------------
f = pq.ParquetFile(SRC)
rng = np.random.RandomState(SEED)
frames = []
t0 = time.time()
for batch in f.iter_batches(batch_size=300_000):
    d = batch.to_pandas()
    m = rng.random(len(d)) < SAMPLE_FRAC
    if m.sum():
        frames.append(d.loc[m])
df = pd.concat(frames, ignore_index=True)
print(f'[load] 采样 {len(df):,} 行 | {time.time() - t0:.0f}s')

# ------------------ 2. 预处理（镜像 preprocessing/weather.py） ------------------
df = df.sort_values('fact_time').reset_index(drop=True)
dt = pd.to_datetime(df['fact_time'], unit='s')          # fact_time 是 unix 秒
df['day_of_week'] = dt.dt.weekday                       # 0=周一..6=周日
df['day_of_month'] = dt.dt.day
df['minute_of_day'] = dt.dt.hour * 60 + dt.dt.minute
df['hour_of_day'] = dt.dt.hour
df['month'] = dt.dt.month

bin_cols = [c for c in df.columns if 'available' in c and c != TARGET and c not in META]
num_cols = [c for c in df.columns if 'available' not in c and c != TARGET and c not in META]
print(f'[feat] num={len(num_cols)} bin={len(bin_cols)} (合计 {len(num_cols) + len(bin_cols)}，应≈103)')

X_num = df[num_cols].astype('float32').to_numpy()
X_bin = df[bin_cols].astype('float32').to_numpy()
y = df[TARGET].astype('float32').to_numpy()
t = df['fact_time'].to_numpy().astype('int64')

# ------------------ 3. default 时间切分 ------------------
train_mask = t < ts(2023, 6, 1)
val_mask = (t >= ts(2023, 6, 1)) & (t < ts(2023, 7, 1))
test_mask = t >= ts(2023, 7, 1)
print(f'[split] train={train_mask.sum():,} val={val_mask.sum():,} test={test_mask.sum():,}')

# ------------------ 4. 数值特征标准化 + 标签标准化 ------------------
# paper 对 weather MLP 用 num_policy="noisy-quantile"（QuantileTransformer+噪声，较慢）；
# 冒烟用 StandardScaler 更快、代码路径等价。想忠实复刻可替换为文件末尾注释里的版本。
# ⚠️ FIX：weather 的 cmc_*/gfs_* 特征在预报不可用处是 NaN（靠 *_available 表达缺失），
#    StandardScaler.transform 会把 NaN 原样透传，MLP 遇 NaN 整行输出 NaN、RMSE 变 nan。
#    官方 noisy-quantile 分支正是在 transform 后做 np.nan_to_num —— 这里对齐同一口径：
#    标准化后 NaN→0（即训练集均值），缺失信息仍由 bin 的 *_available 特征携带。
n_nan = int(np.isnan(X_num[train_mask]).sum())
scaler = StandardScaler().fit(X_num[train_mask])
X_num = np.nan_to_num(scaler.transform(X_num)).astype('float32')
print(f'[nan] 训练集特征 NaN={n_nan:,} → 标准化后置 0（官方 nan_to_num 口径）')
X = np.concatenate([X_num, X_bin], axis=1)

y_mean = float(y[train_mask].mean())   # 标签标准化（nn_baselines.py:274-277）
y_std = float(y[train_mask].std())
y_std = y_std if y_std > 1e-6 else 1.0


# ------------------ 5. MLP（镜像 paper MLP backbone） ------------------
class MLP(nn.Module):
    def __init__(self, d_in, n_blocks, d_block, dropout):
        super().__init__()
        self.blocks = nn.ModuleList([
            nn.Sequential(nn.Linear(d_block if i else d_in, d_block), nn.ReLU(), nn.Dropout(dropout))
            for i in range(n_blocks)
        ])
        self.head = nn.Linear(d_block, 1)

    def forward(self, x):
        for b in self.blocks:
            x = b(x)
        return self.head(x).squeeze(-1)


torch.manual_seed(SEED)
np.random.seed(SEED)
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f'[device] {device}')

model = MLP(X.shape[1], N_BLOCKS, D_BLOCK, DROPOUT).to(device)
opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
lossf = nn.MSELoss()
print(f'[model] 参数量={sum(p.numel() for p in model.parameters() if p.requires_grad):,}')

Xtr = torch.from_numpy(X[train_mask]).to(device)
ytr = torch.from_numpy(((y[train_mask] - y_mean) / y_std).astype('float32')).to(device)
Xva = torch.from_numpy(X[val_mask]).to(device)
Xte = torch.from_numpy(X[test_mask]).to(device)
n_tr = len(Xtr)


def rmse(pred_c, y_c):          # pred 已反标准化，直接算 °C
    return float(np.sqrt(np.mean((pred_c - y_c) ** 2)))


gen = torch.Generator(device=device).manual_seed(SEED)
for epoch in range(N_EPOCHS):
    model.train()
    perm = torch.randperm(n_tr, generator=gen, device=device)
    tot = 0.0
    for i in range(0, n_tr, BATCH_SIZE):
        idx = perm[i:i + BATCH_SIZE]
        opt.zero_grad()
        loss = lossf(model(Xtr[idx]), ytr[idx])
        loss.backward()
        opt.step()
        tot += loss.item() * len(idx)
    model.eval()
    with torch.inference_mode():
        pv = (model(Xva).cpu().numpy() * y_std) + y_mean
        pt = (model(Xte).cpu().numpy() * y_std) + y_mean
    print(f'epoch {epoch + 1}/{N_EPOCHS} | train loss={tot / n_tr:.5f} | '
          f'val RMSE={rmse(pv, y[val_mask]):.4f}°C | test RMSE={rmse(pt, y[test_mask]):.4f}°C')

print(f'\n[done] test RMSE = {rmse(pt, y[test_mask]):.4f}°C '
      f'(TabReD LightGBM 调参参考值 1.4625；冒烟小模型小样本，别指望对齐)')


# ======================================================================================
# 可选：忠实复刻 paper 的 noisy-quantile 数值预处理（替换上面第 4 段 StandardScaler）
# ======================================================================================
# from sklearn.preprocessing import QuantileTransformer
# q = QuantileTransformer(n_quantiles=max(min(n_tr // 30, 1000), 10),
#                         output_distribution='normal', subsample=1_000_000_000,
#                         random_state=SEED)
# Xnt = X_num[train_mask] + np.random.RandomState(SEED).normal(
#     0, 1e-5, X_num[train_mask].shape).astype('float32')
# q.fit(Xnt)
# X_num = np.nan_to_num(q.transform(X_num)).astype('float32')
