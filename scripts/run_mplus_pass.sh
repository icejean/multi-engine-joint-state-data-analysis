#!/usr/bin/env bash
# M+S 模式全量 126 题 pass^3，只跑 M0 一档（元数据已一次性注入 schema.json+notes.md，无梯度差，M1/M2 不需要）。
# 结果写 results_wc_mplus_126_pass<N>.json。
# 硬隔离：每轮只把 works_cycles（裸库）注册进 .datasources.json，防 agent 越界到 _dict/_er。
# 用法: bash run_mplus_pass.sh 1
set -euo pipefail

PASS=${1:?用法: run_mplus_pass.sh <pass号>}

WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts
WC=$WS/dataai-test/data/works_cycles
MODEL=deepseek-v4-flash
RESULTS="results_wc_mplus_126_pass${PASS}.json"

cd "$WS"

TS=$(date +%Y%m%d_%H%M%S)
SNAPSHOT=".datasources.json.bak.${TS}"
cp -f .datasources.json "$SNAPSHOT"
echo "现场备份注册表 → $SNAPSHOT"
cp -f .datasources_m0.json .datasources.json
echo "注册表 → 只留 works_cycles（硬隔离 M0）: $(python3 -c "import json; print([e['name'] for e in json.load(open('.datasources.json'))['datasources']])")"

python3 "$SCRIPTS/run_bench_wc_mplus.py" --all --levels M0 --model "$MODEL" \
    --results "$RESULTS" --retry 2 --sleep 1

cp -f "$SNAPSHOT" .datasources.json
rm -f "$SNAPSHOT"
echo "已恢复注册表"

echo ""
echo "## 重判（防 gold 漂移）"
python3 "$SCRIPTS/rescore_wc.py" "$RESULTS"
echo ""
echo "✅ M+S pass${PASS} 完成: $WC/$RESULTS"
