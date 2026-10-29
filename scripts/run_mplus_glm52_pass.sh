#!/usr/bin/env bash
# M+S 模式全量 126 题 pass^3，模型 glm-5.2（zai/glm-5.2），P2-B2 用。
# 与 run_mplus_pass.sh（deepseek）同构，仅 MODEL 与结果文件名不同。
# 结果写 results_wc_mplus_126_glm52_pass<N>.json。
# 用法: bash run_mplus_glm52_pass.sh 1
set -euo pipefail

PASS=${1:?用法: run_mplus_glm52_pass.sh <pass号>}

WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts
WC=$WS/dataai-test/data/works_cycles
MODEL=zai/glm-5.2
RESULTS="results_wc_mplus_126_glm52_pass${PASS}.json"

cd "$WS"

TS=$(date +%Y%m%d_%H%M%S)
SNAPSHOT=".datasources.json.bak.${TS}"
cp -f .datasources.json "$SNAPSHOT"
restore() {
  cp -f "$SNAPSHOT" .datasources.json 2>/dev/null || true
  rm -f "$SNAPSHOT" 2>/dev/null || true
  echo "[trap] 已恢复注册表"
}
trap restore EXIT
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
echo "✅ M+S glm-5.2 pass${PASS} 完成: $WC/$RESULTS"
