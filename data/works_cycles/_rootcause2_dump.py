#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 2 次根因分析：全量错题结构化 dump（含 agent SQL vs gold SQL 实际结果 diff）。

对两轴最终结果里每一道「唯一错题」，dump：
  - 题目文本 / evidence / note(gold provenance) / source / domain / features
  - gold 混淆 SQL + gold rows（行数 + 前若干行）
  - 每个挂掉的档：agent final_sql + 实际执行结果（行数 + 前若干行）+ error + extra_columns
输出：_rootcause2_dump.json（供人工/后续脚本分析），不打印任何明文凭据。
"""
import json
import re
import sys
from pathlib import Path

import pymysql

HERE = Path(__file__).resolve().parent
DATA = HERE

DB_BY_LEVEL = {"M0": "works_cycles", "M1": "works_cycles_dict", "M2": "works_cycles_er"}
S_DB = "works_cycles"


def _load_creds():
    local = DATA.parent.parent / ".env"  # dataai-test/.env
    env_path = local if local.exists() else Path("/opt/dataai/templates/.env")
    creds = {}
    for line in env_path.read_text().splitlines():
        m = re.match(r"^\s*(MYSQLHOST|MYSQLPORT|MYSQLUSER|MYSQLPASSWORD)\s*=\s*(.*)\s*$", line)
        if m:
            creds[m.group(1)] = m.group(2)
    return creds


def _ser(v):
    if v is None:
        return None
    from datetime import date, datetime
    from decimal import Decimal
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def _exec(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    cols = [d[0] for d in (cur.description or [])]
    rows = cur.fetchall()
    return cols, [[_ser(v) for v in row] for row in rows]


def preview(rows, n=6):
    if not rows:
        return []
    return rows[:n]


def main():
    gold = {g["id"]: g for g in json.load(open(DATA / "gold.json"))}
    qset = {q["id"]: q for q in json.load(open(DATA / "question_set_final_obfuscated.json"))["questions"]}
    s_runs = json.load(open(DATA / "results_wc_s_full_v2.json"))["runs"]
    m_runs = json.load(open(DATA / "results_wc_m_126_full_v2.json"))["runs"]

    creds = _load_creds()
    conns = {}
    for db in ("works_cycles", "works_cycles_dict", "works_cycles_er"):
        conns[db] = pymysql.connect(
            host=creds.get("MYSQLHOST", "127.0.0.1"),
            port=int(creds.get("MYSQLPORT", 3306)),
            user=creds["MYSQLUSER"],
            password=creds["MYSQLPASSWORD"],
            charset="utf8mb4",
            database=db,
        )

    def wrong_instances(runs, lvkey):
        out = []
        for r in runs:
            if not r["pass"]:
                out.append((r["question_id"], r[lvkey], r))
        return out

    def build_axis(runs, lvkey, dbfn):
        # group wrong by question
        by_q = {}
        for r in runs:
            if not r["pass"]:
                by_q.setdefault(r["question_id"], []).append((r[lvkey], r))
        result = []
        for qid in sorted(by_q):
            q = qset.get(qid, {})
            g = gold[qid]
            rec = {
                "id": qid,
                "source": q.get("source"),
                "domain": q.get("domain"),
                "features": q.get("features"),
                "join_count": q.get("join_count"),
                "question": q.get("question"),
                "evidence": q.get("evidence"),
                "note": q.get("note"),
                "gold_sql": q.get("SQL_obfuscated"),
                "gold_rows": g["rows"],
                "gold_nrows": len(g["rows"]),
                "gold_preview": preview(g["rows"]),
                "fails": {},
            }
            # execute gold sql to get gold row count sanity (using S db / M0 db)
            try:
                gc, grow = _exec(conns[dbfn(qid)], rec["gold_sql"])
                rec["gold_sql_nrows_exec"] = len(grow)
            except Exception as e:
                rec["gold_sql_nrows_exec"] = f"ERR: {e}"
            for lv, r in sorted(by_q[qid], key=lambda x: x[0]):
                entry = {"level": lv, "final_sql": r.get("final_sql"), "error": r.get("error"),
                         "extra_columns": r.get("extra_columns")}
                if r.get("final_sql"):
                    try:
                        c, rows = _exec(conns[dbfn(qid)], r["final_sql"])
                        entry["cand_cols"] = c
                        entry["cand_nrows"] = len(rows)
                        entry["cand_preview"] = preview(rows)
                    except Exception as e:
                        entry["cand_nrows"] = f"ERR: {e}"
                        entry["cand_preview"] = []
                if "turns" in r:
                    entry["turns"] = r.get("turns")
                    entry["tool_calls"] = r.get("tool_calls")
                    entry["agent_text_tail"] = (r.get("agent_text") or "")[-400:]
                rec["fails"][lv] = entry
            result.append(rec)
        return result

    s_axis = build_axis(s_runs, "s_level", lambda qid: S_DB)
    m_axis = build_axis(m_runs, "m_level", lambda qid: DB_BY_LEVEL[m_runs and [r for r in m_runs if r["question_id"] == qid][0]["m_level"]])

    out = {"s_axis": s_axis, "m_axis": m_axis,
           "s_unique_wrong": [r["id"] for r in s_axis],
           "m_unique_wrong": [r["id"] for r in m_axis]}
    json.dump(out, open(DATA / "_rootcause2_dump.json", "w"), ensure_ascii=False, indent=2, default=str)
    for c in conns.values():
        c.close()
    print("S unique wrong:", out["s_unique_wrong"])
    print("M unique wrong:", out["m_unique_wrong"])
    print("dump written to _rootcause2_dump.json")


if __name__ == "__main__":
    main()
