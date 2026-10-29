#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
判分引擎:候选 SQL → 执行 → 结果集比对 gold → EX / Δ₄ 报告。

判分规则(见 docs/exp-metadata-gradient.md §5,初版,实跑后微调):
  - 结果集按「值多重集」比对:忽略行序、列序、列名/别名
  - 数值按 2 位小数容差
  - NULL / None / 空字符串 视为等价
  - 单值 与 单行单列 视为等价(按值元组比对天然满足)

候选答案格式(candidate.json):
  {
    "answers": [
      {"question_id": "B1", "m_level": "M0", "final_sql": "SELECT ..."},
      ...
    ]
  }

用法:
  python score.py --candidates candidate.json
  python score.py --selftest     # 以 gold_sql 自身为候选,验证判分器(期望 100%)

M 档 → 数据库映射: M0 → sakila_rntl ; M1 → sakila_rntl_m1 ; M2 → sakila_rntl_meta(三者数据一致)。
"""
import argparse
import json
import os
import re
from collections import Counter
from decimal import Decimal
from datetime import date, datetime

import pymysql

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data", "sakila")
QUESTIONS_JSON = os.path.join(DATA_DIR, "questions.json")
GOLD_JSON = os.path.join(DATA_DIR, "gold.json")

DB_BY_LEVEL = {"M0": "sakila_rntl", "M1": "sakila_rntl_m1", "M2": "sakila_rntl_meta"}


def _load_creds():
    # 本地 .env 优先(开源第三方复现用),否则回退 Portal 模板路径(本机开发)
    local = os.path.join(SCRIPT_DIR, "..", ".env")
    env_path = local if os.path.exists(local) else "/opt/dataai/templates/.env"
    creds = {}
    with open(env_path) as f:
        for line in f:
            m = re.match(r"^\s*(MYSQLHOST|MYSQLPORT|MYSQLUSER|MYSQLPASSWORD)\s*=\s*(.*)\s*$", line)
            if m:
                creds[m.group(1)] = m.group(2)
    return creds


def _ser(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def _try_num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float, Decimal)):
        return round(float(v), 2)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        try:
            return round(float(s), 2)
        except ValueError:
            return None
    return None


def normalize_value(v):
    if v is None:
        return ("null", None)
    if isinstance(v, str) and v.strip() == "":
        return ("null", None)
    n = _try_num(v)
    if n is not None:
        return ("num", n)
    return ("str", str(v))


def normalize_rows(rows):
    """结果集 → 值行多重集。

    同时忽略行序与列序:每行先按「规范化值」排序(行内列序不敏感),
    再以行多重集比对(行序不敏感)。
    """
    return Counter(tuple(sorted(normalize_value(c) for c in row)) for row in rows)


def results_equal(gold_rows, cand_rows):
    return normalize_rows(gold_rows) == normalize_rows(cand_rows)


def execute_sql(conn, sql):
    s = sql.strip()
    if s.startswith("%%sql"):
        s = s[len("%%sql"):].strip()
    s = s.rstrip(";").strip()
    cur = conn.cursor()
    cur.execute(s)
    rows = cur.fetchall()
    return [[_ser(v) for v in row] for row in rows]


def execute_sql_columns(conn, sql):
    """执行 SQL,返回 (column_names, rows)。列名用于「多输出列」备注。"""
    s = sql.strip()
    if s.startswith("%%sql"):
        s = s[len("%%sql"):].strip()
    s = s.rstrip(";").strip()
    cur = conn.cursor()
    cur.execute(s)
    cols = [d[0] for d in (cur.description or [])]
    rows = cur.fetchall()
    return cols, [[_ser(v) for v in row] for row in rows]


def _row_counter(row):
    """一行 → 规范化值多重集(Counter)。"""
    return Counter(normalize_value(c) for c in row)


def _is_submultiset(g, c):
    """g 是否为 c 的子多重集(允许 c 多出值)。"""
    return all(c.get(k, 0) >= v for k, v in g.items())


def results_equal_relaxed(gold_rows, cand_rows):
    """放宽「多列」判分:候选每行可比 gold 多输出值(多列),只要 gold 每行的值集
    是某个候选行的子多重集即判对。仅放宽列数——行数仍须一致、行内 gold 值仍须落在
    同一候选行内(保留行分组)。列数相同 → 退化为严格比对(results_equal)。"""
    if len(gold_rows) != len(cand_rows):
        return False
    if not gold_rows:  # 两边都空
        return True
    if len(gold_rows[0]) == len(cand_rows[0]):
        return results_equal(gold_rows, cand_rows)
    gold_ms = [_row_counter(r) for r in gold_rows]
    cand_ms = [_row_counter(r) for r in cand_rows]
    # 按「能匹配的候选行数」升序处理(最受限优先),降低贪心歧义
    order = sorted(
        range(len(gold_ms)),
        key=lambda i: sum(1 for c in cand_ms if _is_submultiset(gold_ms[i], c)),
    )
    used = [False] * len(cand_ms)
    for i in order:
        g = gold_ms[i]
        for j, c in enumerate(cand_ms):
            if not used[j] and _is_submultiset(g, c):
                used[j] = True
                break
        else:
            return False
    return True


def _column_value_multisets(rows):
    """rows(行列表)转置为列值多重集列表。空 rows 返回 []。"""
    if not rows:
        return []
    ncol = len(rows[0])
    return [Counter(normalize_value(row[c]) for row in rows) for c in range(ncol)]


def diff_extra_columns(gold_rows, gold_cols, cand_rows, cand_cols):
    """按列值多重集匹配 gold 列与候选列,返回候选里对不上任何 gold 列的多余列名。

    用值多重集(非列名)匹配——agent 常用不同别名(如 nm vs component_name)。
    gold_cols / cand_cols 是与 rows 对齐的列名列表。匹配不上或无法判定返回 []。
    """
    if not gold_rows or not cand_rows:
        return []
    gold_ms = _column_value_multisets(gold_rows)
    cand_ms = _column_value_multisets(cand_rows)
    matched = [False] * len(cand_cols)
    for gm in gold_ms:
        for j, cm in enumerate(cand_ms):
            if not matched[j] and cm == gm:
                matched[j] = True
                break
    return [cand_cols[j] for j in range(len(cand_cols)) if not matched[j]]


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


def _score_level(conns, gold_by_id, answers, level):
    rows = [a for a in answers if a["m_level"] == level]
    if not rows:
        return None
    by_type = {}
    passed = 0
    fails = []
    for a in rows:
        qid = a["question_id"]
        gold = gold_by_id.get(qid)
        if gold is None:
            raise KeyError(f"未知 question_id: {qid}")
        db = DB_BY_LEVEL.get(level, "sakila_rntl")
        cand_rows = execute_sql(conns[db], a["final_sql"])
        ok = results_equal(gold["rows"], cand_rows)
        t = gold["type"]
        by_type.setdefault(t, [0, 0])
        by_type[t][1] += 1
        if ok:
            passed += 1
            by_type[t][0] += 1
        else:
            fails.append(qid)
    return {"level": level, "total": len(rows), "passed": passed, "by_type": by_type, "fails": fails}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    with open(QUESTIONS_JSON, encoding="utf-8") as f:
        questions = json.load(f)
    with open(GOLD_JSON, encoding="utf-8") as f:
        gold = json.load(f)
    gold_by_id = {g["id"]: g for g in gold}

    if args.selftest:
        # 以 gold_sql 自身为候选,验证判分闭环(期望 100%)
        answers = []
        for q in questions:
            for lvl in ("M0", "M1", "M2"):
                answers.append({"question_id": q["id"], "m_level": lvl, "final_sql": q["gold_sql"]})
    else:
        with open(args.candidates, encoding="utf-8") as f:
            answers = json.load(f)["answers"]

    creds = _load_creds()
    conns = {db: _connect(db) for db in ("sakila_rntl", "sakila_rntl_m1", "sakila_rntl_meta")}
    try:
        results = {}
        for lvl in ("M0", "M1", "M2"):
            r = _score_level(conns, gold_by_id, answers, lvl)
            if r is not None:
                results[lvl] = r
    finally:
        for c in conns.values():
            c.close()

    # 报告
    order = ["M0", "M1", "M2"]
    ex = {}
    for lvl in order:
        r = results.get(lvl)
        if not r:
            continue
        ex[lvl] = r["passed"] / r["total"]
        print(f"== {lvl} ==")
        print(f"  EX: {r['passed']}/{r['total']} = {ex[lvl]*100:.2f}%")
        for t, (p, tot) in sorted(r["by_type"].items()):
            print(f"    {t:10s} {p}/{tot}")
        if r["fails"]:
            print(f"  失败: {', '.join(r['fails'])}")

    if "M0" in ex:
        for lvl in ("M1", "M2"):
            if lvl in ex:
                d = ex[lvl] - ex["M0"]
                print(f"\nΔ₄({lvl}) = EX({lvl}) - EX(M0) = {d*100:+.2f} 个百分点")
        if "M1" in ex and "M2" in ex:
            num = ex["M1"] - ex["M0"]
            den = ex["M2"] - ex["M0"]
            capture = (num / den) if den else float("nan")
            print(f"收益捕获率 = Δ₄(M1)/Δ₄(M2) = {capture:.2f}")


if __name__ == "__main__":
    main()
