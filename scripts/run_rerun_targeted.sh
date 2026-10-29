#!/usr/bin/env bash
# 定向重跑「需重跑批」——只重跑当前挂掉的 (qid, level) 组合，不重跑已过的档。
# 前置：prompt 规则补强（去重/递归 CTE 层级/否定词/最新值强化 + M 超时 240→360）。
# S 轴直连 DeepSeek 无隔离；M 轴硬隔离三批。结果就地合并进 *_full_v2.json（断点续跑）。
set -euo pipefail

WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts
WC=$WS/dataai-test/data/works_cycles

S_IDS="11,12,13,19,27,29,45,52,99,101,119"
# M 轴按档分（硬隔离每批单库）：level:ids
M_BATCHES=("M0:28,52,119" "M1:52,65,70,119" "M2:12,65,99")

echo "== [0] 备份两个结果文件 =="
TS=$(date +%Y%m%d_%H%M%S)
cp "$WC/results_wc_s_full_v2.json" "$WC/results_wc_s_full_v2.json.bak.$TS"
cp "$WC/results_wc_m_126_full_v2.json" "$WC/results_wc_m_126_full_v2.json.bak.$TS"
echo "备份时间戳 $TS"

echo ""
echo "== [1] 删除 S 轴目标题里挂掉的 (qid, s_level) =="
python3 -c "
import json
f='$WC/results_wc_s_full_v2.json'
d=json.load(open(f))
ids={int(x) for x in '$S_IDS'.split(',')}
before=len(d['runs'])
d['runs']=[r for r in d['runs'] if not (r['question_id'] in ids and not r['pass'])]
print(f'S: {before} -> {len(d[\"runs\"])} 条，删 {before-len(d[\"runs\"])} 个挂掉的档')
json.dump(d, open(f,'w'), ensure_ascii=False, indent=2)
"

echo ""
echo "== [2] 删除 M 轴目标题里挂掉的 (qid, m_level) =="
M_ALL_IDS="28,52,119,65,70,12,99"
python3 -c "
import json
f='$WC/results_wc_m_126_full_v2.json'
d=json.load(open(f))
ids={int(x) for x in '$M_ALL_IDS'.split(',')}
before=len(d['runs'])
d['runs']=[r for r in d['runs'] if not (r['question_id'] in ids and not r['pass'])]
print(f'M: {before} -> {len(d[\"runs\"])} 条，删 {before-len(d[\"runs\"])} 个挂掉的档')
json.dump(d, open(f,'w'), ensure_ascii=False, indent=2)
"

echo ""
echo "== [3] S 轴定向重跑（single-shot，直连 DeepSeek）=="
python3 "$SCRIPTS/run_bench_wc_singleshot.py" --ids "$S_IDS" --levels S0,S1,S2 \
    --model deepseek-v4-flash --results results_wc_s_full_v2.json

echo ""
echo "== [4] M 轴定向重跑（agent，硬隔离三批）=="
SNAP="$WS/.datasources.json.bak.$TS"
cp -f "$WS/.datasources.json" "$SNAP"
for entry in "${M_BATCHES[@]}"; do
  LVL="${entry%%:*}"; IDS="${entry#*:}"
  case $LVL in
    M0) ISO=.datasources_m0.json ;;
    M1) ISO=.datasources_m1.json ;;
    M2) ISO=.datasources_m2.json ;;
    *) echo "未知 level $LVL"; exit 1 ;;
  esac
  echo "## 批次 $LVL（注册表 $ISO，ids=$IDS）"
  cp -f "$WS/$ISO" "$WS/.datasources.json"
  python3 "$SCRIPTS/run_bench_wc.py" --ids "$IDS" --levels "$LVL" \
      --model deepseek-v4-flash --results results_wc_m_126_full_v2.json --retry 2 --sleep 1
done
cp -f "$SNAP" "$WS/.datasources.json"
rm -f "$SNAP"
echo "已恢复注册表"

echo ""
echo "== [5] 最终数字（重判，防 gold 漂移）=="
python3 "$SCRIPTS/rescore_wc.py" results_wc_s_full_v2.json --s
python3 "$SCRIPTS/rescore_wc.py" results_wc_m_126_full_v2.json
echo "✅ 定向重跑完成"
