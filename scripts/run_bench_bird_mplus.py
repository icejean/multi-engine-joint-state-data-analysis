#!/usr/bin/env python3
"""BIRD dev M+S 收敛曲线 harness(单模式)。

与 run_bench_wc_mplus.py 同机制:注入 schema.json + notes.md 资源文件 → agent 生成 SQL
→ MySQL 执行 → results_equal_relaxed 判分 → 落盘。差异:
  - 单库单模式(无 M0/M1/M2 梯度),一库一跑。
  - 收敛曲线 = 多轮跑,每轮换一份 notes.md(从零逐步积累),每轮一个 results 文件。
  - meta_instr 是通用版(去掉 works_cycles 专属的 BOM/end_dt/rt_chng_dt 规则,库专属知识走 notes.md)。

用法:
  python run_bench_bird_mplus.py --db formula_1 --all --results results_f1_round1.json
  python run_bench_bird_mplus.py --db financial --ids 1,5,9 --model deepseek-v4-flash --backend dsh

资源文件(自动定位 data/{db}/{db}_schema.json 与 {db}_notes.md,可用 --resource-* 覆盖)。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / ".." / "data"
HOME = Path.home()

from run_bench_wc_mplus import (  # noqa: E402
    extract_sqls, write_mcp_chat_id, _find_dsh, _dsh_model_patch, _dsh_session_file,
    _dsh_tool_calls, _openclaw_cost_from_transcript, _dsh_cost_from_session, _apply_cost,
    DSH_CWD, BACKEND_ENV, AGENT_TIMEOUT, RATE_LIMIT_MARKERS,
)
from score import results_equal_relaxed, execute_sql_columns, diff_extra_columns, _connect  # noqa: E402


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _meta_instr(ds_name, schema_path, notes_path):
    return (
        f"【重要】本次任务只允许查询数据源 `{ds_name}` 这一个数据源，禁止切换到其他任何数据源。\n\n"
        "【最高优先级·答完即止】判分只取你【最后执行的一条 SQL】作为最终答案。"
        "一旦你执行了最终答案 SQL 并看到结果，就必须立即停止，严禁再执行任何 SQL——"
        "包括验证结果、交叉核对、COUNT 试数、查重复、查明细。任何「再确认一下」的后缀查询都会把正确答案顶掉、被判错。\n\n"
        f"【资源文件·权威来源】本数据源已打包好 schema 与注意事项两个资源文件，"
        f"请用 read 工具【一次性读取】这两个绝对路径，作为表结构/字段含义/外键关系/SQL 注意事项的权威来源：\n"
        f"  1. schema(表/字段/外键/列类型): {schema_path}\n"
        f"  2. notes(SQL 注意事项):           {notes_path}\n"
        "读完据此确定：表结构、每个字段的含义、表间 JOIN 的外键列（复合外键要全部列一起 join）、以及 notes 里列出的各类规则。"
        "不要再用 list_objects 逐表探索，也不要查 sys_*/information_schema——资源文件已包含这些信息。"
        "只在资源文件不足以确定答案时才自行探索：例如要确认具体数据值（枚举值/大小写/是否 fan-out 重复）而资源文件里没写，"
        "此时才用 preview_data 抽查关键表数据；否则不要探索，直接基于资源文件写 SQL。\n\n"
        "【输出列】SELECT 每一列都要对应题面要求的「一个独立字段」，一列一值，不要自作主张增删列。"
        "不要用 CONCAT/CONCAT_WS 把多个字段的值拼进同一列，除非题面明确要求拼接。"
        "复合信息（姓名＝名＋姓、坐标＝纬＋经）要按字段拆开分别返回；"
        "题面问「full name/全名」返回 名+姓 两列；不要额外输出题面没要求的列（如内部 ID/url）。\n\n"
        "【复数语义】英文里「IDs/names/their X」这类复数有两解，别只按单类理解：\n"
        "- 单类复数：同一实体的多行（如 list clients 的 IDs = 每个 client 一个 ID）→ 返回该实体 ID 一列；\n"
        "- 跨实体复数：题面同时带出主实体和关联实体（如 clients 及其 accounts）时，泛指的「IDs」可能指各实体各一个 ID → 多列（如 client_id + account_id）。\n"
        "判据：题面明确关联第二个实体（whose account / with their orders 等）且用泛指复数「IDs」→ 倾向返回多个实体的 ID 列。\n\n"
        "【过滤】只加实现题面要求所必需的条件，不要脑补题面没提的约束；"
        "题面问「所有/每个/every/all」某类记录时输出应包含该类全部记录，不要额外加会排除部分行的过滤。"
        "不要「硬编码」：不要把你探索时看到的某个具体 ID/值写进 WHERE，除非题面明确给出了具体值。\n\n"
        "【聚合口径】average/平均 = AVG(...)；over/more than N = 严格 >N（不是 ≥N）；at least N = ≥N。\n\n"
        "【极值】问 earliest/latest/first/last/most recent → 用 ORDER BY <时间/数值列> ASC/DESC LIMIT 1 动态表达，"
        "别把探索时看到的那个具体值（日期/ID）写死进 WHERE。\n\n"
        "【输出形状】题面问 Yes/No → 用 `CASE WHEN ... THEN 'Yes' ELSE 'No' END`；问名字/名称/是谁 → 返回 name/名字列，不是 code/ID 列。\n\n"
        "【去重】判分按你返回的行数比对，分两类：\n"
        "- 问「哪些实体 / which X / list X」（X 是唯一实体，如 accounts/districts/clients/circuits）→ SELECT DISTINCT 该实体列，每个实体一行；\n"
        "- 问「每条记录 / each X / count 次数 / 明细」→ 别 DISTINCT、别 COUNT(DISTINCT)、别 GROUP BY 去重，保留原始每行。\n\n"
        "【否定】no/not/without/没有/无 → 取「没有」的那部分，对应 `= 0`/`IS NULL`/`NOT`，不要写成 `> 0`。\n\n"
        "【收敛】语义按字面理解、尽早收敛；探索的唯一目的是找到「能回答题面的最小表集合」。"
        "一旦确认字段含义立即写最终答案 SQL 并停止。探索最多 12 轮，第 12 轮必须输出最终答案 SQL。\n\n"
        "【最终答案】系统只取你最后执行的一条 SQL 作为最终答案，它必须是直接回答题面的数据查询（SELECT 出题面要的字段），"
        "绝不能停在探索语句上（SHOW TABLES/sys_*/COUNT 试数/硬编码 ID）。得到答案后不要再执行任何验证/汇总 SQL。"
    )


def agent_turn(qid, question, ds_name, model, backend, model_patch, evidence, schema_path, notes_path):
    chat_id = uuid.uuid4().hex
    write_mcp_chat_id(chat_id)

    msg = f"请使用数据源 {ds_name} 回答下面的问题。\n\n{_meta_instr(ds_name, schema_path, notes_path)}\n\n{question}"
    if evidence:
        msg += f"\n\n【外部知识（用于消歧，来自 BIRD 官方 evidence）】{evidence}"

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
        "question_id": qid, "datasource": ds_name, "chat_id": chat_id,
        "final_sql": "", "sql_history": [], "agent_text": "", "tool_calls": 0,
        "pass": False, "error": None, "model": model, "turns": 0, "tool_rounds": 0,
        "tokens": None, "cost_usd": None, "elapsed_seconds": None,
        "agent_duration_ms": None, "extra_columns": [],
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
        _apply_cost(result, _openclaw_cost_from_transcript((meta.get("agentMeta") or {}).get("sessionFile")))

    audit = HOME / "log" / f"{chat_id}.sql"
    sqls = extract_sqls(audit.read_text(encoding="utf-8")) if audit.exists() else []
    result["sql_history"] = sqls
    result["final_sql"] = sqls[-1] if sqls else ""
    return result


def score_result(result, gold, ds_name):
    if not result["final_sql"]:
        if result["error"] is None:
            result["error"] = "no final sql"
        return result
    gold_rows = gold["rows"]
    gold_cols = gold.get("columns", [])
    try:
        conn = _connect(ds_name)
        try:
            cand_cols, cand_rows = execute_sql_columns(conn, result["final_sql"])
            result["pass"] = results_equal_relaxed(gold_rows, cand_rows)
            if result["pass"]:
                result["extra_columns"] = diff_extra_columns(gold_rows, gold_cols, cand_rows, cand_cols)
        finally:
            conn.close()
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["pass"] = False
    return result


def load_existing(path):
    if Path(path).exists():
        return load_json(path).get("runs", [])
    return []


def is_rate_limited(result):
    err = result.get("error")
    if err is not None:
        low = err.lower()
        return any(m in low for m in RATE_LIMIT_MARKERS)
    return result.get("tool_calls", 0) == 0 and not result.get("agent_text")


def _stat(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="formula_1 | financial")
    ap.add_argument("--ids", help="逗号分隔题号(整数)")
    ap.add_argument("--all", action="store_true", help="跑全部有 gold 的题")
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--backend", choices=["openclaw", "dsh"], default="openclaw")
    ap.add_argument("--results", required=True, help="结果文件(相对 data/{db}/ 或绝对路径)")
    ap.add_argument("--sleep", type=int, default=0)
    ap.add_argument("--retry", type=int, default=0)
    ap.add_argument("--resource-schema", help="schema.json 绝对路径(默认 data/{db}/{db}_schema.json)")
    ap.add_argument("--resource-notes", help="notes.md 绝对路径(默认 data/{db}/{db}_notes.md)")
    args = ap.parse_args()

    db = args.db
    ddir = DATA_DIR / db
    questions_json = ddir / "question_set_obfuscated.json"
    gold_json = ddir / "gold.json"
    schema_path = args.resource_schema or str(ddir / f"{db}_schema.json")
    notes_path = args.resource_notes or str(ddir / f"{db}_notes.md")
    results_json = Path(args.results) if os.path.isabs(args.results) else ddir / args.results

    for flag, p in (("--resource-schema", schema_path), ("--resource-notes", notes_path)):
        if not Path(p).exists():
            print(f"⚠️ {flag} 资源文件不存在: {p}")
            sys.exit(2)

    model_patch = None
    if args.backend == "dsh":
        DSH_CWD.mkdir(parents=True, exist_ok=True)
        model_patch = _dsh_model_patch(args.model)

    questions = load_json(questions_json)["questions"]
    gold = {g["id"]: g for g in load_json(gold_json)}

    if args.all:
        selected = questions
    elif args.ids:
        ids = {int(x.strip()) for x in args.ids.split(",") if x.strip()}
        selected = [q for q in questions if q["id"] in ids]
    else:
        print("请用 --ids 或 --all 指定题")
        sys.exit(2)

    no_gold = [q["id"] for q in selected if q["id"] not in gold]
    selected = [q for q in selected if q["id"] in gold]
    if no_gold:
        print(f"⚠️ 跳过无 gold 的 {len(no_gold)} 题: {no_gold}")

    runs = load_existing(results_json)
    existing = {r["question_id"] for r in runs}
    todo = [q for q in selected if q["id"] not in existing]

    print(f"{db}: 共 {len(todo)} 题待跑(已跳过 {len(existing)} 题已完成) -> {results_json}")

    for i, q in enumerate(todo, 1):
        print(f"\n[{i}/{len(todo)}] Q{q['id']} ...", flush=True)
        result = None
        for attempt in range(args.retry + 1):
            result = agent_turn(q["id"], q["question"], db, args.model, args.backend, model_patch,
                                q.get("evidence"), schema_path, notes_path)
            if not is_rate_limited(result):
                break
            if attempt < args.retry:
                wait = max(args.sleep, 15) * (attempt + 1)
                print(f"    ⚠️ 空响应(疑似限流),{wait}s 后重试({attempt+1}/{args.retry})...", flush=True)
                time.sleep(wait)
        score_result(result, gold[q["id"]], db)
        runs.append(result)
        results_json.parent.mkdir(parents=True, exist_ok=True)
        results_json.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2), encoding="utf-8")
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

    # 报告
    scored = [r for r in runs if r["pass"] is not None]
    passed = sum(1 for r in scored if r["pass"])
    ex = passed / len(scored) if scored else float("nan")
    print(f"\n{'=' * 60}")
    print(f"== {db} M+S 报告 ==")
    print(f"EX: {passed}/{len(scored)} = {ex*100:.1f}%")
    extra = [(r["question_id"], r.get("extra_columns")) for r in scored if r.get("extra_columns")]
    if extra:
        print(f"带多余列(放宽判对但多输出): {len(extra)} 题 -> {extra}")
    fails = [r["question_id"] for r in scored if not r["pass"]]
    if fails:
        print(f"失败: {', '.join(map(str, fails))}")
    tok_in = _stat([r["tokens"]["input"] for r in scored if r.get("tokens")])
    tok_tot = _stat([r["tokens"]["total"] for r in scored if r.get("tokens")])
    cost = _stat([r["cost_usd"] for r in scored if r.get("cost_usd") is not None])
    secs = _stat([r["elapsed_seconds"] for r in scored])
    rounds = _stat([r["tool_rounds"] for r in scored])
    cost_s = f"{cost:.4f}" if cost == cost else "n/a"
    print(f"均 token in={tok_in:,.0f} total={tok_tot:,.0f} | 美元/题={cost_s} | 耗时={secs:.1f}s | 工具轮数={rounds:.1f}")


if __name__ == "__main__":
    main()
