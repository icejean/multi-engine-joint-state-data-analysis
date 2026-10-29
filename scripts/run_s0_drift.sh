#!/usr/bin/env bash
# S0 错题并集 pass^3 漂移采样：对「至少一轮 S0 挂过」的 50 道题，各跑 3 次 single-shot。
# 3 个独立结果文件（r1/r2/r3）绕开 run_bench_wc_singleshot.py 的 (qid, s_level) 断点去重。
# 不覆盖任何已有结果文件。全程直连 DeepSeek + pymysql，无 .datasources.json 隔离问题。
set -euo pipefail

WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts

# S0 错题并集 = full_v2 ∪ pass1 的 S0 挂题（50 道）
IDS="12,13,14,20,26,27,30,33,35,36,37,39,40,41,43,44,45,48,50,54,56,57,64,65,73,75,77,79,80,81,82,84,86,87,89,90,91,94,98,99,109,110,111,112,116,117,119,120,123,124"

cd "$WS"
for R in 1 2 3; do
  echo "############################################################"
  echo "## S0 漂移第 $R/3 轮 —— 50 题 → results_wc_s0_drift_r$R.json"
  echo "############################################################"
  python3 "$SCRIPTS/run_bench_wc_singleshot.py" --ids "$IDS" --levels S0 \
      --model deepseek-v4-flash --results "results_wc_s0_drift_r$R.json"
done

echo ""
echo "✅ S0 漂移 3 轮完成。结果:"
echo "   $WS/dataai-test/data/works_cycles/results_wc_s0_drift_r1.json"
echo "   $WS/dataai-test/data/works_cycles/results_wc_s0_drift_r2.json"
echo "   $WS/dataai-test/data/works_cycles/results_wc_s0_drift_r3.json"
