#!/usr/bin/env bash
# B1：dirty 库 single-shot 同库基线（4 条串行，日志分开落盘，断点续跑）
# 用法（后台）：
#   cd /home/ubuntu/.openclaw/workspace/dataai-test
#   nohup bash scripts/run_b1_singleshot.sh > logs/b1_master.log 2>&1 &
set -uo pipefail
cd /home/ubuntu/.openclaw/workspace/dataai-test || exit 1
mkdir -p logs

run() {
  local db="$1" mode="$2" results="$3" extra="$4"
  echo ">>> [$db/$mode] $(date '+%F %T') 开始"
  # shellcheck disable=SC2086
  python3 scripts/run_bench_bird_singleshot.py --db "$db" --all --results "$results" $extra \
    > "logs/b1_${db}_${mode}.log" 2>&1
  echo "<<< [$db/$mode] $(date '+%F %T') 退出码 $?"
}

run financial  s1  results_fin_ss_s1.json  ""
run formula_1 s1  results_f1_ss_s1.json   ""
run financial  s1n results_fin_ss_s1n.json "--with-notes"
run formula_1 s1n results_f1_ss_s1n.json "--with-notes"

echo "=== B1 全部完成 $(date '+%F %T') ==="
