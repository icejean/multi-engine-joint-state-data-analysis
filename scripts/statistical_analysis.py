#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 统计严谨性分析：McNemar 显著性 + bootstrap 95% CI + pass@k 曲线。

零 LLM 成本——全部从现有 pass^3 三轮结果文件重算。

口径（对齐 stateful-analysis-report §2.2）：
  pass@1(平均)  = 三轮准确率平均 = 378 次作答池的答对比例（能力）
  pass^3(全对)  = 三轮全对题占比（可靠性下界）
  并集(≥1 对)   = 三轮里至少一次对的题占比（给三次机会能答对）
  pass@k        = 三轮里至少 k 次对的题占比

McNemar 用「每题一个二元结果」两种口径：
  并集口径：该题三轮至少一次对 = 1
  全对口径：该题三轮全对 = 1
采用精确 McNemar（二项检验，不依赖 scipy）。

用法：python scripts/statistical_analysis.py
"""
import json
import math
from collections import defaultdict

WC = "data/works_cycles"


def load(f):
    return json.load(open(f))["runs"]


def by_qid(runs, lvkey, lvl):
    """返回 {question_id: pass_bool}，只取指定档位。"""
    return {r["question_id"]: bool(r.get("pass")) for r in runs if r.get(lvkey) == lvl}


def load_3pass(prefix, lvkey, lvl):
    """读三轮，返回 {qid: [p1, p2, p3]}。"""
    acc = defaultdict(list)
    for p in [1, 2, 3]:
        f = f"{WC}/{prefix}{p}.json"
        for qid, ok in by_qid(load(f), lvkey, lvl).items():
            acc[qid].append(ok)
    return acc


def stats(triples):
    """triples: {qid: [3 bool]} → 各种口径的比例。"""
    n = len(triples)
    avg = sum(sum(v) for v in triples.values()) / (3 * n)          # pass@1 平均
    all3 = sum(1 for v in triples.values() if all(v)) / n          # pass^3 全对
    ge1 = sum(1 for v in triples.values() if any(v)) / n           # 并集
    ge2 = sum(1 for v in triples.values() if sum(v) >= 2) / n      # pass@2
    return {"n": n, "avg": avg, "all3": all3, "ge1": ge1, "ge2": ge2}


def exact_mcnemar(b, c):
    """精确 McNemar：b,c 是不一致对。p = 2*P(Bin(b+c,0.5) <= min(b,c))。"""
    n = b + c
    if n == 0:
        return 1.0
    m = min(b, c)
    p_tail = sum(math.comb(n, k) for k in range(m + 1)) / (2 ** n)
    return min(1.0, 2 * p_tail)


def mcnemar(triples_a, triples_b, mode="union"):
    """配对 McNemar，返回 (b, c, p)。b: a对b错；c: a错b对。"""
    qids = set(triples_a) & set(triples_b)
    b = c = 0
    for q in qids:
        va, vb = triples_a[q], triples_b[q]
        if mode == "union":
            a_ok, b_ok = any(va), any(vb)
        else:  # all3
            a_ok, b_ok = all(va), all(vb)
        if a_ok and not b_ok:
            b += 1
        elif not a_ok and b_ok:
            c += 1
    return b, c, exact_mcnemar(b, c)


def bootstrap_ci(triples, metric="avg", n_boot=10000, seed=42):
    """对题集重采样，返回 (lo, hi) 95% 百分位 CI。"""
    import random
    rng = random.Random(seed)
    qids = list(triples.keys())
    n = len(qids)
    vals = []
    for _ in range(n_boot):
        samp = [triples[qids[rng.randrange(n)]] for _ in range(n)]
        if metric == "avg":
            v = sum(sum(s) for s in samp) / (3 * len(samp))
        elif metric == "all3":
            v = sum(1 for s in samp if all(s)) / len(samp)
        elif metric == "ge1":
            v = sum(1 for s in samp if any(s)) / len(samp)
        else:
            v = sum(1 for s in samp if sum(s) >= 2) / len(samp)
        vals.append(v)
    vals.sort()
    return vals[int(0.025 * n_boot)], vals[int(0.975 * n_boot)]


def fmt(ratio, lo=None, hi=None):
    s = f"{ratio*100:5.1f}%"
    if lo is not None:
        s += f"  [CI {lo*100:.1f}–{hi*100:.1f}]"
    return s


def main():
    # 三轮数据
    mplus = load_3pass("results_wc_mplus_126_pass", "m_level", "M0")
    s1 = load_3pass("results_wc_s_full_pass", "s_level", "S1")
    s2 = load_3pass("results_wc_s_full_pass", "s_level", "S2")
    m0 = load_3pass("results_wc_m_126_full_pass", "m_level", "M0")
    m1 = load_3pass("results_wc_m_126_full_pass", "m_level", "M1")
    m2 = load_3pass("results_wc_m_126_full_pass", "m_level", "M2")

    print("=" * 78)
    print("一、各档准确率 + bootstrap 95% CI（三轮）")
    print("=" * 78)
    s0 = load_3pass("results_wc_s_full_pass", "s_level", "S0")
    rows = [("M+S M0", mplus), ("S0", s0), ("S1", s1), ("S2", s2),
            ("M0", m0), ("M1", m1), ("M2", m2)]
    print(f"{'档':8} {'pass@1(平均)':22} {'pass^3(全对)':22} {'并集(≥1对)':20} {'pass@2':18}")
    for name, t in rows:
        st = stats(t)
        ci_avg = bootstrap_ci(t, "avg")
        ci_all3 = bootstrap_ci(t, "all3")
        print(f"{name:8} {fmt(st['avg'], *ci_avg):22} {fmt(st['all3'], *ci_all3):22} "
              f"{fmt(st['ge1']):20} {fmt(st['ge2']):18}")

    print()
    print("=" * 78)
    print("二、配对 McNemar 检验（M+S M0 vs 各对照）")
    print("=" * 78)
    for mode, label in [("union", "并集口径(≥1对)"), ("all3", "全对口径(pass^3)")]:
        print(f"\n[{label}]")
        mkey = "ge1" if mode == "union" else "all3"
        for name, other in [("S1(single-shot 字典)", s1), ("S2(single-shot 满配)", s2),
                            ("M0(纯探索 裸)", m0), ("M1(纯探索 字典)", m1), ("M2(纯探索 满配)", m2)]:
            b, c, p = mcnemar(mplus, other, mode)
            os_ = stats(other)
            print(f"  M+S M0 vs {name:22}  b={b:3} c={c:3}  p={p:.4f}"
                  f"   (M+S {fmt(stats(mplus)[mkey])} vs "
                  f"{name.split('(')[0]:4} {fmt(os_[mkey])})")

    print()
    print("=" * 78)
    print("三、pass@k 曲线（M+S M0，k = 至少 k 次对）")
    print("=" * 78)
    st = stats(mplus)
    n = st["n"]
    for k, v in [("pass@1 (≥1对)", st["ge1"]), ("pass@2 (≥2对)", st["ge2"]), ("pass@3 (全对)", st["all3"])]:
        cnt = round(v * n)
        print(f"  {k:16} {cnt}/{n} = {v*100:.1f}%")

    print()
    print("注：M+S 只跑了 M0 档；S/M 各档均 126 题 × 3 轮。")


if __name__ == "__main__":
    main()
