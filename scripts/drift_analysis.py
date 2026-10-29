#!/usr/bin/env python3
"""pass^k 漂移分析:读 N 轮 results 文件,diff 出稳定对/稳定错/翻转题 + 轮间漂移率/总漂移率。

用法:
    python drift_analysis.py --db formula_1 --results results_f1_pass3_run1.json,results_f1_pass3_run2.json,results_f1_pass3_run3.json

输出(对齐 semantic-drift-methodology.md 的口径):
  - 每轮 EX
  - 稳定对(全轮 pass)、稳定错(全轮 fail)
  - 翻转题(至少一次 pass 一次 fail)
  - 轮间漂移率 = Σ相邻轮对翻转数 / (题数 × 轮对数)
  - 总漂移率 = 至少翻一次的题数 / 题数
"""
import argparse
import json
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["runs"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--results", required=True, help="逗号分隔的 results 文件名(相对 data/{db}/)")
    args = ap.parse_args()

    ddir = Path(__file__).resolve().parent.parent / "data" / args.db
    files = [ddir / f for f in args.results.split(",")]

    rounds = []
    for f in files:
        runs = load(f)
        scored = [r for r in runs if r.get("pass") is not None]
        passed = sum(1 for r in scored if r["pass"])
        rounds.append({"file": f.name, "runs": runs, "scored": scored,
                       "passed": passed, "ex": passed / len(scored) if scored else float("nan")})

    # 对齐题集(取交集题号)
    common = set(rounds[0]["scored"][0]["question_id"] for _ in [0])
    common = {r["question_id"] for r in rounds[0]["scored"]}
    for rd in rounds[1:]:
        common &= {r["question_id"] for r in rd["scored"]}

    print(f"{args.db}: {len(rounds)} 轮, 共同题 {len(common)} 道\n")
    print("== 每轮 EX ==")
    for i, rd in enumerate(rounds, 1):
        print(f"  r{i} ({rd['file']}): {rd['ex']*100:.1f}% ({rd['passed']}/{len(rd['scored'])})")

    # 每题在各轮的 pass 序列
    seq = {}
    for qid in sorted(common):
        seq[qid] = []
        for rd in rounds:
            m = {r["question_id"]: r for r in rd["scored"]}
            seq[qid].append(m[qid]["pass"])

    stable_pass = [q for q, s in seq.items() if all(s)]
    stable_fail = [q for q, s in seq.items() if not any(s)]
    flip = [q for q, s in seq.items() if any(s) and not all(s)]

    print(f"\n== 稳定性 ==")
    print(f"  稳定对: {len(stable_pass)}/{len(common)} = {len(stable_pass)/len(common)*100:.1f}%")
    print(f"  稳定错: {len(stable_fail)} 题 -> {stable_fail}")
    print(f"  翻转题: {len(flip)}/{len(common)} = {len(flip)/len(common)*100:.1f}% -> {flip}")

    # 轮间翻转计数
    pair_flips = 0
    for i in range(len(rounds) - 1):
        for qid in common:
            if seq[qid][i] != seq[qid][i + 1]:
                pair_flips += 1
    n_pairs = len(common) * (len(rounds) - 1)
    print(f"\n== 漂移率 ==")
    print(f"  轮间翻转: {pair_flips} 次 / {n_pairs} 题对 = {pair_flips/n_pairs*100:.1f}% (轮间漂移率)")
    print(f"  总漂移率: {len(flip)}/{len(common)} = {len(flip)/len(common)*100:.1f}%")

    # 翻转题的各轮模式
    if flip:
        print(f"\n== 翻转题模式(P=pass, F=fail) ==")
        for q in flip:
            pat = "".join("P" if s else "F" for s in seq[q])
            print(f"  Q{q}: {pat}")


if __name__ == "__main__":
    main()
