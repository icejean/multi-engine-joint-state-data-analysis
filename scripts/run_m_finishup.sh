#!/usr/bin/env bash
# M 轴收尾：gold 重判 + 重跑 evidence/question 修过的 12 题。
# 前置：run_full_v2.sh 已跑完（M2 完成、.datasources.json 已恢复 5 库）。
set -euo pipefail

WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts
cd "$WS/dataai-test"

IDS="9,22,23,36,39,41,43,45,54,67,81,94"
RESULTS=results_wc_m_126_full_v2.json

echo "############################################################"
echo "## [1/3] gold 重判（Q29/Q73/Q74 新 gold，静态）"
echo "############################################################"
python3 "$SCRIPTS/rescore_wc.py" "$RESULTS"

echo ""
echo "############################################################"
echo "## [2/3] 删除 12 题旧记录"
echo "############################################################"
python3 -c "
import json
d=json.load(open('data/works_cycles/$RESULTS'))
ids={int(x) for x in '$IDS'.split(',')}
d['runs']=[r for r in d['runs'] if r['question_id'] not in ids]
json.dump(d, open('data/works_cycles/$RESULTS','w'), ensure_ascii=False, indent=2)
print('删除后剩', len(d['runs']), '条')
"

echo ""
echo "############################################################"
echo "## [3/3] 硬隔离重跑 12 题 × 3 档"
echo "############################################################"
TS=$(date +%Y%m%d_%H%M%S)
SNAPSHOT="$WS/.datasources.json.bak.${TS}"
cp -f "$WS/.datasources.json" "$SNAPSHOT"
echo "备份注册表 → $SNAPSHOT"

for LVL in M0 M1 M2; do
  case $LVL in
    M0) ISO=.datasources_m0.json ;;
    M1) ISO=.datasources_m1.json ;;
    M2) ISO=.datasources_m2.json ;;
  esac
  echo "## 批次 $LVL ($ISO)"
  cp -f "$WS/$ISO" "$WS/.datasources.json"
  python3 "$SCRIPTS/run_bench_wc.py" --ids "$IDS" --levels "$LVL" \
      --model deepseek-v4-flash --results "$RESULTS" --retry 2 --sleep 1
done

cp -f "$SNAPSHOT" "$WS/.datasources.json"
rm -f "$SNAPSHOT"

echo ""
echo "## 最终 M 轴数字"
python3 "$SCRIPTS/rescore_wc.py" "$RESULTS"
echo "✅ M 轴收尾完成"
