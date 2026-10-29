#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BIRD dev single-shot 基线 runner（P2-B1）。

与 run_bench_bird_mplus.py（agent M+S 多轮）对照：**单次 LLM 调用、无工具循环、无执行反馈**。
注入 {db}_schema.json（数据字典 + 外键 + 列类型），可选 {db}_notes.md。

定位：为「M+S 领先 single-shot」提供**同库**对照基线（替代跨系统借 MCI-SQL 76.41%）。
口径：single-shot 拿到全部静态元数据（schema 字典 + evidence），但**默认不带 notes**
（notes 是 M+S 的迭代产物，single-shot 无迭代机制）——这样对比才公平。

用法：
  python run_bench_bird_singleshot.py --db financial --all --results results_fin_ss.json
  python run_bench_bird_singleshot.py --db formula_1 --all --results results_f1_ss.json
  python run_bench_bird_singleshot.py --db financial --all --with-notes --results results_fin_ss_notes.json

判分 results_equal_relaxed（与 agent 版一致）。
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / ".." / "data"

# 去掉 SOCKS 代理(httpx 无 socksio)
for _k in ("ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"

from run_bench_wc_singleshot import call_llm, extract_sql, _read_key  # noqa: E402
from score import results_equal_relaxed, execute_sql_columns, diff_extra_columns, _connect  # noqa: E402


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def serialize_schema(schema):
    """schema.json → 文本（表描述 + 列描述 + 外键），注入 single-shot 提示词。"""
    lines = []
    for t in schema["tables"]:
        lines.append(f"表 `{t['name']}` [{t.get('table_type', '')}]: {t.get('desc', '')}")
        for c in t.get("columns", []):
            lines.append(f"  {c['name']} ({c.get('type', '')}): {c.get('desc', '')}")
    lines.append("")
    lines.append("外键关系(JOIN 用)：")
    for fk in schema.get("foreign_keys", []):
        marker = f" [复合外键 {fk.get('seq')}/{fk.get('count')}]" if fk.get("count", 1) > 1 else ""
        lines.append(f"  {fk['from']} -> {fk['to']}{marker}")
    return "\n".join(lines)


META_INSTR = (
    "你是 Text2SQL 系统。根据下面给出的数据库结构，把用户的问题翻译成一条 MySQL SELECT 语句。\n"
    "只输出 SQL 本身，不要解释，不要 markdown 代码块，不要多余文字。\n"
    "\n"
    "【输出列】SELECT 每一列都要对应题面要求的「一个独立字段」，一列一值，不要自作主张增删列，"
    "不要用 SELECT *。由多个字段组成的复合信息（姓名＝名＋姓、坐标＝纬＋经）要按字段拆开分别返回，"
    "不要用 CONCAT/CONCAT_WS 拼进同一列（除非题面明确要求拼接）。"
    "题面问「full name/全名」返回 名+姓 两列；不要额外输出题面没要求的列（如内部 ID/url）。\n"
    "\n"
    "【复数语义】英文里「IDs/names/their X」这类复数有两解，别只按单类理解：\n"
    "- 单类复数：同一实体的多行（如 list clients 的 IDs = 每个 client 一个 ID）→ 返回该实体 ID 一列；\n"
    "- 跨实体复数：题面同时带出主实体和关联实体（如 clients 及其 accounts）时，泛指「IDs」可能指各实体各一个 ID → 多列。\n"
    "\n"
    "【过滤与 JOIN】只加实现题面要求所必需的条件、只 JOIN 题面要求所必需的表，"
    "不要脑补题面没提的约束；题面问「所有/每个/every/all」时输出应包含该类全部记录。"
    "不要硬编码：不要把你推测的具体 ID/值写进 WHERE，除非题面明确给出。\n"
    "\n"
    "【聚合口径】average/平均 = AVG(...)；over/more than N = 严格 >N（不是 ≥N）；at least N = ≥N。\n"
    "\n"
    "【极值】问 earliest/latest/first/last/most recent → 用 ORDER BY <时间/数值列> ASC/DESC LIMIT 1 动态表达，"
    "别把某个具体日期/ID 写死进 WHERE。\n"
    "\n"
    "【去重】判分按你返回的行数比对：\n"
    "- 问「哪些实体 / which X / list X」（X 是唯一实体）→ SELECT DISTINCT 该实体列，每个实体一行；\n"
    "- 问「每条记录 / each X / count 次数 / 明细」→ 别 DISTINCT、别 COUNT(DISTINCT)、别 GROUP BY 去重。\n"
    "\n"
    "【否定】no/not/without/没有/无 → 取「没有」的那部分，对应 `= 0`/`IS NULL`/`NOT`，不要写成 `> 0`。\n"
    "\n"
    "【输出形状】问 Yes/No → 用 `CASE WHEN ... THEN 'Yes' ELSE 'No' END`；问名字/名称 → 返回 name 列不是 code/ID。\n"
    "\n"
    "【SQL 细节】CTE/别名不要用 MySQL 保留字（如 usage、order、group）。\n"
)


def build_prompt(schema_text, notes_text, question, evidence):
    parts = [META_INSTR, "【数据库结构】表名、列名、列类型、描述、外键：", schema_text]
    if notes_text:
        parts += ["", "【SQL 注意事项】", notes_text]
    parts += ["", "【问题】", question]
    if evidence:
        parts += ["", "【外部知识（用于消歧，来自 BIRD 官方 evidence）】", evidence]
    parts += ["", "SQL："]
    return "\n".join(parts)


def run_one(api_key, model, base_url, qid, question, evidence, schema_text, notes_text, gold, conn):
    prompt = build_prompt(schema_text, notes_text, question, evidence)
    result = {
        "question_id": qid, "s_level": "S1N" if notes_text else "S1",
        "final_sql": "", "pass": False, "error": None, "model": None,
        "tokens": None, "elapsed_seconds": None, "extra_columns": [],
    }
    t0 = time.perf_counter()
    try:
        content, used_model, tokens = call_llm(api_key, model, base_url, prompt)
        result["model"] = used_model
        result["tokens"] = tokens
        sql = extract_sql(content)
        result["final_sql"] = sql
        if not sql:
            result["error"] = "no sql extracted"
            return result
        cand_cols, cand_rows = execute_sql_columns(conn, sql)
        result["pass"] = results_equal_relaxed(gold["rows"], cand_rows)
        if result["pass"]:
            result["extra_columns"] = diff_extra_columns(
                gold["rows"], gold.get("columns", []), cand_rows, cand_cols)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["pass"] = False
    finally:
        result["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
    return result


def load_existing(path):
    if Path(path).exists():
        return load_json(path).get("runs", [])
    return []


def _stat(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="formula_1 | financial")
    ap.add_argument("--ids", help="逗号分隔题号")
    ap.add_argument("--all", action="store_true", help="跑全部有 gold 的题")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--results", required=True, help="结果文件(相对 data/{db}/ 或绝对路径)")
    ap.add_argument("--with-notes", action="store_true", help="额外注入 {db}_notes.md")
    ap.add_argument("--sleep", type=int, default=0)
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

    if not Path(schema_path).exists():
        print(f"⚠️ schema 资源文件不存在: {schema_path}")
        sys.exit(2)

    schema = load_json(schema_path)
    schema_text = serialize_schema(schema)
    notes_text = ""
    if args.with_notes:
        if not Path(notes_path).exists():
            print(f"⚠️ notes 资源文件不存在: {notes_path}")
            sys.exit(2)
        notes_text = Path(notes_path).read_text(encoding="utf-8")

    questions = load_json(questions_json)["questions"]
    gold = {str(g["id"]): g for g in load_json(gold_json)}

    if args.all:
        selected = questions
    elif args.ids:
        ids = {str(x.strip()) for x in args.ids.split(",") if x.strip()}
        selected = [q for q in questions if str(q["id"]) in ids]
    else:
        print("请用 --ids 或 --all 指定题")
        sys.exit(2)

    no_gold = [q["id"] for q in selected if str(q["id"]) not in gold]
    selected = [q for q in selected if str(q["id"]) in gold]
    if no_gold:
        print(f"⚠️ 跳过无 gold 的 {len(no_gold)} 题: {no_gold}")

    api_key = _read_key(args.base_url)
    runs = load_existing(results_json)
    existing = {(str(r["question_id"]), r["s_level"]) for r in runs}
    todo = [(q, str(q["id"])) for q in selected if (str(q["id"]), "S1N" if notes_text else "S1") not in existing]
    print(f"{db}: single-shot {'+notes' if notes_text else '(schema 字典)'} "
          f"共 {len(todo)} 题待跑 -> {results_json}")

    conn = _connect(db)
    try:
        for i, (q, qid) in enumerate(todo, 1):
            print(f"\n[{i}/{len(todo)}] Q{qid} ...", flush=True)
            r = run_one(api_key, args.model, args.base_url, qid, q["question"],
                        q.get("evidence"), schema_text, notes_text, gold[qid], conn)
            runs.append(r)
            results_json.parent.mkdir(parents=True, exist_ok=True)
            results_json.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2), encoding="utf-8")
            tok = r.get("tokens") or {}
            extra = r.get("extra_columns") or []
            extra_s = f" 多列={extra}" if extra else ""
            st = "✅" if r["pass"] else ("⚠️" if r["error"] else "❌")
            print(f"    {st} pass={r['pass']} tok={tok.get('total', '?')} "
                  f"{r.get('elapsed_seconds', 0):.0f}s err={r['error']}{extra_s}")
            if args.sleep > 0:
                time.sleep(args.sleep)
    finally:
        conn.close()

    scored = [r for r in runs if r["pass"] is not None]
    passed = sum(1 for r in scored if r["pass"])
    ex = passed / len(scored) if scored else float("nan")
    print(f"\n{'=' * 60}")
    print(f"== {db} single-shot 报告 ==")
    print(f"EX: {passed}/{len(scored)} = {ex*100:.1f}%")
    tok_in = _stat([r["tokens"]["input"] for r in scored if r.get("tokens")])
    tok_tot = _stat([r["tokens"]["total"] for r in scored if r.get("tokens")])
    secs = _stat([r["elapsed_seconds"] for r in scored])
    print(f"均 token in={tok_in:,.0f} total={tok_tot:,.0f} | 耗时={secs:.1f}s")
    fails = [r["question_id"] for r in scored if not r["pass"]]
    if fails:
        print(f"失败: {', '.join(map(str, fails))}")


if __name__ == "__main__":
    main()
