#!/usr/bin/env bash
# 全量重跑 v2 —— evidence + 时间态 + 最新值 + 字面理解/收敛 修复后。
# 顺序：S 轴 single-shot 全量 → M 轴 Agent 全量（硬隔离三档）。
# 结果写 *_v2.json，不覆盖旧结果（旧 results_wc_s_full.json / results_wc_m_126_full.json 留档）。
set -euo pipefail

WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts
cd "$WS"

echo "############################################################"
echo "## [1/2] S 轴 single-shot 全量 (S0/S1/S2, 直连 DeepSeek)"
echo "############################################################"
python3 "$SCRIPTS/run_bench_wc_singleshot.py" --all --levels S0,S1,S2 \
    --model deepseek-v4-flash --results results_wc_s_full_v2.json

echo ""
echo "############################################################"
echo "## [2/2] M 轴 Agent 全量 (M0/M1/M2, 硬隔离)"
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
  python3 "$SCRIPTS/run_bench_wc.py" --all --levels "$LVL" --model deepseek-v4-flash \
      --results results_wc_m_126_full_v2.json --retry 2 --sleep 1
done

cp -f "$SNAPSHOT" .datasources.json
rm -f "$SNAPSHOT"
echo ""
echo "✅ 全部完成。结果在 dataai-test/data/works_cycles/results_wc_s_full_v2.json + results_wc_m_126_full_v2.json"
