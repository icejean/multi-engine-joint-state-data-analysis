#!/usr/bin/env bash
# 干净 pilot 6×3 元数据梯度 —— 硬隔离版。
# 每批只把「单个 works_cycles 库」注册进 .datasources.json，批间换文件；
# 跑完恢复原注册表。结果统一写 results_wc_pilot_clean.json（断点续跑）。
set -euo pipefail

WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts
RESULTS=results_wc_pilot_clean.json
IDS="1,26,33,88,99,113"

cd "$WS"
RESTORE=$(ls -t .datasources.json.bak.* 2>/dev/null | head -1)
[ -n "$RESTORE" ] || { echo "❌ 找不到备份文件，终止"; exit 1; }
echo "恢复目标: $RESTORE"

for LVL in M0 M1 M2; do
  case $LVL in
    M0) ISO=.datasources_m0.json ;;
    M1) ISO=.datasources_m1.json ;;
    M2) ISO=.datasources_m2.json ;;
  esac
  echo ""
  echo "############################################################"
  echo "## 批次 $LVL —— 注册表: $ISO"
  echo "############################################################"
  cp -f "$ISO" .datasources.json
  echo "注册的数据源: $(python3 -c "import json; print([e['name'] for e in json.load(open('.datasources.json'))['datasources']])")"
  python3 "$SCRIPTS/run_bench_wc.py" --ids "$IDS" --levels "$LVL" --results "$RESULTS"
done

echo ""
echo "############################################################"
echo "## 恢复原注册表: $RESTORE"
echo "############################################################"
cp -f "$RESTORE" .datasources.json
echo "已恢复数据源: $(python3 -c "import json; print([e['name'] for e in json.load(open('.datasources.json'))['datasources']])")"
echo "✅ 三批完成"
