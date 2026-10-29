#!/usr/bin/env bash
# 26 题梯度敏感子集跑分 —— 硬隔离版(复用 run_pilot_clean.sh 的隔离机制)。
# 每批只把「单个 works_cycles 库」注册进 .datasources.json，批间换文件；跑完恢复原注册表。
# 结果统一写指定 results 文件(断点续跑)。
#
# 用法(环境变量覆盖):
#   IDS="99" RESULTS=results_wc_cost_validate.json ./run_26subset.sh   # 3×1 小批验证
#   ./run_26subset.sh                                                  # 全量 26 题 × 3 档
set -euo pipefail

WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts

# 26 题梯度敏感子集 = 对照4 + 字典敏感5(BOM/CTE) + ER敏感 jc≥3 ×17
IDS=${IDS:-"1,26,33,113,99,100,101,102,103,89,90,91,93,94,95,96,98,105,108,109,111,123,124,126,127,128"}
RESULTS=${RESULTS:-results_wc_26subset.json}
MODEL=${MODEL:-deepseek-v4-flash}

cd "$WS"

# 现场备份当前注册表,跑完恢复这个(而非依赖历史 .bak.*)
TS=$(date +%Y%m%d_%H%M%S)
SNAPSHOT=".datasources.json.bak.${TS}"
cp -f .datasources.json "$SNAPSHOT"
echo "现场备份当前注册表 → $SNAPSHOT"
echo "当前数据源: $(python3 -c "import json; print([e['name'] for e in json.load(open('.datasources.json'))['datasources']])")"

for LVL in M0 M1 M2; do
  case $LVL in
    M0) ISO=.datasources_m0.json ;;
    M1) ISO=.datasources_m1.json ;;
    M2) ISO=.datasources_m2.json ;;
  esac
  echo ""
  echo "############################################################"
  echo "## 批次 $LVL —— 注册表: $ISO (只留单库,硬隔离)"
  echo "############################################################"
  cp -f "$ISO" .datasources.json
  echo "注册的数据源: $(python3 -c "import json; print([e['name'] for e in json.load(open('.datasources.json'))['datasources']])")"
  python3 "$SCRIPTS/run_bench_wc.py" --ids "$IDS" --levels "$LVL" --model "$MODEL" --results "$RESULTS"
done

echo ""
echo "############################################################"
echo "## 恢复原注册表: $SNAPSHOT"
echo "############################################################"
cp -f "$SNAPSHOT" .datasources.json
echo "已恢复数据源: $(python3 -c "import json; print([e['name'] for e in json.load(open('.datasources.json'))['datasources']])")"
echo "✅ 三批完成,结果在 dataai-test/data/works_cycles/$RESULTS"
