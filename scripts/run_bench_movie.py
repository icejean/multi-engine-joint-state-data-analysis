#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
movie M+S 混合模式基准运行器 —— run_bench_wc_mplus.py 的图库(Neo4j/Cypher)版。

M+S 口径(与 works_cycles M+S 一致):agent 按绝对路径用 read 工具**一次性加载**
schema.json + notes.md 两个资源文件,作为图结构(节点标签/属性/关系类型及方向)与
Cypher 注意事项的权威来源;只有资源文件不足以确定答案(如需确认具体数据值/枚举/
大小写/是否 fan-out 重复)时才 preview_data 抽查,否则不现场探索。

与 works_cycles M+S 的差异:
  - 单数据源 `movie`(Neo4j),无 M0/M1/M2 元数据梯度 → 无 --levels,每题只跑一次
  - 终答是**裸 Cypher**(不是 SQL),审计落 ~/log/<chat_id>.cypher(空行分隔的语句)
  - 判分走 score_cypher.py(值多重集比对,忽略行序/列序,放宽多列)

机制与 run_bench_wc_mplus.py 完全一致:驱动 openclaw agent(或 --backend dsh)跑题
→ 提终答 Cypher → 判分(results_equal_relaxed) → 逐条落盘 + 断点续跑 → 每题采集
成本指标(model/turns/tool_rounds/tokens/cost_usd/elapsed)。

用法:
  python run_bench_movie.py --ids 1,5,99
  python run_bench_movie.py --all --results results_movie_mplus.json
  python run_bench_movie.py --all --backend dsh --model glm-5.2
  # 覆盖资源文件(默认 data/movie/ 下的 movie_schema.json + movie_notes.md)
  python run_bench_movie.py --ids 1 --resource-schema /abs/schema.json --resource-notes /abs/notes.md

前置: movie 图数据源需注册为 .datasources.json(type:neo4j),Portal 已切到 Cypher kernel。
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

from score_cypher import (
    connect_graph,
    results_equal_relaxed,
    execute_cypher,
    diff_extra_columns,
)

SCRIPT_DIR = Path(__file__).resolve().parent
MOVIE_DIR = SCRIPT_DIR / ".." / "data" / "movie"
GOLD_JSON = MOVIE_DIR / "gold.json"
RESULTS_JSON = MOVIE_DIR / "results_movie_mplus.json"

HOME = Path.home()
DATASOURCE = "movie"          # 单数据源(Neo4j),无元数据梯度
AGENT_TIMEOUT = 360

# ── M+S 资源文件(默认绝对路径;可用 --resource-schema / --resource-notes 覆盖) ──
RESOURCE_SCHEMA = str(HOME / ".openclaw" / "workspace" / "dataai-test" / "data" / "movie" / "movie_schema.json")
RESOURCE_NOTES = str(HOME / ".openclaw" / "workspace" / "dataai-test" / "data" / "movie" / "movie_notes.md")

# ── DSH(DeepSeek Harness)后端(与 run_bench_wc_mplus.py 相同) ──
DSH_CWD = HOME / ".dsh" / "workspace"
DSH_MODEL_MAP = {
    "deepseek-v4-flash": ("deepseek-official", "deepseek-v4-flash"),
    "deepseek-v4-pro": ("deepseek-official", "deepseek-v4-pro"),
    "glm-5.1": ("zai", "glm-5.1"),
    "glm-5.2": ("zai", "glm-5.2"),
    "glm-5-pro": ("xirang", "GLM-5-Pro"),
    "GLM-5-Pro": ("xirang", "GLM-5-Pro"),
    "deepseek-v3.2-pro": ("xirang", "DeepSeek-V3.2-Pro"),
    "minimax-m3": ("minimax", "MiniMax-M3"),
}
BACKEND_ENV = {"openclaw": "openclaw", "dsh": "deepseek_harness"}


def load_json(p):
    return json.loads(Path(p).read_text())


def extract_cyphers(text):
    """从 Cypher 审计日志提取语句列表(与 SQL 的 extract_sqls 对应)。

    每条 Cypher 前有 `// @ds: <name>` 分隔行,语句本身可跨多行;`//` 是 Cypher
    的注释符(不是 `--`)。按分隔行分组、组内多行拼成一条,返回完整语句列表。
    """
    stmts, cur = [], []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("// @ds:"):
            if cur:
                stmts.append("\n".join(cur))
                cur = []
            continue
        if not s or s.startswith("//"):
            continue
        cur.append(s)
    if cur:
        stmts.append("\n".join(cur))
    return stmts


def write_mcp_chat_id(chat_id):
    p = HOME / ".jupyter-mcp" / "current_chat_id"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(chat_id)


# ── DSH 后端 helpers(与 run_bench_wc_mplus.py 相同) ──

def _find_dsh():
    found = shutil.which("dsh")
    if found:
        return found
    for local_bin in (HOME / ".local" / "bin" / "dsh", HOME / ".local" / "node_modules" / ".bin" / "dsh"):
        if local_bin.is_file():
            return str(local_bin)
    return "dsh"


def _dsh_model_patch(model):
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
    session_id = f"session-{chat_id}"
    base = HOME / ".dsh" / "sessions"
    for suffix in ("session.jsonl.zstd", "session.jsonl"):
        for p in base.glob(f"*/{session_id}/{suffix}"):
            return p
    return None


def _dsh_tool_calls(session_path):
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


# ── 成本指标采集(与 run_bench_wc_mplus.py 相同) ──

def _openclaw_cost_from_transcript(session_file):
    if not session_file:
        return {}
    p = Path(session_file)
    if not p.exists():
        return {}
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {}
    turns = tool_rounds = tool_calls = 0
    tok_input = tok_output = tok_cache_read = tok_cache_write = tok_reasoning = 0
    cost_usd = 0.0
    has_cost = False
    model = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "message":
            continue
        m = obj.get("message") or {}
        if m.get("role") != "assistant":
            continue
        turns += 1
        provider, mid = m.get("provider"), m.get("model")
        if provider or mid:
            model = f"{provider}/{mid}"
        n_calls = 0
        content = m.get("content")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "toolCall":
                    n_calls += 1
        tool_calls += n_calls
        if n_calls > 0:
            tool_rounds += 1
        u = m.get("usage") or {}
        tok_input += u.get("input") or 0
        tok_output += u.get("output") or 0
        tok_cache_read += u.get("cacheRead") or 0
        tok_cache_write += u.get("cacheWrite") or 0
        tok_reasoning += u.get("reasoningTokens") or 0
        c = u.get("cost")
        if isinstance(c, dict) and c.get("total") is not None:
            cost_usd += float(c["total"])
            has_cost = True
    return {
        "model": model,
        "turns": turns,
        "tool_rounds": tool_rounds,
        "tool_calls": tool_calls,
        "tokens": {
            "input": tok_input,
            "output": tok_output,
            "cache_read": tok_cache_read,
            "cache_write": tok_cache_write,
            "reasoning": tok_reasoning,
            "total": tok_input + tok_output + tok_cache_read + tok_cache_write,
        },
        "cost_usd": round(cost_usd, 6) if has_cost else None,
    }


def _dsh_cost_from_session(session_path):
    if session_path is None:
        return {}
    if str(session_path).endswith(".zstd"):
        r = subprocess.run(["zstd", "-dc", str(session_path)], capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return {}
        text = r.stdout
    else:
        try:
            text = Path(session_path).read_text(encoding="utf-8")
        except Exception:
            return {}
    model = None
    steps, tool_steps = set(), set()
    tool_calls = 0
    tok_input = tok_output = tok_cache_read = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("type")
        d = obj.get("data") or {}
        if t == "request/header":
            cfg = (d.get("header") or {}).get("config") or {}
            if cfg.get("provider") or cfg.get("model"):
                model = f"{cfg.get('provider')}/{cfg.get('model')}"
        elif t == "request/context":
            if d.get("provider") or d.get("model"):
                model = f"{d.get('provider')}/{d.get('model')}"
        elif t == "step/start":
            steps.add((d.get("turn"), d.get("step")))
        elif t == "tool/call":
            tool_calls += 1
            tool_steps.add((d.get("turn"), d.get("step")))
        elif t == "assistant/chunk":
            ch = d.get("chunk") or {}
            if ch.get("type") == "usage":
                u = ch.get("usage") or {}
                tok_input += u.get("inputTokens") or 0
                tok_output += u.get("outputTokens") or 0
                tok_cache_read += u.get("cacheReadTokens") or 0
    return {
        "model": model,
        "turns": len(steps),
        "tool_rounds": len(tool_steps),
        "tool_calls": tool_calls,
        "tokens": {
            "input": tok_input,
            "output": tok_output,
            "cache_read": tok_cache_read,
            "cache_write": 0,
            "reasoning": None,
            "total": tok_input + tok_output + tok_cache_read,
        },
        "cost_usd": None,
    }


def _apply_cost(result, cost):
    if not cost:
        return result
    for k in ("model", "turns", "tool_rounds", "tokens", "cost_usd"):
        if cost.get(k) is not None:
            result[k] = cost[k]
    if cost.get("tool_calls") is not None:
        result["tool_calls"] = cost["tool_calls"]
    return result


def _meta_instr(resource_schema, resource_notes):
    """M+S 口径的过程性指令(Cypher 版):资源文件替代现场探索。"""
    return (
        f"【重要】本次任务只允许查询数据源 `{DATASOURCE}` 这一个数据源，"
        "禁止 list_datasources 后切换到其他任何数据源。"
        "\n\n【重要】确定图结构(节点标签/属性/关系类型及方向)与 Cypher 注意事项——权威来源是资源文件，不是现场探索："
        "本数据源已有打包好的两个资源文件，请用 read 工具按绝对路径**一次性加载**，作为图 schema 与 Cypher 注意事项的权威来源：\n"
        f"  - 图 schema(节点标签、各标签属性、关系类型及方向)：{resource_schema}\n"
        f"  - Cypher 生成注意事项(踩坑清单)：{resource_notes}\n"
        "读完这两个文件后据此确定：有哪些节点标签(如 :Movie :Person)、每个标签有哪些属性、"
        "有哪些关系类型及其方向、以及各类确定性规则(去重、NULL 排序、聚合口径等)。"
        "**不要**再用 list_objects 逐标签探索——资源文件已包含这些信息。"
        "**只有在资源文件不足以确定答案时**才自行探索：例如需要确认具体数据值(枚举值/大小写/是否 fan-out 重复)"
        "而资源文件里没写，此时才用 preview_data 抽查关键标签的节点；否则不要探索，直接基于资源文件写 Cypher。"
        "\n\n【重要】输出形状：RETURN 每一列都要对应题面要求的「一个独立字段」，一列一值，不要自作主张增删列。"
        "不要用字符串拼接或 collect() 把多个字段的值拼进同一列，除非题面明确要求。"
        "题面问「名字/名称」→ 返回 name 属性，不要返回内部 id/elementId。"
        "\n\n【重要】过滤条件：只加实现题面要求所必需的条件，不要脑补题面没提的约束；"
        "题面问「所有/每个/every/all」时输出应包含该类全部记录，不要额外加会排除部分行的过滤。"
        "不要「硬编码」：不要把你探索数据时看到的某个具体属性值/id 直接写进 WHERE，"
        "题面的语义条件要用对应的属性条件表达，除非题面明确给出了具体值。"
        "尤其：题面给出的实体(电影名/人名)要用 Cypher 从该实体推导关联值(先 MATCH 出它的国家/导演/公司，再 MATCH 关联)，"
        "不要把你 preview/推导得到的中间值(国家名/人名)写死进 WHERE。"
        "\n\n【重要】关系方向：写对 (n)-[:rel]->(m) 与 (n)<-[:rel]-(m) 的方向，方向反了会得到空集或错误结果。"
        "\n\n【重要】去重：一对多(fan-out，一个节点对应多个邻居)时，问「有哪些 X」要加 DISTINCT(WITH DISTINCT n 或 RETURN DISTINCT)，"
        "问「数量」要用 count(DISTINCT n)，除非题面明确要按关系逐条计数。去重对象是实体(节点)，不是返回值。"
        "\n\n【重要】重名节点：图里有海量同名电影/人物(gold 按「节点」去重，不是按名字)。"
        "「列出名字」用 WITH DISTINCT n RETURN n.name（不要 RETURN DISTINCT n.name，那会合并同名电影）；"
        "「名字+计数」必须 WITH n, count(DISTINCT m) AS num RETURN n.name, num（不要 RETURN n.name, count(...)，那会按名字分组合并同名电影）。"
        "\n\n【重要】NULL 排序：Neo4j 里 ORDER BY x DESC 时 NULL 排最前、ORDER BY x ASC 时 NULL 排最后。"
        "所以「最高/最新/最大」这类取极值的题，若该属性可能缺失，要加 `WHERE x IS NOT NULL` 再排序取 LIMIT 1，否则会取到 NULL 的行。"
        "但「列出所有/每个」题**不要**加 `IS NOT NULL`——NULL 也是合法值，要原样返回。"
        "\n\n【重要】数量比较：over/more than N = 严格 >N(不是 ≥N)；at least N = ≥N。"
        "\n\n【重要】聚合口径：average/平均 = avg(...)；count = count(...)。Cypher 无 GROUP BY，聚合前用 WITH 分组(如 WITH n, count(DISTINCT m) AS num)。"
        "\n\n【重要】语义按字面理解、尽早收敛：探索的唯一目的是找到「能回答题面的最小图模式」，"
        "一旦确认标签/关系/属性含义，立即写出最终答案 Cypher 并停止，不要反复换解读。"
        "探索最多 12 轮，第 12 轮必须输出最终答案 Cypher(不确定也基于已探明信息给最优解)。"
        "\n\n【重要】最终答案：系统只取你最后执行的一条 Cypher 作为最终答案，它必须是「直接回答题面的查询」(RETURN 出题面要的字段)。"
        "绝不能停在探索语句上——如 CALL db.labels()、preview_data、MATCH (n) RETURN n LIMIT 1 试看——这些探索只是为了找答案，"
        "找到后必须再输出真正的答案 Cypher(用题面的名字/语义条件)。"
        "得到答案后不要再执行任何验证/交叉核对语句，末尾多跑语句会导致答案被判错。"
    )


def agent_turn(question_id, question, model="deepseek-v4-flash", backend="openclaw",
               model_patch=None, resource_schema=RESOURCE_SCHEMA, resource_notes=RESOURCE_NOTES):
    """驱动 agent 回答一题(M+S 口径),返回结果 dict。"""
    chat_id = uuid.uuid4().hex
    write_mcp_chat_id(chat_id)

    msg = (f"请使用数据源 {DATASOURCE} 回答下面的问题。\n\n"
           + _meta_instr(resource_schema, resource_notes)
           + f"\n\n{question}")

    env = os.environ.copy()
    env["DATAAI_CHAT_ID"] = chat_id
    env["AGENT_BACKEND"] = BACKEND_ENV[backend]

    if backend == "dsh":
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
        "datasource": DATASOURCE,
        "chat_id": chat_id,
        "final_cypher": "",
        "cypher_history": [],
        "agent_text": "",
        "tool_calls": 0,
        "pass": False,
        "error": None,
        "model": model,
        "turns": 0,
        "tool_rounds": 0,
        "tokens": None,
        "cost_usd": None,
        "elapsed_seconds": None,
        "agent_duration_ms": None,
        "extra_columns": [],
    }

    kwargs = {"capture_output": True, "text": True, "timeout": AGENT_TIMEOUT + 30, "env": env}
    if backend == "dsh":
        kwargs["cwd"] = str(DSH_CWD)
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        result["error"] = "agent timeout"
        result["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
        return result
    result["elapsed_seconds"] = round(time.perf_counter() - t0, 2)

    if r.returncode != 0:
        result["error"] = f"agent rc={r.returncode}: {r.stderr[:300]}"
        return result

    if backend == "dsh":
        result["agent_text"] = (r.stdout or "").strip()
        dsh_session = _dsh_session_file(chat_id)
        result["tool_calls"] = _dsh_tool_calls(dsh_session)
        _apply_cost(result, _dsh_cost_from_session(dsh_session))
    else:
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            result["error"] = f"agent json parse: {e}"
            return result
        payloads = data.get("payloads", [])
        result["agent_text"] = payloads[0].get("text", "") if payloads else ""
        meta = data.get("meta", {})
        result["tool_calls"] = (meta.get("toolSummary", {}) or {}).get("calls", 0)
        result["agent_duration_ms"] = meta.get("durationMs")
        _apply_cost(result, _openclaw_cost_from_transcript(
            (meta.get("agentMeta") or {}).get("sessionFile")
        ))

    # 从审计日志提裸 Cypher(空行分隔)—— 与 SQL 的 extract_sqls 对应
    audit = HOME / "log" / f"{chat_id}.cypher"
    cyphers = extract_cyphers(audit.read_text(encoding="utf-8")) if audit.exists() else []
    result["cypher_history"] = cyphers
    result["final_cypher"] = cyphers[-1] if cyphers else ""
    return result


def score_result(result, gold, driver, database):
    """执行终答 Cypher 并与 gold 比对(放宽多列),回填 pass / error / extra_columns。"""
    if not result["final_cypher"]:
        if result["error"] is None:
            result["error"] = "no final cypher"
        return result
    try:
        cand_cols, cand_rows = execute_cypher(driver, database, result["final_cypher"])
        result["pass"] = results_equal_relaxed(gold["rows"], cand_rows)
        if result["pass"]:
            result["extra_columns"] = diff_extra_columns(
                gold["rows"], gold.get("columns", []), cand_rows, cand_cols
            )
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["pass"] = False
    return result


def load_existing(results_json):
    if results_json.exists():
        data = load_json(results_json)
        return data.get("runs", [])
    return []


RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "ratelimit", "too many requests", "429", "throttl", "限流")


def is_rate_limited(result):
    err = result.get("error")
    if err is not None:
        low = err.lower()
        return any(m in low for m in RATE_LIMIT_MARKERS)
    return result.get("tool_calls", 0) == 0 and not result.get("agent_text")


def _stat(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else float("nan")


def _print_cost_report(runs):
    lv = [r for r in runs if r.get("tokens")]
    if not lv:
        print("无 token 数据")
        return
    tok_in = _stat([r["tokens"]["input"] for r in lv])
    tok_out = _stat([r["tokens"]["output"] for r in lv])
    tok_tot = _stat([r["tokens"]["total"] for r in lv])
    cache = _stat([r["tokens"]["cache_read"] for r in lv])
    cost = _stat([r["cost_usd"] for r in lv if r.get("cost_usd") is not None])
    secs = _stat([r["elapsed_seconds"] for r in lv])
    rounds = _stat([r["tool_rounds"] for r in lv])
    cost_s = f"{cost:.4f}" if cost == cost else "n/a"
    print(f"均 token in={tok_in:,.0f} out={tok_out:,.0f} cache读={cache:,.0f} "
          f"total={tok_tot:,.0f} | 美元/题={cost_s} | 耗时={secs:.1f}s | "
          f"工具轮数={rounds:.1f} (n={len(lv)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="逗号分隔的题号(整数),如 1,5,99,100,116")
    ap.add_argument("--all", action="store_true", help="跑全部题")
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--backend", choices=["openclaw", "dsh"], default="openclaw")
    ap.add_argument("--results", default="results_movie_mplus.json")
    ap.add_argument("--sleep", type=int, default=0)
    ap.add_argument("--retry", type=int, default=0)
    ap.add_argument("--resource-schema", default=RESOURCE_SCHEMA, help="M+S schema 资源文件绝对路径")
    ap.add_argument("--resource-notes", default=RESOURCE_NOTES, help="M+S notes 资源文件绝对路径")
    args = ap.parse_args()

    for flag, p in (("--resource-schema", args.resource_schema), ("--resource-notes", args.resource_notes)):
        if not Path(p).exists():
            print(f"⚠️ {flag} 资源文件不存在: {p}")
            sys.exit(2)

    model_patch = None
    if args.backend == "dsh":
        DSH_CWD.mkdir(parents=True, exist_ok=True)
        model_patch = _dsh_model_patch(args.model)

    results_json = MOVIE_DIR / args.results
    gold = load_json(GOLD_JSON)
    gold_by_id = {g["id"]: g for g in gold}

    if args.all:
        selected = gold
    elif args.ids:
        ids = {int(x.strip()) for x in args.ids.split(",") if x.strip()}
        selected = [g for g in gold if g["id"] in ids]
    else:
        print("请用 --ids 或 --all 指定题")
        sys.exit(2)

    existing = {r["question_id"] for r in load_existing(results_json)}
    runs = load_existing(results_json)
    todo = [g for g in selected if g["id"] not in existing]

    print(f"共 {len(todo)} 题待跑,已跳过 {len(existing)} 题已完成")

    driver, database = connect_graph()
    try:
        for i, g in enumerate(todo, 1):
            print(f"\n[{i}/{len(todo)}] Q{g['id']} ({g['match_category']}) ...", flush=True)
            result = None
            for attempt in range(args.retry + 1):
                result = agent_turn(g["id"], g["question"], args.model, args.backend,
                                    model_patch, args.resource_schema, args.resource_notes)
                if not is_rate_limited(result):
                    break
                if attempt < args.retry:
                    wait = max(args.sleep, 15) * (attempt + 1)
                    print(f"    ⚠️ 空响应(疑似限流),{wait}s 后重试({attempt+1}/{args.retry})...", flush=True)
                    time.sleep(wait)
            score_result(result, g, driver, database)
            runs.append(result)
            results_json.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2))
            status = "✅" if result["pass"] else "❌"
            tok = result.get("tokens") or {}
            cost_s = f" ${result['cost_usd']:.4f}" if result.get("cost_usd") is not None else ""
            extra = result.get("extra_columns") or []
            extra_s = f" 多列={extra}" if extra else ""
            print(f"    {status} pass={result['pass']} tok={tok.get('total', 0):,} "
                  f"轮数={result.get('tool_rounds', 0)} {result.get('elapsed_seconds', 0):.0f}s"
                  f"{cost_s}{extra_s} err={result['error']}")
            if args.sleep > 0:
                time.sleep(args.sleep)
    finally:
        driver.close()

    print(f"\n{'=' * 60}")
    print("== 报告(M+S 混合模式, movie 图库) ==")
    passed = sum(1 for r in runs if r["pass"])
    total = len(runs)
    print(f"EX: {passed}/{total} = {passed / total * 100:.1f}%" if total else "无数据")

    extra = [(r["question_id"], r.get("extra_columns")) for r in runs if r.get("extra_columns")]
    if extra:
        print(f"带多余列(放宽判对但多输出): {len(extra)}/{total} 题")
        for qid, cols in extra:
            print(f"  Q{qid}: 多出 {cols}")

    dom_stat = {}
    for r in runs:
        d = gold_by_id[r["question_id"]]["match_category"]
        dom_stat.setdefault(d, [0, 0])
        dom_stat[d][1] += 1
        if r["pass"]:
            dom_stat[d][0] += 1
    print("\n按 match_category:")
    for d, (p, tot) in sorted(dom_stat.items(), key=lambda kv: -kv[1][1]):
        print(f"  {d:30s} {p}/{tot}")

    fails = [r["question_id"] for r in runs if not r["pass"]]
    if fails:
        print(f"\n失败 {len(fails)} 题: {', '.join(map(str, fails))}")

    print("\n== 成本汇总 ==")
    _print_cost_report(runs)


if __name__ == "__main__":
    main()
