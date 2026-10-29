#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B1 收尾：同库 single-shot vs M+S 领先幅度 + 配对 McNemar。

数据源：
  single-shot（B1，deepseek-v4-flash 单发）：
    data/{db}/results_{db}_ss_s1.json   （schema 注入，无 notes）
    data/{db}/results_{db}_ss_s1n.json  （schema + notes 注入）
  M+S（pass^3，三轮）：
    data/{db}/results_{db}_pass3_run{1,2,3}.json

口径（对齐 statistical_analysis.py）：
  single-shot：每题一个二元结果（单发）。
  M+S：每题三个结果 → pass@1(平均) / pass^3(全对) / 并集(≥1对)。
  McNemar：精确二项检验，配对同一题号；single-shot 单发 vs M+S 两种口径
    （union = M+S 三轮至少一次对；all3 = 三轮全对）。

用法：python scripts/analyze_b1_singleshot.py
"""
import json
import math
from collections import defaultdict


def load_singleshot(path):
    runs = json.load(open(path))["runs"]
    return {str(r["question_id"]): bool(r.get("pass")) for r in runs}


def load_3pass(prefix, n=3):
    acc = defaultdict(list)
    for p in range(1, n + 1):
        f = f"{prefix}{p}.json"
        for r in json.load(open(f))["runs"]:
            acc[str(r["question_id"])].append(bool(r.get("pass")))
    return acc


def exact_mcnemar(b, c):
    n = b + c
    if n == 0:
        return 1.0
    m = min(b, c)
    p_tail = sum(math.comb(n, k) for k in range(m + 1)) / (2 ** n)
    return min(1.0, 2 * p_tail)


def mcnemar_ss_vs_3(ss, triple, mode="union"):
    """ss: {qid: bool}；triple: {qid: [3 bool]}。
    返回 (b, c, p)：b = M+S对且SS错，c = SS对且M+S错。"""
    qids = set(ss) & set(triple)
    b = c = 0
    for q in qids:
        ss_ok = ss[q]
        m_ok = any(triple[q]) if mode == "union" else all(triple[q])
        if m_ok and not ss_ok:
            b += 1
        elif ss_ok and not m_ok:
            c += 1
    return b, c, exact_mcnemar(b, c)


def stats3(triple):
    n = len(triple)
    avg = sum(sum(v) for v in triple.values()) / (3 * n)
    all3 = sum(1 for v in triple.values() if all(v)) / n
    ge1 = sum(1 for v in triple.values() if any(v)) / n
    return n, avg, all3, ge1


def main():
    # M+S 官方口径文件：financial 用 pass3_run（全 106 题 95.3%）；
    # formula_1 用 final_run（修 7 题后 97.1/93.6/93.0 → 94.6%，见 report §2.7）。
    for db, short, mplus_pfx in [
        ("financial", "fin", "results_fin_pass3_run"),
        ("formula_1", "f1", "results_f1_final_run"),
    ]:
        base = f"data/{db}"
        s1 = load_singleshot(f"{base}/results_{short}_ss_s1.json")
        s1n = load_singleshot(f"{base}/results_{short}_ss_s1n.json")
        mplus = load_3pass(f"{base}/{mplus_pfx}")

        n_m, avg, all3, ge1 = stats3(mplus)
        n_s1, r_s1 = len(s1), sum(s1.values()) / len(s1)
        n_s1n, r_s1n = len(s1n), sum(s1n.values()) / len(s1n)

        print("=" * 70)
        print(f"{db}：同库 single-shot vs M+S")
        print("=" * 70)
        print(f"  single-shot s1  (schema)      : {r_s1*100:5.1f}%  ({sum(s1.values())}/{n_s1})")
        print(f"  single-shot s1n (schema+notes): {r_s1n*100:5.1f}%  ({sum(s1n.values())}/{n_s1n})")
        print(f"  M+S pass@1(三轮平均)          : {avg*100:5.1f}%")
        print(f"  M+S pass^3(三轮全对)          : {all3*100:5.1f}%")
        print(f"  M+S 并集(≥1对)                : {ge1*100:5.1f}%")
        print()
        print(f"  领先幅度（M+S pass@1 vs single-shot）：")
        print(f"    vs s1   : {avg*100 - r_s1*100:+5.1f}pp")
        print(f"    vs s1n  : {avg*100 - r_s1n*100:+5.1f}pp")
        print()
        print(f"  配对 McNemar（M+S vs single-shot，同题 {len(set(s1)&set(mplus))} 题）：")
        for ss_name, ss in [("s1", s1), ("s1n", s1n)]:
            for mode, mlab in [("union", "并集"), ("all3", "全对")]:
                b, c, p = mcnemar_ss_vs_3(ss, mplus, mode)
                sig = "**显著**" if p < 0.05 else "不显著"
                print(f"    vs {ss_name:3} [{mlab:2}]  b={b:3}(M+S对SS错) "
                      f"c={c:3}(SS对M+S错)  p={p:.4f}  {sig}")
        print()


if __name__ == "__main__":
    main()
