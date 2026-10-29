#!/usr/bin/env python3
"""收敛曲线汇总:读一轮 results 文件,统计准确率/耗时/token/工具调用,追加进 convergence_curve.json。

用法:
    python summarize_convergence.py --db formula_1 --results results_f1_round1.json \
        --round 1 --notes "empty(从零)"
    python summarize_convergence.py --db formula_1 --results results_f1_round2.json \
        --round 2 --notes "第2轮(+圈速TIME_TO_SEC坑)"

输出 data/{db}/convergence_curve.json: {db, rounds:[{round, notes, accuracy, avg_*, total_*, ...}]}
每轮一进条目,同 round 覆盖旧条目,用于画收敛曲线(x=round, y=accuracy/cost/time)。
"""
import argparse
import json
from pathlib import Path


def _stat(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--results", required=True, help="results 文件(相对 data/{db}/)")
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--notes", default="", help="本轮 notes 描述")
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--backend", default="openclaw")
    ap.add_argument("--convergence", default=None, help="收敛文件(默认 data/{db}/convergence_curve.json)")
    args = ap.parse_args()

    ddir = Path(__file__).resolve().parent.parent / "data" / args.db
    results_path = ddir / args.results
    conv_path = Path(args.convergence) if args.convergence else ddir / "convergence_curve.json"

    runs = json.loads(results_path.read_text(encoding="utf-8"))["runs"]

    total = len(runs)
    passed = sum(1 for r in runs if r.get("pass"))
    fails = [r["question_id"] for r in runs if not r.get("pass")]
    errors = {r["question_id"]: r.get("error") for r in runs if r.get("error")}

    def tok(r):
        t = r.get("tokens") or {}
        return {
            "total": t.get("total") or 0,
            "input": t.get("input") or 0,
            "cache_read": t.get("cache_read") or 0,
        }

    toks = [tok(r) for r in runs]
    entry = {
        "round": args.round,
        "notes": args.notes,
        "model": args.model,
        "backend": args.backend,
        "results_file": args.results,
        "total": total,
        "passed": passed,
        "accuracy": round(passed / total, 4) if total else None,
        "avg_tool_rounds": round(_stat([r.get("tool_rounds") for r in runs]), 2),
        "avg_tool_calls": round(_stat([r.get("tool_calls") for r in runs]), 2),
        "avg_elapsed_s": round(_stat([r.get("elapsed_seconds") for r in runs]), 2),
        "avg_tokens": round(_stat([t["total"] for t in toks])),
        "avg_input_tokens": round(_stat([t["input"] for t in toks])),
        "avg_cache_read": round(_stat([t["cache_read"] for t in toks])),
        "total_elapsed_s": round(sum(r.get("elapsed_seconds") or 0 for r in runs), 1),
        "total_tokens": sum(t["total"] for t in toks),
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in runs), 4),
        "fails": fails,
        "errors": errors,
    }

    if conv_path.exists():
        conv = json.loads(conv_path.read_text(encoding="utf-8"))
    else:
        conv = {"db": args.db, "rounds": []}
    conv["rounds"] = [e for e in conv["rounds"] if e["round"] != args.round]
    conv["rounds"].append(entry)
    conv["rounds"].sort(key=lambda e: e["round"])
    conv_path.write_text(json.dumps(conv, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"round {args.round}: EX {passed}/{total} = {passed/total*100:.1f}%")
    print(f"  均 tool_rounds={entry['avg_tool_rounds']} tool_calls={entry['avg_tool_calls']} "
          f"elapsed={entry['avg_elapsed_s']}s tokens={entry['avg_tokens']:,}")
    print(f"  total elapsed={entry['total_elapsed_s']:.0f}s tokens={entry['total_tokens']:,} "
          f"cost=${entry['cost_usd']}")
    if fails:
        print(f"  失败 {len(fails)} 题: {fails[:30]}")
    print(f"  -> {conv_path}")


if __name__ == "__main__":
    main()
