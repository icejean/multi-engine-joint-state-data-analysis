#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行题库 gold SQL,生成 gold.json(结果集比对基准)。

- 单一事实来源:data/sakila/questions.json(题面 + gold_sql)。
- 对 sakila_rntl 执行(与 sakila_rntl_meta 数据一致)。
- 输出:data/sakila/gold.json + 控制台摘要。
"""
import json
import os
import re
from decimal import Decimal
from datetime import date, datetime

import pymysql

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data", "sakila")
QUESTIONS_JSON = os.path.join(DATA_DIR, "questions.json")
OUT_GOLD = os.path.join(DATA_DIR, "gold.json")


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


def main():
    with open(QUESTIONS_JSON, encoding="utf-8") as f:
        questions = json.load(f)

    creds = _load_creds()
    conn = pymysql.connect(
        host=creds.get("MYSQLHOST", "localhost"),
        port=int(creds.get("MYSQLPORT", 3306)),
        user=creds["MYSQLUSER"],
        password=creds["MYSQLPASSWORD"],
        charset="utf8mb4",
        database="sakila_rntl",
    )
    cur = conn.cursor()
    gold = []
    print(f"{'id':4s} {'type':10s} {'rows':>5s}  首行")
    print("-" * 70)
    for q in questions:
        cur.execute(q["gold_sql"])
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        serialized = [[_ser(v) for v in row] for row in rows]
        gold.append({
            "id": q["id"],
            "type": q["type"],
            "hop": q["hop"],
            "columns": cols,
            "rows": serialized,
        })
        first = serialized[0] if serialized else []
        print(f"{q['id']:4s} {q['type']:10s} {len(serialized):5d}  {first}")
    cur.close()
    conn.close()

    with open(OUT_GOLD, "w", encoding="utf-8") as f:
        json.dump(gold, f, ensure_ascii=False, indent=2)
    print(f"\ngold 已写出: {OUT_GOLD}")


if __name__ == "__main__":
    main()
