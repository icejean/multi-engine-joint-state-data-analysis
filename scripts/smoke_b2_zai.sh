#!/usr/bin/env bash
# B2 冒烟测试：确认 zai/glm-5.2 的 provider+模型（zai = bigmodel.cn，非 xirang = 息壤 ai.ctaigw.cn）。
# 只跑 1 题（id 1，M0），成本极低；跑完看结果 JSON 的 model 字段（被转录实际命中的 provider/model 覆盖）。
set -uo pipefail
WS=/home/ubuntu/.openclaw/workspace
SCRIPTS=$WS/dataai-test/scripts
WC=$WS/dataai-test/data/works_cycles
MODEL=zai/glm-5.2
RESULTS="results_wc_mplus_smoke_b2_zai.json"
QID="${1:-1}"

cd "$WS"

TS=$(date +%Y%m%d_%H%M%S)
SNAPSHOT=".datasources.json.bak.${TS}"
cp -f .datasources.json "$SNAPSHOT"
restore() {
  cp -f "$SNAPSHOT" .datasources.json 2>/dev/null || true
  rm -f "$SNAPSHOT" 2>/dev/null || true
  echo "[restore] 已恢复注册表"
}
trap restore EXIT

cp -f .datasources_m0.json .datasources.json
echo "注册表 → M0 硬隔离: $(python3 -c "import json; print([e['name'] for e in json.load(open('.datasources.json'))['datasources']])")"

python3 "$SCRIPTS/run_bench_wc_mplus.py" --ids "$QID" --levels M0 --model "$MODEL" --results "$RESULTS"

echo ""
echo "===== 冒烟结果关键字段 ====="
python3 - "$WC/$RESULTS" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))['runs'][0]
for k in ['question_id','m_level','model','error','pass','turns','tool_rounds','cost_usd','elapsed_seconds']:
    print(f"  {k}: {r.get(k)}")
t = r.get('tokens') or {}
print(f"  tokens.total: {t.get('total')}")
print(f"  final_sql: {str(r.get('final_sql'))[:140]}")
PY
