#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行 test_movie.json 的 gold_cypher,生成 movie 的 gold.json(判分基准)。

- 单一事实来源: data/movie/test_movie.json(每条题的 gold_cypher + answer_json)
- 对 movie 图库执行 gold_cypher,得到「真实结果行」,作为判分基准
- 输出 data/movie/gold.json:
    [{id, qid, match_category, question, gold_cypher, columns, rows}, ...]
    id            = 顺序整数(1..401,便于 --ids)
    match_category = CypherBench 模板分类,当 domain 用(报告分项)
    columns       = RETURN 别名(判「多输出列」备注用)
    rows          = 执行结果(已规整为 JSON 可序列化,经 score_cypher._ser)

与 gen_gold_wc.py 的差异: 图库无「空集聚合→NULL」的退化问题,也无 SQL 方言导致的
执行失败——test_movie.json 的 401 条 gold_cypher 已全部验证过可执行且结果确定。
"""
import json
import os

from score_cypher import connect_graph, execute_cypher

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MOVIE_DIR = os.path.join(SCRIPT_DIR, "..", "data", "movie")
QUESTIONS_JSON = os.path.join(MOVIE_DIR, "test_movie.json")
OUT_GOLD = os.path.join(MOVIE_DIR, "gold.json")


def main():
    with open(QUESTIONS_JSON, encoding="utf-8") as f:
        questions = json.load(f)

    driver, database = connect_graph()
    gold, errors = [], []
    print(f"{'id':>4s}  {'match_category':30s} {'rows':>6s}  首行")
    print("-" * 84)
    try:
        for i, q in enumerate(questions, 1):
            cat = (q.get("from_template") or {}).get("match_category", "n/a")
            try:
                cols, rows = execute_cypher(driver, database, q["gold_cypher"])
            except Exception as e:  # noqa: BLE001 —— 理论不会发生,防呆
                errors.append({"id": i, "qid": q["qid"], "reason": f"{type(e).__name__}: {e}"})
                print(f"{i:4d}  {cat:30s}       ✗ {type(e).__name__}: {e}")
                continue
            gold.append({
                "id": i,
                "qid": q["qid"],
                "match_category": cat,
                "question": q["nl_question"],
                "gold_cypher": q["gold_cypher"],
                "columns": cols,
                "rows": rows,
            })
            first = rows[0] if rows else []
            print(f"{i:4d}  {cat:30s} {len(rows):6d}  {first}")
    finally:
        driver.close()

    with open(OUT_GOLD, "w", encoding="utf-8") as f:
        json.dump(gold, f, ensure_ascii=False, indent=2)
    print(f"\ngold 已写出: {OUT_GOLD} ({len(gold)}/{len(questions)} 题)")
    if errors:
        print(f"⚠️ 执行失败 {len(errors)} 题:")
        for e in errors:
            print(f"  Q{e['id']}: {e['reason']}")


if __name__ == "__main__":
    main()
