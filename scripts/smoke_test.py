#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v0.8.0 元数据梯度实验 —— 冒烟测试。

验证端到端管线是否就绪，分三部分：

  Part A（可靠，无 LLM）—— 数据源与元数据
    1. 两个数据源已注册（读 ~/.openclaw/workspace/.datasources.json）
    2. sakila_rntl 无 sys 表；sakila_rntl_meta 有 3 张 sys 表，且列名与字典说明一致
    3. 16 张数据表行数与原库一致
  Part B（可靠）—— gold + 判分器
    4. gold.json 有 25 题、pilot 5 题在列
    5. score.py --selftest 通过（gold 自身 100%）
  Part C（可选 --with-agent，慢）—— 真实 Agent 驱动
    6. 调 `openclaw agent` 跑 D1（依赖字典的题），从 ~/log/<chat_id>.sql 提 SQL 判分

用法:
  /usr/lib64/anaconda3/envs/graphrag/bin/python scripts/smoke_test.py [--with-agent]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pymysql

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / ".." / "data" / "sakila"
GOLD_JSON = DATA_DIR / "gold.json"
QUESTIONS_JSON = DATA_DIR / "questions.json"

HOME = Path.home()
REGISTRY_PATHS = [
    HOME / ".openclaw" / "workspace" / ".datasources.json",
    HOME / ".dsh" / "workspace" / ".datasources.json",
]
DB_NAMES = {"M0": "sakila_rntl", "M2": "sakila_rntl_meta"}
DATA_TABLES = {
    "actr", "addr", "awd", "card", "catg", "city", "cnty", "cust", "doc", "film",
    "flm_act", "flm_cat", "invt", "lang", "pymt", "rntl", "staf", "stor",
}
SYS_COLUMNS = {
    "sys_tables": {"table_name", "table_desc", "table_type"},
    "sys_table_fields": {"table_name", "field_name", "field_desc"},
    "sys_foreignkeys": {"constraint_name", "from_table", "from_column", "to_table", "to_column", "column_seq", "column_count", "source", "confidence"},
}

PILOT_IDS = ["A3", "B1", "D1", "E2", "F2"]
_ok = 0
_bad = 0


def check(name, ok, detail=""):
    global _ok, _bad
    if ok:
        _ok += 1
        print(f"  ✅ {name}" + (f"  — {detail}" if detail else ""))
    else:
        _bad += 1
        print(f"  ❌ {name}" + (f"  — {detail}" if detail else ""))


def load_registry():
    """合并所有 workspace 的 .datasources.json，返回 {name: entry}。"""
    merged = {}
    for p in REGISTRY_PATHS:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text())
        except Exception as e:
            print(f"  ⚠️ 读 {p} 失败: {e}")
            continue
        for ds in data.get("datasources", []):
            merged[ds["name"]] = ds
    return merged


def connect(entry):
    return pymysql.connect(
        host=entry.get("host", "localhost"),
        port=int(entry.get("port", 3306)),
        user=entry["username"],
        password=entry["password"],
        charset="utf8mb4",
        database=entry["database"],
    )


def table_rows(conn, db):
    cur = conn.cursor()
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema=%s", (db,)
    )
    return {r[0] for r in cur.fetchall()}


def part_a():
    print("\n== Part A: 数据源与元数据 ==")
    reg = load_registry()
    check("数据源 sakila_rntl 已注册", "sakila_rntl" in reg)
    check("数据源 sakila_rntl_meta 已注册", "sakila_rntl_meta" in reg)
    if not ("sakila_rntl" in reg and "sakila_rntl_meta" in reg):
        print("  ⚠️ 数据源缺失，跳过连接检查")
        return

    # M0 库
    try:
        conn = connect(reg["sakila_rntl"])
        tables = table_rows(conn, "sakila_rntl")
        sys_tables = {t for t in tables if t.startswith("sys_")}
        check("sakila_rntl: 18 张数据表", DATA_TABLES.issubset(tables),
              f"数据表 {len(DATA_TABLES & tables)}/18")
        check("sakila_rntl: 无 sys 表", len(sys_tables) == 0, f"sys 表数={len(sys_tables)}")
        conn.close()
    except Exception as e:
        check("sakila_rntl 连接", False, str(e))

    # M2 库
    try:
        conn = connect(reg["sakila_rntl_meta"])
        tables = table_rows(conn, "sakila_rntl_meta")
        sys_tables = {t for t in tables if t.startswith("sys_")}
        check("sakila_rntl_meta: 18 张数据表", DATA_TABLES.issubset(tables),
              f"数据表 {len(DATA_TABLES & tables)}/18")
        check("sakila_rntl_meta: 3 张 sys 表", sys_tables == {"sys_tables", "sys_table_fields", "sys_foreignkeys"},
              f"sys 表={sorted(sys_tables)}")
        # 校验 sys 表列名与字典说明一致
        cur = conn.cursor()
        for t, want_cols in SYS_COLUMNS.items():
            cur.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s",
                ("sakila_rntl_meta", t),
            )
            got = {r[0] for r in cur.fetchall()}
            check(f"sys 表列名一致: {t}", got == want_cols, f"got={sorted(got)}")
        conn.close()
    except Exception as e:
        check("sakila_rntl_meta 连接", False, str(e))


def part_b():
    print("\n== Part B: gold + 判分器 ==")
    gold = json.loads(GOLD_JSON.read_text()) if GOLD_JSON.exists() else []
    check("gold.json 有 25 题", len(gold) == 25, f"{len(gold)} 题")
    ids = {g["id"] for g in gold}
    check("pilot 5 题在列", all(i in ids for i in PILOT_IDS), f"{sorted(set(PILOT_IDS) & ids)}")

    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "score.py"), "--selftest"],
        capture_output=True, text=True, timeout=120,
    )
    ok = r.returncode == 0 and "EX: 25/25" in r.stdout
    check("score.py --selftest 通过 (gold 自身 100%)", ok, f"rc={r.returncode}")


def part_c():
    print("\n== Part C: 真实 Agent 驱动（D1 × M0/M2）==")
    questions = {q["id"]: q for q in json.loads(QUESTIONS_JSON.read_text())}
    q = questions["D1"]
    from score import results_equal, execute_sql, _connect, _load_creds  # noqa: E402

    for m in ("M0", "M2"):
        ds = DB_NAMES[m]
        chat_id = uuid.uuid4().hex
        session_key = f"agent:main:portal-{chat_id}"
        # MCP server 读的 fallback（OpenClaw stdio 只继承 env 白名单）
        p = HOME / ".jupyter-mcp" / "current_chat_id"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(chat_id)

        msg = f"请使用数据源 {ds} 查询并回答下面的问题，只给出最终答案（一个数值即可），不要解释过程。\n\n{q['question']}"
        cmd = [
            "openclaw", "agent", "--agent", "main",
            "--session-key", session_key, "--message", msg,
            "--local", "--json", "--timeout", "180",
        ]
        env = os.environ.copy()
        env["DATAAI_CHAT_ID"] = chat_id
        env["AGENT_BACKEND"] = "openclaw"
        print(f"\n  ▶ {m} ({ds}) 运行中…")
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=210, env=env)
        except subprocess.TimeoutExpired:
            check(f"{m} agent 返回", False, "超时")
            continue
        if r.returncode != 0:
            check(f"{m} agent 返回", False, f"rc={r.returncode}: {r.stderr[:200]}")
            continue

        # 提取最终 SQL（审计日志里最后一条非注释 SQL）
        audit = HOME / "log" / f"{chat_id}.sql"
        final_sql = ""
        if audit.exists():
            for line in audit.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("//"):
                    final_sql = line
        check(f"{m} 审计日志有 SQL", bool(final_sql), f"audit={audit}")

        # 判分
        if final_sql:
            conn = _connect(ds)
            try:
                cand = execute_sql(conn, final_sql)
                ok = results_equal(q_rows_from_gold(q["id"]), cand)
                check(f"{m} 判分", ok, f"SQL={final_sql[:60]}")
            except Exception as e:
                check(f"{m} 判分", False, f"{e}")
            finally:
                conn.close()


def q_rows_from_gold(qid):
    gold = json.loads(GOLD_JSON.read_text())
    for g in gold:
        if g["id"] == qid:
            return g["rows"]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-agent", action="store_true")
    args = ap.parse_args()

    part_a()
    part_b()
    if args.with_agent:
        part_c()

    print(f"\n{'=' * 50}")
    print(f"冒烟测试结果: {_ok} 通过 / {_bad} 失败")
    sys.exit(1 if _bad else 0)


if __name__ == "__main__":
    main()
