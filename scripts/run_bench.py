#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全量基准运行器:驱动 openclaw agent 跑题库 → 提终答 SQL → 判分 → Δ₄ 报告。

可断点续跑:结果逐条落盘到 data/sakila/results_flash.json,已跑过的 (question_id, m_level)
自动跳过;中断后重跑同命令即可续。

用法:
  # 5 题 pilot
  python run_bench.py --ids B1,C5,D1,E2,H4
  # 全量 25 题
  python run_bench.py --all
  # 指定 M 档(默认 M0,M2)
  python run_bench.py --all --levels M0,M2
  # 信创环境(无 OpenClaw)走 DSH 后端
  python run_bench.py --all --backend dsh --model glm-5.2 --results results_glm52_dsh.json
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / ".." / "data" / "sakila"
QUESTIONS_JSON = DATA_DIR / "questions.json"
GOLD_JSON = DATA_DIR / "gold.json"
RESULTS_JSON = DATA_DIR / "results_flash.json"

HOME = Path.home()
DB_BY_LEVEL = {"M0": "sakila_rntl", "M1": "sakila_rntl_m1", "M2": "sakila_rntl_meta"}
AGENT_TIMEOUT = 240

# ── DSH(DeepSeek Harness)后端 ─────────────────────────────────────────────
# 信创环境装不了 OpenClaw 时走 dsh headless;与 Portal 的 DeepSeekHarnessAdapter
# (dataai-portal/backend/app/services/agents/deepseek_harness.py)逐字对齐。
# 命令无 --model/--json,message 是位置参数,模型路由走 --patch YAML overlay。
DSH_CWD = HOME / ".dsh" / "workspace"   # 固定 cwd:避开 dataai-portal/.env 的 DSH_DEFAULT_MODEL,会话落 ~/.dsh/sessions
DSH_MODEL_MAP = {
    # run_bench --model → (DSH provider, DSH model),对齐 dataai-portal/.env 的 DSH_MODELS
    "deepseek-v4-flash": ("deepseek-official", "deepseek-v4-flash"),
    "deepseek-v4-pro": ("deepseek-official", "deepseek-v4-pro"),
    "glm-5.1": ("zai", "glm-5.1"),
    "glm-5.2": ("zai", "glm-5.2"),
    "glm-5-pro": ("xirang", "GLM-5-Pro"),
    "GLM-5-Pro": ("xirang", "GLM-5-Pro"),  # 兼容 run_bench 历史大写写法
    "deepseek-v3.2-pro": ("xirang", "DeepSeek-V3.2-Pro"),
    "minimax-m3": ("minimax", "MiniMax-M3"),
}
BACKEND_ENV = {"openclaw": "openclaw", "dsh": "deepseek_harness"}  # AGENT_BACKEND 值(供 switch_kernel 选 context 文件)

from score import results_equal, execute_sql, _connect  # noqa: E402


def load_json(p):
    return json.loads(Path(p).read_text())


def extract_sqls(text):
    """从审计日志提取 SQL 语句列表。

    每条 SQL 前有 `-- @ds:` / `// @ds:` 分隔行,且 SQL 本身可跨多行。
    按分隔行分组、组内多行拼成一条,返回完整语句列表(按执行顺序)。
    """
    stmts, cur = [], []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("-- @ds:") or s.startswith("// @ds:"):
            if cur:
                stmts.append(" ".join(cur))
                cur = []
            continue
        if not s or s.startswith("--") or s.startswith("//"):
            continue
        cur.append(s)
    if cur:
        stmts.append(" ".join(cur))
    return stmts


def write_mcp_chat_id(chat_id):
    p = HOME / ".jupyter-mcp" / "current_chat_id"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(chat_id)


# ── DSH 后端 helpers ──

def _find_dsh():
    """定位 dsh 可执行文件(系统 PATH / ~/.local 优先,兜底裸名)。"""
    found = shutil.which("dsh")
    if found:
        return found
    for local_bin in (HOME / ".local" / "bin" / "dsh", HOME / ".local" / "node_modules" / ".bin" / "dsh"):
        if local_bin.is_file():
            return str(local_bin)
    return "dsh"


def _dsh_model_patch(model):
    """生成 dsh 的 --patch 模型路由覆盖文件,返回路径。

    DSH 无 --model,模型由 agent-default-model 的 {provider, model} 决定;
    未知模型 fallback 到 deepseek-official 直连。每模型一个固定文件,幂等。
    """
    provider, dsh_model = DSH_MODEL_MAP.get(model, ("deepseek-official", model))
    patch = (
        "- id: agent-default-model\n"
        "  config:\n"
        f"    provider: {provider}\n"
        f"    model: {dsh_model}\n"
    )
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", model)
    p = HOME / ".dsh" / f"model-patch-bench-{safe}.yml"
    p.write_text(patch, encoding="utf-8")
    return str(p)


def _dsh_session_file(chat_id):
    """定位 dsh 会话 JSONL(zstd 或明文),按 session id 全局 glob。"""
    session_id = f"session-{chat_id}"
    base = HOME / ".dsh" / "sessions"
    for suffix in ("session.jsonl.zstd", "session.jsonl"):
        for p in base.glob(f"*/{session_id}/{suffix}"):
            return p
    return None


def _dsh_tool_calls(session_path):
    """统计最新一轮的 tool/call 次数(DSH stdout 无结构化 toolSummary)。"""
    if session_path is None:
        return 0
    if str(session_path).endswith(".zstd"):
        r = subprocess.run(["zstd", "-dc", str(session_path)], capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return 0
        text = r.stdout
    else:
        try:
            text = session_path.read_text(encoding="utf-8")
        except Exception:
            return 0
    max_turn, count = -1, 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "tool/call":
            continue
        turn = obj.get("data", {}).get("turn", 0)
        if turn > max_turn:
            max_turn, count = turn, 1
        elif turn == max_turn:
            count += 1
    return count


def agent_turn(question_id, question, ds_name, m_level, model="deepseek-v4-flash", backend="openclaw", model_patch=None):
    """驱动 agent 回答一题,返回结果 dict。

    backend: openclaw(默认,保复现) / dsh(信创环境,DeepSeek Harness)。
    model_patch: dsh 后端的 --patch 模型路由覆盖文件路径(openclaw 忽略)。
    """
    chat_id = uuid.uuid4().hex
    write_mcp_chat_id(chat_id)

    meta_instr = (
        "【重要】生成 SQL 之前，必须先查询该数据源中可用的元数据表"
        "（sys_tables、sys_table_fields、sys_foreignkeys，如存在）。"
        "如果存在 sys_foreignkeys（外键关系表，即 ER 图），必须先查询它，"
        "据此确定表与表之间的关联列，再编写 JOIN 条件。"
        "\n\n【重要】得到最终答案后，直接给出答案即可，"
        "不要再执行任何验证、交叉核对或汇总 SQL——系统只取你最后执行的一条 SQL 作为最终答案，"
        "末尾多跑的验证语句会导致答案被判错。"
    )
    msg = f"请使用数据源 {ds_name} 回答下面的问题。\n\n{meta_instr}\n\n{question}"

    env = os.environ.copy()
    env["DATAAI_CHAT_ID"] = chat_id
    env["AGENT_BACKEND"] = BACKEND_ENV[backend]

    if backend == "dsh":
        # DSH headless:message 是位置参数,无 --json/--model;模型路由走 --patch。
        cmd = [_find_dsh(), "--profile", "headless"]
        if model_patch:
            cmd += ["--patch", model_patch]
        cmd += ["--session-id", f"session-{chat_id}", msg]
    else:
        session_key = f"agent:main:portal-{chat_id}"
        cmd = [
            "openclaw", "agent", "--agent", "main",
            "--model", model,
            "--session-key", session_key, "--message", msg,
            "--local", "--json", "--timeout", str(AGENT_TIMEOUT),
        ]

    result = {
        "question_id": question_id,
        "m_level": m_level,
        "datasource": ds_name,
        "chat_id": chat_id,
        "final_sql": "",
        "sql_history": [],
        "agent_text": "",
        "tool_calls": 0,
        "pass": False,
        "error": None,
    }

    kwargs = {"capture_output": True, "text": True, "timeout": AGENT_TIMEOUT + 30, "env": env}
    if backend == "dsh":
        kwargs["cwd"] = str(DSH_CWD)
    try:
        r = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        result["error"] = "agent timeout"
        return result

    if r.returncode != 0:
        result["error"] = f"agent rc={r.returncode}: {r.stderr[:300]}"
        return result

    if backend == "dsh":
        # 输出是最终 assistant 文本(非 JSON);工具调用数从会话 JSONL 统计。
        result["agent_text"] = (r.stdout or "").strip()
        result["tool_calls"] = _dsh_tool_calls(_dsh_session_file(chat_id))
    else:
        # 解析 agent JSON 输出
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            result["error"] = f"agent json parse: {e}"
            return result
        payloads = data.get("payloads", [])
        result["agent_text"] = payloads[0].get("text", "") if payloads else ""
        meta = data.get("meta", {})
        result["tool_calls"] = (meta.get("toolSummary", {}) or {}).get("calls", 0)

    # 从审计日志提 SQL(按 -- @ds: 分组,支持多行 SQL)—— 后端无关,统一口径
    audit = HOME / "log" / f"{chat_id}.sql"
    sqls = extract_sqls(audit.read_text()) if audit.exists() else []
    result["sql_history"] = sqls
    result["final_sql"] = sqls[-1] if sqls else ""
    return result


def score_result(result, gold_rows, ds_name):
    """执行终答 SQL 并与 gold 比对,回填 result['pass'] / result['error']。"""
    if not result["final_sql"]:
        # 保留 agent_turn 已设的真实错误(timeout/rc),只在确实无错误时标 no final sql
        if result["error"] is None:
            result["error"] = "no final sql"
        return result
    try:
        conn = _connect(ds_name)
        try:
            cand = execute_sql(conn, result["final_sql"])
            result["pass"] = results_equal(gold_rows, cand)
        finally:
            conn.close()
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["pass"] = False
    return result


def load_existing(results_json):
    if results_json.exists():
        data = load_json(results_json)
        return data.get("runs", [])
    return []


# 限流特征:DSH 限流以 rc=1 退出,错误码 RATE_LIMIT(见 dsh-llm-pi-ai classifyPiAiError)落在 stderr。
RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "ratelimit", "too many requests", "429", "throttl", "限流")


def is_rate_limited(result):
    """检测限流:openclaw 空响应(rc=0 空 payload) 或 错误信息含限流特征(DSH rc=1 退出)。

    两种后端的限流表现不同:
      - openclaw:rc=0 但 payload 空 → error=None、tool_calls=0、agent_text 空
      - dsh:rc=1 退出,stderr 形如 `dsh: RATE_LIMIT: ...` → error 非空
    """
    err = result.get("error")
    if err is not None:
        low = err.lower()
        return any(m in low for m in RATE_LIMIT_MARKERS)
    return result.get("tool_calls", 0) == 0 and not result.get("agent_text")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="逗号分隔的题号,如 A1,B1,C1")
    ap.add_argument("--all", action="store_true", help="跑全部题")
    ap.add_argument("--levels", default="M0,M2", help="逗号分隔的 M 档")
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--backend", choices=["openclaw", "dsh"], default="openclaw",
                    help="agent 后端:openclaw(默认,保复现) 或 dsh(信创环境,DeepSeek Harness)")
    ap.add_argument("--results", default="results_flash.json")
    ap.add_argument("--sleep", type=int, default=0, help="每道题之间的间隔秒数(限流用)")
    ap.add_argument("--retry", type=int, default=0, help="空响应(疑似限流)时的重试次数")
    args = ap.parse_args()

    # DSH 后端:模型路由走 --patch 覆盖文件(整个 run 同一模型,生成一次即可)
    model_patch = None
    if args.backend == "dsh":
        DSH_CWD.mkdir(parents=True, exist_ok=True)
        model_patch = _dsh_model_patch(args.model)

    results_json = DATA_DIR / args.results

    questions = load_json(QUESTIONS_JSON)
    gold = {g["id"]: g for g in load_json(GOLD_JSON)}
    levels = [x.strip() for x in args.levels.split(",") if x.strip()]

    if args.all:
        selected = questions
    elif args.ids:
        ids = {x.strip() for x in args.ids.split(",") if x.strip()}
        selected = [q for q in questions if q["id"] in ids]
    else:
        print("请用 --ids 或 --all 指定题")
        sys.exit(2)

    # 断点续跑
    existing = {(r["question_id"], r["m_level"]) for r in load_existing(results_json)}
    runs = load_existing(results_json)
    todo = [(q, lvl) for q in selected for lvl in levels if (q["id"], lvl) not in existing]

    print(f"共 {len(todo)} 次待跑({len(selected)} 题 × {len(levels)} 档),已跳过 {len(existing)} 次已完成的")

    for i, (q, lvl) in enumerate(todo, 1):
        ds = DB_BY_LEVEL[lvl]
        print(f"\n[{i}/{len(todo)}] {q['id']} ({lvl}, {ds}) ...", flush=True)
        result = None
        for attempt in range(args.retry + 1):
            result = agent_turn(q["id"], q["question"], ds, lvl, args.model, args.backend, model_patch)
            if not is_rate_limited(result):
                break
            if attempt < args.retry:
                wait = max(args.sleep, 15) * (attempt + 1)
                print(f"    ⚠️ 空响应(疑似限流),{wait}s 后重试({attempt+1}/{args.retry})...", flush=True)
                time.sleep(wait)
        score_result(result, gold[q["id"]]["rows"], ds)
        runs.append(result)
        # 逐条落盘(续跑 + 防丢)
        results_json.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2))
        status = "✅" if result["pass"] else ("❌" if result["error"] else "❌")
        print(f"    {status} pass={result['pass']} final_sql={result['final_sql'][:60]!r} err={result['error']}")
        if args.sleep > 0:
            time.sleep(args.sleep)

    # 报告
    print(f"\n{'=' * 60}")
    print("== 报告 ==")
    ex = {}
    by_type = {}
    for lvl in levels:
        lv_runs = [r for r in runs if r["m_level"] == lvl]
        if not lv_runs:
            continue
        passed = sum(1 for r in lv_runs if r["pass"])
        ex[lvl] = passed / len(lv_runs)
        print(f"\n{lvl}: EX {passed}/{len(lv_runs)} = {ex[lvl]*100:.1f}%")
        type_stat = {}
        for r in lv_runs:
            t = gold[r["question_id"]]["type"]
            type_stat.setdefault(t, [0, 0])
            type_stat[t][1] += 1
            if r["pass"]:
                type_stat[t][0] += 1
        for t, (p, tot) in sorted(type_stat.items()):
            print(f"    {t:10s} {p}/{tot}")
        fails = [r["question_id"] for r in lv_runs if not r["pass"]]
        if fails:
            print(f"    失败: {', '.join(fails)}")

    if "M0" in ex:
        for lvl in ("M1", "M2"):
            if lvl in ex:
                print(f"\nΔ₄({lvl}) = EX({lvl}) - EX(M0) = {(ex[lvl]-ex['M0'])*100:+.1f} 个百分点")


if __name__ == "__main__":
    main()
