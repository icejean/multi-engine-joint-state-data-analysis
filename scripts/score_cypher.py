#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cypher 判分引擎 —— score.py 的图库(Neo4j)版。

候选 Cypher → neo4j 执行 → 结果集与 gold 按「值多重集」比对 → EX 报告。

判分规则与 score.py 完全一致:
  - 结果集按「值多重集」比对:忽略行序、列序、列名/别名
  - 数值按 2 位小数容差
  - NULL / None / 空字符串 视为等价
  - 单值 与 单行单列 视为等价(按值元组比对天然满足)
  - 放宽多列:候选可比 gold 多输出列,只要 gold 每行的值集是某候选行的子多重集

与 score.py 的唯一差异是执行层:SQL 走 pymysql,这里走 neo4j 官方 driver。

连接来源(与 Cypher kernel 同一套):优先读 `~/.openclaw/workspace/.datasources.json`
里 type=neo4j 的 `movie` 条目(或第一个图库);没有才回落 `.env` 的 `NEO4J_*`。

用法:
  python score_cypher.py --candidates candidate.json
  python score_cypher.py --selftest     # 以 gold_cypher 自身为候选,验证判分闭环(期望 100%)
"""
import argparse
import json
import os
import re
from collections import Counter
from datetime import date, datetime, time as dtime

from neo4j import GraphDatabase
from neo4j import time as ntime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MOVIE_DIR = os.path.join(SCRIPT_DIR, "..", "data", "movie")
GOLD_JSON = os.path.join(MOVIE_DIR, "gold.json")
QUESTIONS_JSON = os.path.join(MOVIE_DIR, "test_movie.json")

# 数值比对容差(与 score.py 对齐:2 位小数)
NUM_ROUND = 2


# ── 值规整 ───────────────────────────────────────────────────────────────

def _ser(v):
    """neo4j 值 → JSON 可序列化的普通类型(用于落盘 gold 与回传比对)。"""
    if v is None:
        return None
    # neo4j.time.* 不是 datetime 子类,必须先判(见文件头注记)
    if isinstance(v, (ntime.Date, ntime.DateTime, ntime.Time)):
        return v.isoformat()
    if isinstance(v, ntime.Duration):
        return str(v)
    if isinstance(v, (datetime, date, dtime)):
        return v.isoformat()
    if isinstance(v, (int, float, bool, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [_ser(x) for x in v]
    if isinstance(v, dict):
        return {k: _ser(x) for k, x in v.items()}
    return str(v)


def _try_num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return round(float(v), NUM_ROUND)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        try:
            return round(float(s), NUM_ROUND)
        except ValueError:
            return None
    return None


def normalize_value(v):
    """单值 → (类型, 规范化值)。NULL/空串等价、数值按容差取整、其余按字符串。"""
    if v is None:
        return ("null", None)
    if isinstance(v, str) and v.strip() == "":
        return ("null", None)
    # 日期/时间 → isoformat 字符串(neo4j.time 与标准 datetime 都覆盖)
    if isinstance(v, (ntime.Date, ntime.DateTime, ntime.Time, datetime, date, dtime)):
        return ("str", v.isoformat())
    n = _try_num(v)
    if n is not None:
        return ("num", n)
    return ("str", str(v))


def normalize_rows(rows):
    """结果集 → 值行多重集(忽略行序与列序:行内按规范化值排序)。"""
    return Counter(tuple(sorted(normalize_value(c) for c in row)) for row in rows)


def results_equal(gold_rows, cand_rows):
    return normalize_rows(gold_rows) == normalize_rows(cand_rows)


# ── 放宽多列(与 score.py 同构) ───────────────────────────────────────────

def _row_counter(row):
    return Counter(normalize_value(c) for c in row)


def _is_submultiset(g, c):
    return all(c.get(k, 0) >= v for k, v in g.items())


def results_equal_relaxed(gold_rows, cand_rows):
    """放宽「多列」判分:候选每行可比 gold 多输出值,只要 gold 每行的值集是某候选
    行的子多重集。仅放宽列数——行数仍须一致、gold 值仍须落在同一候选行内。"""
    if len(gold_rows) != len(cand_rows):
        return False
    if not gold_rows:
        return True
    if len(gold_rows[0]) == len(cand_rows[0]):
        return results_equal(gold_rows, cand_rows)
    gold_ms = [_row_counter(r) for r in gold_rows]
    cand_ms = [_row_counter(r) for r in cand_rows]
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
    if not rows:
        return []
    ncol = len(rows[0])
    return [Counter(normalize_value(row[c]) for row in rows) for c in range(ncol)]


def diff_extra_columns(gold_rows, gold_cols, cand_rows, cand_cols):
    """按列值多重集匹配,返回候选里对不上任何 gold 列的多余列名(判对时备注用)。"""
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


# ── 连接 ─────────────────────────────────────────────────────────────────

def _load_env_file(path):
    cfg = {}
    for line in open(path, encoding="utf-8").read().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip().strip("'\"")
    return cfg


def _find_env():
    d = SCRIPT_DIR
    while True:
        p = os.path.join(d, ".env")
        if os.path.isfile(p):
            return p
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _datasource_entry():
    """从 per-user 注册表找 movie(或第一个 neo4j)图数据源。"""
    for base in ("~/.openclaw/workspace", "~/.dsh/workspace"):
        p = os.path.expanduser(os.path.join(base, ".datasources.json"))
        if not os.path.isfile(p):
            continue
        try:
            entries = json.load(open(p, encoding="utf-8")).get("datasources", [])
        except (OSError, ValueError):
            continue
        graphs = [e for e in entries if (e.get("type") or "").lower() == "neo4j"]
        if not graphs:
            continue
        for e in graphs:
            if e.get("name") == "movie":
                return e
        return graphs[0]
    return None


def connect_graph():
    """按数据源注册表(回落 .env)建 neo4j driver,返回 (driver, database)。"""
    entry = _datasource_entry()
    if entry:
        url = entry.get("url") or f"bolt://{entry.get('host', 'localhost')}:{entry.get('port', 7687)}"
        user = entry.get("username") or "neo4j"
        pwd = entry.get("password") or ""
        database = entry.get("database") or "neo4j"
    else:
        env = _find_env()
        cfg = _load_env_file(env) if env else {}
        url = cfg.get("NEO4J_URI", "bolt://localhost:7687")
        user = cfg.get("NEO4J_USERNAME", "neo4j")
        pwd = cfg.get("NEO4J_PASSWORD", "neo4j")
        database = cfg.get("NEO4J_DB", "neo4j")
    return GraphDatabase.driver(url, auth=(user, pwd)), database


# ── 执行 ─────────────────────────────────────────────────────────────────

def execute_cypher(driver, database, cypher):
    """执行一条 Cypher,返回 (column_names, rows)。列名用于「多输出列」备注。"""
    c = cypher.strip()
    # 防御:agent 可能误带 %%cypher 前缀或末尾分号
    c = re.sub(r"^%%cypher\b[^\n]*\n?", "", c, flags=re.I).strip()
    c = c.rstrip(";").strip()
    result = driver.execute_query(c, database_=database)
    cols = list(result.keys)
    rows = [[_ser(v) for v in r.values()] for r in result.records]
    return cols, rows


def score_candidate(driver, database, gold_rows, gold_cols, cand_cypher):
    """执行候选 Cypher 并与 gold 比对(放宽多列),返回 (pass, extra_columns, error)。"""
    try:
        cand_cols, cand_rows = execute_cypher(driver, database, cand_cypher)
    except Exception as e:  # noqa: BLE001 —— 判分要把执行错误当「答错」而非崩掉
        return False, [], f"{type(e).__name__}: {e}"
    ok = results_equal_relaxed(gold_rows, cand_rows)
    extra = diff_extra_columns(gold_rows, gold_cols, cand_rows, cand_cols) if ok else []
    return ok, extra, None


# ── 入口 ─────────────────────────────────────────────────────────────────

def _load_gold():
    with open(GOLD_JSON, encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    gold = _load_gold()
    gold_by_id = {g["id"]: g for g in gold}

    driver, database = connect_graph()
    try:
        if args.selftest:
            # 以 gold 自身的 gold_cypher 为候选,验证判分闭环(期望 100%)
            answers = [{"question_id": g["id"], "final_cypher": g["gold_cypher"]} for g in gold]
        else:
            with open(args.candidates, encoding="utf-8") as f:
                answers = json.load(f)["answers"]

        passed = 0
        fails = []
        for a in answers:
            qid = a["question_id"]
            g = gold_by_id.get(qid)
            if g is None:
                raise KeyError(f"未知 question_id: {qid}")
            ok, extra, err = score_candidate(
                driver, database, g["rows"], g.get("columns", []), a["final_cypher"]
            )
            if ok:
                passed += 1
            else:
                fails.append((qid, err or "结果不匹配"))
    finally:
        driver.close()

    print(f"EX: {passed}/{len(answers)} = {passed / len(answers) * 100:.2f}%")
    if fails:
        print(f"失败 {len(fails)} 条:")
        for qid, err in fails:
            print(f"  Q{qid}: {err}")


if __name__ == "__main__":
    main()
