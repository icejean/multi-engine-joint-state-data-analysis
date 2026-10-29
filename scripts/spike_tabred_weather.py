#!/usr/bin/env python3
"""TabReD weather spike（流式版）：按行组读 + 列投影 + 抽 100 万行，避免整表载入 OOM。

用法：/usr/lib64/anaconda3/envs/graphrag/bin/python scripts/spike_tabred_weather.py
"""
import time
import resource
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from lightgbm import LGBMRegressor
from sklearn.metrics import r2_score, mean_squared_error

SRC = 'data/tabred/weather.parquet'
TARGET = 'fact_temperature'
EXCLUDE = {'fact_time', 'apply_time_rl', 'fact_station_id', TARGET}
SAMPLE = 1_000_000


def rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


f = pq.ParquetFile(SRC)
s = f.schema_arrow
feats = [n for n in s.names if n not in EXCLUDE and pa.types.is_floating(s.field(n).type)]
print(f'[schema] rows={f.metadata.num_rows:,} cols={len(s.names)} 特征(浮点)={len(feats)}')

p = SAMPLE / f.metadata.num_rows
rng = np.random.RandomState(42)
Xp, yp = [], []
t0 = time.time()
for batch in f.iter_batches(columns=feats + [TARGET], batch_size=300_000):
    d = batch.to_pandas()
    m = rng.random(len(d)) < p
    if m.sum():
        Xp.append(d.loc[m, feats].astype('float32'))
        yp.append(d.loc[m, TARGET].astype('float32'))
X = pd.concat(Xp, ignore_index=True)
y = pd.concat(yp, ignore_index=True)
print(f'[sample] {len(X):,} 行 | {time.time()-t0:.0f}s | rss={rss():.0f}MB')

idx = rng.permutation(len(X))
n = int(len(X) * 0.8)
m = LGBMRegressor(n_estimators=300, n_jobs=4, random_state=42, verbose=-1)
t0 = time.time()
m.fit(X.iloc[idx[:n]], y.iloc[idx[:n]])
pred = m.predict(X.iloc[idx[n:]])
dt = time.time() - t0
r2 = r2_score(y.iloc[idx[n:]], pred)
rmse = float(np.sqrt(mean_squared_error(y.iloc[idx[n:]], pred)))
print(f'[fit] train={n:,} test={len(X)-n:,} | {dt:.0f}s | rss={rss():.0f}MB')
print(f'[fact_temperature] R2={r2:.4f} | RMSE={rmse:.3f} °C')
imp = pd.Series(m.feature_importances_, index=feats).sort_values(ascending=False).head(8)
print('top 特征:', {k: round(v) for k, v in imp.items()})
