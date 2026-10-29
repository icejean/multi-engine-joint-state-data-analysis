#!/usr/bin/env bash
# M+S 模式全量 126 题，模型 glm-5.2（openclaw 后端 zai/glm-5.2）。
# 只跑 M0 一档（元数据已一次性注入 schema.json+notes.md，无梯度差，M1/M2 不需要）。
# 结果写 results_wc_mplus_126_glm52.json。
# 硬隔离：每轮只把 works_cycles（裸库）注册进 .datasources.json，防 agent 越界到 _dict/_er。
set -euo pipefail

WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts
WC=$WS/dataai-test/data/works_cycles
MODEL=zai/glm-5.2
RESULTS="results_wc_mplus_126_glm52.json"

cd "$WS"

TS=$(date +%Y%m%d_%H%M%S)
SNAPSHOT=".datasources.json.bak.${TS}"
cp -f .datasources.json "$SNAPSHOT"

# 无论成功/失败，退出前都要恢复注册表（后台任务，状态必须自愈）
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

echo ""
echo "## 重判（防 gold 漂移）"
python3 "$SCRIPTS/rescore_wc.py" "$RESULTS"
echo ""
echo "✅ M+S glm-5.2 全量完成: $WC/$RESULTS"
