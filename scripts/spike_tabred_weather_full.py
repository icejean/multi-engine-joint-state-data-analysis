#!/usr/bin/env python3
"""TabReD weather 全量版（笔记本 24G 跑）：整表 1695 万行 float32 + 时间切分(前12月/后1月) + LightGBM。

⚠️ 本机 7.5G 跑不动（全量峰值 ~7GB+），须在笔记本(16核24G)跑。
切分：fact_time < 2023-07-01 为训练(前12月)、>= 为测试(后1月)，报 RMSE 对标 TabReD LightGBM 1.4625。

用法：/usr/lib64/anaconda3/envs/graphrag/bin/python scripts/spike_tabred_weather_full.py
"""
import time
import resource
import datetime
import numpy as np
import pandas as pd
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
print(f'[schema] rows={f.metadata.num_rows:,} cols={len(s.names)} 特征(浮点)={len(feats)}')

# 逐批读 + 立即转 float32（fact_time 留 int64），避免整表 float64 的 ~13G 瞬态
parts = []
t0 = time.time()
for batch in f.iter_batches(columns=feats + [TARGET, 'fact_time'], batch_size=500_000):
    d = batch.to_pandas()
    d[feats + [TARGET]] = d[feats + [TARGET]].astype('float32')
    parts.append(d)
df = pd.concat(parts, ignore_index=True)
del parts
print(f'[load] {df.shape} float32 | {time.time()-t0:.0f}s | rss={rss():.0f}MB')

# 时间切分：前 12 月训练 / 后 1 月测试
tr = df[df['fact_time'] < SPLIT]
te = df[df['fact_time'] >= SPLIT]
print(f'[split] train(前12月)={len(tr):,} test(后1月)={len(te):,}')
Xtr, ytr = tr[feats], tr[TARGET]
Xte, yte = te[feats], te[TARGET]
del df, tr, te

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
imp = pd.Series(m.feature_importances_, index=feats).sort_values(ascending=False).head(10)
print('top 特征:', {k: round(v) for k, v in imp.items()})
