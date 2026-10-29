#!/usr/bin/env bash
# 126 题全量 M 轴（Agent 自迭代）跑分 —— 硬隔离版。
# 复用 run_26subset.sh 的隔离机制：每批只把「单个 works_cycles 库」注册进
# .datasources.json，批间换文件，跑完恢复原注册表。结果统一写指定 results 文件（断点续跑）。
#
# 三批 = M0 / M1 / M2 三档元数据（硬隔离：agent 只能 list 到当前档那一个库）。
# 全量 126 题（question_set_final_obfuscated.json），模型 deepseek-v4-flash。
#
# 用法(环境变量覆盖):
#   ./run_126_full.sh                    # 全量 126 题 × 3 档 = 378 次 agent 运行
#   RESULTS=results_wc_m_126_full.json MODEL=deepseek-v4-flash ./run_126_full.sh
set -euo pipefail

WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts

RESULTS=${RESULTS:-results_wc_m_126_full.json}
MODEL=${MODEL:-deepseek-v4-flash}

cd "$WS"

# 现场备份当前注册表，跑完恢复这个（而非依赖历史 .bak.*）
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
  python3 "$SCRIPTS/run_bench_wc.py" --all --levels "$LVL" --model "$MODEL" \
      --results "$RESULTS" --retry 2 --sleep 1
done

echo ""
echo "############################################################"
echo "## 恢复原注册表: $SNAPSHOT"
echo "############################################################"
cp -f "$SNAPSHOT" .datasources.json
echo "已恢复数据源: $(python3 -c "import json; print([e['name'] for e in json.load(open('.datasources.json'))['datasources']])")"
echo "✅ 三批完成,结果在 dataai-test/data/works_cycles/$RESULTS"
