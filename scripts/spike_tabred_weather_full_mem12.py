#!/usr/bin/env python3
"""TabReD weather 全量版 · 12GB 机器可跑（内存优化加载，结果与原 full 脚本一致）。

与 spike_tabred_weather_full.py 的区别**只在加载**：
  原版 parts[] + pd.concat 在 concat 时双份拷贝 → 峰值 ~13GB → 12GB OOM。
  此版两次流式读 + 预分配 float32 数组直接路由 train/test → 峰值 ~8GB。
模型参数 / 时间切分 / 指标完全一致（LGBMRegressor n_estimators=300, n_jobs=-1, rs=42；
fact_time < 2023-07-01 为训练(前12月)、>= 为测试(后1月)）。

用法：cd dataai-test && /opt/venv311/bin/python scripts/spike_tabred_weather_full_mem12.py
"""
import time
import resource
import datetime
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from lightgbm import LGBMRegressor
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error

SRC = 'data/tabred/weather.parquet'
TARGET = 'fact_temperature'
EXCLUDE = {'fact_time', 'apply_time_rl', 'fact_station_id', TARGET}
SPLIT = int(datetime.datetime(2023, 7, 1, tzinfo=datetime.timezone.utc).timestamp())


def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


f = pq.ParquetFile(SRC)
s = f.schema_arrow
feats = [n for n in s.names if n not in EXCLUDE and pa.types.is_floating(s.field(n).type)]
n_rows = f.metadata.num_rows
cols = feats + [TARGET]          # 95 特征 + 目标，全是 float32
print(f'[schema] rows={n_rows:,} cols={len(s.names)} 特征(浮点)={len(feats)}')

# pass 1：只读 fact_time(int64)，统计 train/test 行数
t0 = time.time()
n_tr = n_te = 0
for batch in f.iter_batches(columns=['fact_time'], batch_size=1_000_000):
    t = batch.to_pandas()['fact_time'].to_numpy()
    n_tr += int((t < SPLIT).sum())
    n_te += int((t >= SPLIT).sum())
print(f'[pass1] train(前12月)={n_tr:,} test(后1月)={n_te:,} | {time.time()-t0:.0f}s')

# pass 2：预分配 float32，逐批按 fact_time 路由，避免 concat 双份拷贝
Xtr = np.empty((n_tr, len(feats)), dtype='float32')
ytr = np.empty(n_tr, dtype='float32')
Xte = np.empty((n_te, len(feats)), dtype='float32')
yte = np.empty(n_te, dtype='float32')
ptr_tr = ptr_te = 0
t0 = time.time()
for batch in f.iter_batches(columns=cols + ['fact_time'], batch_size=500_000):
    d = batch.to_pandas()
    t = d['fact_time'].to_numpy()
    arr = d[cols].to_numpy()          # (k, 96) float32
    m = t < SPLIT
    k_tr = int(m.sum())
    k_te = int((~m).sum())
    Xtr[ptr_tr:ptr_tr + k_tr] = arr[m, :-1]
    ytr[ptr_tr:ptr_tr + k_tr] = arr[m, -1]
    Xte[ptr_te:ptr_te + k_te] = arr[~m, :-1]
    yte[ptr_te:ptr_te + k_te] = arr[~m, -1]
    ptr_tr += k_tr
    ptr_te += k_te
del d, arr, t, m
print(f'[pass2] Xtr={Xtr.shape} Xte={Xte.shape} | {time.time()-t0:.0f}s | rss={rss():.0f}MB')
print(f'[split] train(前12月)={len(Xtr):,} test(后1月)={len(Xte):,} | rss={rss():.0f}MB')

m = LGBMRegressor(n_estimators=300, n_jobs=-1, random_state=42, verbose=-1)
t0 = time.time()
m.fit(Xtr, ytr)
dt = time.time() - t0
pred = m.predict(Xte)
rmse = float(np.sqrt(mean_squared_error(yte, pred)))
r2 = r2_score(yte, pred)
mae = float(mean_absolute_error(yte, pred))
print(f'[fit] train={len(Xtr):,} test={len(Xte):,} | {dt:.0f}s | rss={rss():.0f}MB')
print(f'[fact_temperature] RMSE={rmse:.4f}°C | R2={r2:.4f} | MAE={mae:.3f}°C')
print(f'[对标] TabReD LightGBM RMSE=1.4625（Optuna调参+15种子+605K）')
imp = {feats[i]: round(float(m.feature_importances_[i])) for i in np.argsort(m.feature_importances_)[::-1][:10]}
print('top 特征:', imp)
