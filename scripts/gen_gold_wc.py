#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行 works_cycles 题库的 SQL_obfuscated,生成 gold.json(结果集比对基准)。

- 单一事实来源: data/works_cycles/question_set_final_obfuscated.json(每条题的 SQL_obfuscated 字段)
- 对 works_cycles 库执行(与 works_cycles_dict / works_cycles_er 数据表一致)
- 输出:
    data/works_cycles/gold.json        —— 可判分题的基准(供 run_bench_wc.py 比对)
    data/works_cycles/gold_errors.json —— 被剔除的题(不进入 Δ₄ 判分)
- 判分规则沿用 score.py 的 results_equal(值多重集比对,忽略行序/列序,数值 2 位容差)

剔除两类题(保证 Δ₄ 基线干净):
  1. 执行失败 —— BIRD 标注噪声 / MySQL 方言差异导致 gold SQL 报错
  2. 退化 gold —— 「空集聚合 → NULL」:聚合函数(AVG/SUM/MIN/MAX)对空集求值返回 NULL
     (即 WHERE 匹配 0 行)。这种 gold 任何碰巧返回 NULL 的错误答案都会判对,
     污染差分信号,故剔除。

注意:gold 结果为「选中列本身全 NULL」(如 Q61 网站链接为空)或「部分单元格 NULL」
(如 Q76 地址第二行)属于真实数据特征,保留——它们测的是 agent 能否忠实返回 NULL 而非编造。
"""
import json
import os
import re

import pymysql

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WC_DIR = os.path.join(SCRIPT_DIR, "..", "data", "works_cycles")
QUESTIONS_JSON = os.path.join(WC_DIR, "question_set_final_obfuscated.json")
OUT_GOLD = os.path.join(WC_DIR, "gold.json")
OUT_ERRORS = os.path.join(WC_DIR, "gold_errors.json")

GOLD_DB = "works_cycles"   # 三库数据表一致,只对裸库跑一遍

from score import _ser, _load_creds  # noqa: E402

# 「空集聚合 → NULL」检测:结果非空但全 NULL,且 SQL 是无 GROUP BY 的聚合查询
_AGG_RE = re.compile(r"\b(AVG|SUM|COUNT|MIN|MAX)\s*\(", re.I)
_GBY_RE = re.compile(r"\bGROUP\s+BY", re.I)


def _is_degenerate_null(sql, rows):
    """空集聚合 → NULL:结果非空但全 NULL,且 SQL 是无 GROUP BY 的聚合查询。"""
    if not rows:
        return False
    if not all(c is None for row in rows for c in row):
        return False
    return bool(_AGG_RE.search(sql)) and not _GBY_RE.search(sql)


def main():
    with open(QUESTIONS_JSON, encoding="utf-8") as f:
        questions = json.load(f)["questions"]

    creds = _load_creds()
    conn = pymysql.connect(
        host=creds.get("MYSQLHOST", "localhost"),
        port=int(creds.get("MYSQLPORT", 3306)),
        user=creds["MYSQLUSER"],
        password=creds["MYSQLPASSWORD"],
        charset="utf8mb4",
        database=GOLD_DB,
    )
    cur = conn.cursor()
    gold, errors = [], []
    print(f"{'id':>4s}  {'domain':14s} {'jc':>2s} {'rows':>6s}  首行")
    print("-" * 78)
    for q in questions:
        qid = q["id"]
        try:
            cur.execute(q["SQL_obfuscated"])
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            serialized = [[_ser(v) for v in row] for row in rows]
        except Exception as e:
            errors.append({"id": qid, "domain": q["domain"], "reason": f"执行失败: {type(e).__name__}: {e}"})
            print(f"{qid:4d}  {q['domain']:14s} {q['join_count']:2d}       ✗ {type(e).__name__}: {e}")
            continue

        if _is_degenerate_null(q["SQL_obfuscated"], serialized):
            errors.append({"id": qid, "domain": q["domain"], "reason": "空集聚合→NULL(退化 gold)"})
            print(f"{qid:4d}  {q['domain']:14s} {q['join_count']:2d}       ✗ 退化:空集聚合→NULL")
            continue

        gold.append({
            "id": qid,
            "domain": q["domain"],
            "join_count": q["join_count"],
            "features": q["features"],
            "columns": cols,
            "rows": serialized,
        })
        first = serialized[0] if serialized else []
        print(f"{qid:4d}  {q['domain']:14s} {q['join_count']:2d} {len(serialized):6d}  {first}")
    cur.close()
    conn.close()

    with open(OUT_GOLD, "w", encoding="utf-8") as f:
        json.dump(gold, f, ensure_ascii=False, indent=2)
    # 始终重写 errors 文件(空列表也写),避免上一轮的旧内容残留
    with open(OUT_ERRORS, "w", encoding="utf-8") as f:
        json.dump(errors, f, ensure_ascii=False, indent=2)

    print(f"\ngold 已写出: {OUT_GOLD} ({len(gold)}/{len(questions)} 题可判分)")
    if errors:
        print(f"剔除 {len(errors)} 题 → {OUT_ERRORS}")
        for e in errors:
            print(f"  ✗ Q{e['id']:<3d} {e['domain']:12s} {e['reason']}")


if __name__ == "__main__":
    main()
