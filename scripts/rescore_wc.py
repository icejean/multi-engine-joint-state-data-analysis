#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 works_cycles 结果文件按「新 gold」重判（静态，不调 LLM）。

用途：gold 修正（如 Q29/Q73/Q74）后，把已存盘的 final_sql 重新执行、与新 gold.json 比对，
更新 pass 字段。支持 M 轴 per-level 数据库（M0/M1/M2 三库数据表一致，但探索类 final_sql
引用的 sys 表不同，故按 level 连对应库）。

用法：
  python rescore_wc.py results_wc_m_126_full_v2.json
  python rescore_wc.py results_wc_s_full_v2.json --s   # S 轴全 levels 连 works_cycles
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import _connect, execute_sql_columns, results_equal_relaxed  # noqa: E402

WC_DIR = Path(__file__).resolve().parent.parent / "data" / "works_cycles"
DB_BY_LEVEL = {"M0": "works_cycles", "M1": "works_cycles_dict", "M2": "works_cycles_er"}


def rescore(results_file, is_s_axis=False):
    gold = {g["id"]: g for g in json.load(open(WC_DIR / "gold.json"))}
    d = json.load(open(WC_DIR / results_file))
    conns = {}
    changed = 0
    for r in d["runs"]:
        g = gold.get(r["question_id"])
        if g is None:
            continue
        if not r.get("final_sql"):
            r["pass"] = False
            continue
        db = "works_cycles" if is_s_axis else DB_BY_LEVEL.get(r["m_level"], "works_cycles")
        if db not in conns:
            conns[db] = _connect(db)
        old = r["pass"]
        try:
            _, cand_rows = execute_sql_columns(conns[db], r["final_sql"])
            r["pass"] = results_equal_relaxed(g["rows"], cand_rows)
        except Exception:
            r["pass"] = False
        if r["pass"] != old:
            changed += 1
    for c in conns.values():
        c.close()
    json.dump(d, open(WC_DIR / results_file, "w"), ensure_ascii=False, indent=2)
    return changed, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", help="results 文件名(相对 data/works_cycles)")
    ap.add_argument("--s", action="store_true", help="S 轴(全 levels 连 works_cycles)")
    args = ap.parse_args()
    changed, d = rescore(args.results, args.s)
    print(f"重判 {args.results}: pass 翻转 {changed} 处")
    runs = d["runs"]
    lvkey = "s_level" if args.s else "m_level"
    for lvl in (["S0", "S1", "S2"] if args.s else ["M0", "M1", "M2"]):
        lv = [r for r in runs if r.get(lvkey) == lvl]
        if lv:
            p = sum(1 for r in lv if r["pass"])
            print(f"  {lvl}: {p}/{len(lv)} = {p/len(lv)*100:.1f}%")


if __name__ == "__main__":
    main()
