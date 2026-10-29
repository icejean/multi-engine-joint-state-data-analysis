#!/usr/bin/env bash
# pass^3 第 N 轮：S 轴 + M 轴全量各跑一次。
# 结果写 *_pass<N>.json，不覆盖其它轮。
# 顺序与 run_full_v2.sh 一致：S 轴 single-shot 全量 → M 轴 Agent 全量（硬隔离三档）。
# 末尾 rescore 两轴（防 gold 漂移）并打印最终数字。
# 用法: bash run_pass.sh 2   # 第 2 轮 → results_wc_s_full_pass2.json + results_wc_m_126_full_pass2.json
set -euo pipefail

PASS=${1:?用法: run_pass.sh <pass号>}

WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts
WC=$WS/dataai-test/data/works_cycles
MODEL=deepseek-v4-flash

S_RESULTS="results_wc_s_full_pass${PASS}.json"
M_RESULTS="results_wc_m_126_full_pass${PASS}.json"

cd "$WS"

echo "############################################################"
echo "## [1/2] S 轴 single-shot 全量 (S0/S1/S2, 直连 DeepSeek) → $S_RESULTS"
echo "############################################################"
python3 "$SCRIPTS/run_bench_wc_singleshot.py" --all --levels S0,S1,S2 \
    --model "$MODEL" --results "$S_RESULTS"

echo ""
echo "############################################################"
echo "## [2/2] M 轴 Agent 全量 (M0/M1/M2, 硬隔离) → $M_RESULTS"
echo "############################################################"
TS=$(date +%Y%m%d_%H%M%S)
SNAPSHOT=".datasources.json.bak.${TS}"
cp -f .datasources.json "$SNAPSHOT"
echo "现场备份注册表 → $SNAPSHOT"

for LVL in M0 M1 M2; do
  case $LVL in
    M0) ISO=.datasources_m0.json ;;
    M1) ISO=.datasources_m1.json ;;
    M2) ISO=.datasources_m2.json ;;
  esac
  echo ""
  echo "## 批次 $LVL —— 注册表: $ISO (只留单库,硬隔离)"
  cp -f "$ISO" .datasources.json
  python3 "$SCRIPTS/run_bench_wc.py" --all --levels "$LVL" --model "$MODEL" \
      --results "$M_RESULTS" --retry 2 --sleep 1
done

cp -f "$SNAPSHOT" .datasources.json
rm -f "$SNAPSHOT"
echo ""
echo "已恢复注册表: $(python3 -c "import json; print([e['name'] for e in json.load(open('.datasources.json'))['datasources']])")"

echo ""
echo "############################################################"
echo "## [3/3] 重判两轴（防 gold 漂移）+ 最终数字"
echo "############################################################"
python3 "$SCRIPTS/rescore_wc.py" "$S_RESULTS" --s
python3 "$SCRIPTS/rescore_wc.py" "$M_RESULTS"
echo ""
echo "✅ pass${PASS} 完成。结果:"
echo "   $WC/$S_RESULTS"
echo "   $WC/$M_RESULTS"
