#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S 系列(single-shot Text2SQL)基准运行器。

与 M 系列(Agent 自迭代)对照:单次 LLM 调用、无工具循环、无数据探测、无执行反馈。
元数据预注入提示词(SPEC §3.2.2 的「预注入」分支):

  S0 = 裸 schema(表/列/类型)
  S1 = schema + 数据字典(sys_tables / sys_table_fields)
  S2 = schema + 字典 + ER 图(sys_foreignkeys)

模型对齐 M 系列(DataAI Portal workspace 的 DSH 后端默认模型)= DeepSeek V4 Flash,
走 DeepSeek OpenAI API 端点(https://api.deepseek.com),key 读自 ~/.claude。

用法:
  python run_bench_singleshot.py --ids A1,B5,H1 --levels S0,S1,S2
  python run_bench_singleshot.py --all --levels S0,S1,S2
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import pymysql

from langchain_openai import ChatOpenAI

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / ".." / "data" / "sakila"
QUESTIONS_JSON = DATA_DIR / "questions.json"
GOLD_JSON = DATA_DIR / "gold.json"
RESULTS_JSON = DATA_DIR / "results_singleshot.json"

# 去掉 SOCKS 代理(httpx 无 socksio),保留 http 代理
for _k in ("ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

DB_DATA = "sakila_rntl"          # 数据表(三库数据一致)
DB_META = "sakila_rntl_meta"     # 完整元数据(字典 + ER)

MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"
LLM_TIMEOUT = 120

from score import results_equal, execute_sql, _load_creds  # noqa: E402


def _read_key(base_url):
    """按 base_url 从 openclaw.json 的 provider 取 apiKey;fallback ~/.claude / ~/.dsh。"""
    # 1) openclaw.json 的 provider(权威,openclaw agent 用的就是这份)
    try:
        d = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json")))
        for prov in d.get("models", {}).get("providers", {}).values():
            if prov.get("baseUrl") == base_url or base_url.startswith(prov.get("baseUrl", "")):
                k = prov.get("apiKey")
                if k:
                    return k
    except Exception:
        pass
    # 2) ~/.claude/settings.json 的 ANTHROPIC_AUTH_TOKEN(deepseek key)
    try:
        d = json.load(open(os.path.expanduser("~/.claude/settings.json")))
        tok = d.get("env", {}).get("ANTHROPIC_AUTH_TOKEN")
        if tok:
            return tok
    except Exception:
        pass
    # 3) ~/.dsh/.credentials.yaml 递归找第一个非空 key
    try:
        import yaml
        d = yaml.safe_load(open(os.path.expanduser("~/.dsh/.credentials.yaml")))

        def _find(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if isinstance(v, str) and v:
                        return v
                    r = _find(v)
                    if r:
                        return r
            elif isinstance(o, list):
                for x in o:
                    r = _find(x)
                    if r:
                        return r
            return None
        tok = _find(d)
        if tok:
            return tok
    except Exception:
        pass
    raise RuntimeError(f"找不到 {base_url} 对应的 API key")


def _connect(db):
    creds = _load_creds()
    return pymysql.connect(
        host=creds.get("MYSQLHOST", "localhost"),
        port=int(creds.get("MYSQLPORT", 3306)),
        user=creds["MYSQLUSER"],
        password=creds["MYSQLPASSWORD"],
        charset="utf8mb4",
        database=db,
    )


def dump_schema(conn):
    """表名 / 列名 / 类型(仅数据表,不含 sys_*)。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name, column_name, column_type
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name NOT LIKE %s
        ORDER BY table_name, ordinal_position
        """,
        (DB_DATA, "sys\\_%"),
    )
    lines = []
    cur_tbl = None
    for tbl, col, ctype in cur.fetchall():
        if tbl != cur_tbl:
            cur_tbl = tbl
            lines.append(f"表 `{tbl}`:")
        lines.append(f"  {col} {ctype}")
    cur.close()
    return "\n".join(lines)


def dump_dictionary(conn):
    """数据字典:sys_tables(table_desc/table_type) + sys_table_fields(field_desc)。"""
    cur = conn.cursor()
    cur.execute("SELECT table_name, table_desc, table_type FROM sys_tables ORDER BY table_name")
    tbl_rows = cur.fetchall()
    cur.execute(
        "SELECT table_name, field_name, field_desc FROM sys_table_fields ORDER BY table_name, field_name"
    )
    fld_rows = cur.fetchall()
    cur.close()
    lines = ["表描述:"]
    for t, d, ty in tbl_rows:
        lines.append(f"  `{t}` [{ty}]: {d}")
    lines.append("字段描述:")
    for t, f, d in fld_rows:
        lines.append(f"  `{t}`.`{f}`: {d}")
    return "\n".join(lines)


def dump_er(conn):
    """ER 图:sys_foreignkeys 的 from -> to(含复合外键列序)。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT constraint_name, from_table, from_column, to_table, to_column, column_seq, column_count
        FROM sys_foreignkeys
        ORDER BY constraint_name, column_seq
        """
    )
    rows = cur.fetchall()
    cur.close()
    lines = ["外键关系(ER 图):"]
    for cname, ft, fc, tt, tc, seq, cnt in rows:
        marker = f" [复合外键 {seq}/{cnt}]" if cnt > 1 else ""
        lines.append(f"  {ft}.{fc} -> {tt}.{tc}{marker}")
    return "\n".join(lines)


def build_prompt(level, question, schema, dictionary, er):
    """按档拼提示词,注入元数据。"""
    parts = [
        "你是 Text2SQL 系统。根据下面给出的数据库结构，把用户的问题翻译成一条 MySQL SELECT 语句。",
        "只输出 SQL 本身，不要解释，不要 markdown 代码块，不要多余文字。",
        "",
        "【数据库结构】表名、列名、列类型：",
        schema,
    ]
    if level in ("S1", "S2"):
        parts += ["", "【数据字典】表描述与字段描述：", dictionary]
    if level == "S2":
        parts += ["", "【外键关系】ER 图：", er]
    parts += ["", "【问题】", question, "", "SQL："]
    return "\n".join(parts)


def extract_sql(text):
    """从 LLM 回复里提取第一条 SELECT 语句。"""
    if not text:
        return ""
    # 去 markdown 代码块
    text = re.sub(r"```(?:sql)?", "", text)
    # 取第一个 SELECT 开始到分号或结尾
    m = re.search(r"\bSELECT\b.*", text, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    sql = m.group(0)
    sql = sql.split(";")[0]
    return sql.strip()


def make_llm(model, base_url, api_key):
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0,
        timeout=LLM_TIMEOUT,
    )


def run_one(llm, level, q, gold_rows, schema, dictionary, er, conn):
    prompt = build_prompt(level, q["question"], schema, dictionary, er)
    result = {
        "question_id": q["id"],
        "s_level": level,
        "final_sql": "",
        "pass": False,
        "error": None,
    }
    try:
        resp = llm.invoke(prompt)
        sql = extract_sql(resp.content)
        result["final_sql"] = sql
        if not sql:
            result["error"] = "no sql extracted"
            return result
        cand = execute_sql(conn, sql)
        result["pass"] = results_equal(gold_rows, cand)
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["pass"] = False
    return result


def load_json(p):
    return json.loads(Path(p).read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="逗号分隔题号")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--levels", default="S0,S1,S2")
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--base-url", default="https://api.deepseek.com")
    ap.add_argument("--results", default="results_singleshot.json")
    args = ap.parse_args()

    questions = load_json(QUESTIONS_JSON)
    gold = {g["id"]: g for g in load_json(GOLD_JSON)}
    levels = [x.strip() for x in args.levels.split(",") if x.strip()]

    if args.all:
        selected = questions
    elif args.ids:
        ids = {x.strip() for x in args.ids.split(",") if x.strip()}
        selected = [q for q in questions if q["id"] in ids]
    else:
        print("用 --ids 或 --all 指定题")
        sys.exit(2)

    # 元数据 dump(一次性)
    conn_meta = _connect(DB_META)
    try:
        schema = dump_schema(conn_meta)
        dictionary = dump_dictionary(conn_meta)
        er = dump_er(conn_meta)
    finally:
        conn_meta.close()

    results_json = DATA_DIR / args.results
    llm = make_llm(args.model, args.base_url, _read_key(args.base_url))

    # 断点续跑
    existing = set()
    runs = []
    if results_json.exists():
        d = load_json(results_json)
        runs = d.get("runs", [])
        existing = {(r["question_id"], r["s_level"]) for r in runs}

    todo = [(q, lvl) for q in selected for lvl in levels if (q["id"], lvl) not in existing]
    print(f"共 {len(todo)} 次待跑({len(selected)} 题 × {len(levels)} 档),已跳过 {len(existing)} 次")

    conn = _connect(DB_DATA)
    try:
        for i, (q, lvl) in enumerate(todo, 1):
            print(f"\n[{i}/{len(todo)}] {q['id']} ({lvl}) ...", flush=True)
            r = run_one(llm, lvl, q, gold[q["id"]]["rows"], schema, dictionary, er, conn)
            runs.append(r)
            results_json.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2))
            st = "✅" if r["pass"] else ("⚠️" if r["error"] else "❌")
            print(f"    {st} pass={r['pass']} sql={r['final_sql'][:60]!r} err={r['error']}")
    finally:
        conn.close()

    # 报告
    print(f"\n{'=' * 60}\n== 报告(S 系列 single-shot)==")
    ex = {}
    for lvl in levels:
        lv = [r for r in runs if r["s_level"] == lvl]
        if not lv:
            continue
        passed = sum(1 for r in lv if r["pass"])
        ex[lvl] = passed / len(lv)
        print(f"\n{lvl}: EX {passed}/{len(lv)} = {ex[lvl]*100:.1f}%")
        fails = [r["question_id"] for r in lv if not r["pass"]]
        if fails:
            print(f"    失败: {', '.join(fails)}")
    if len(ex) > 1:
        base = levels[0]
        for lvl in levels[1:]:
            d = ex[lvl] - ex[base]
            print(f"\nΔ({base}->{lvl}) = {d*100:+.1f} 个百分点")


if __name__ == "__main__":
    main()
