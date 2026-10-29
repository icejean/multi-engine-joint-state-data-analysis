#!/usr/bin/env python3
"""合并官方题集与自拟题集为一个最终题集。

用法:
    python3 merge_question_sets.py --official question_set_100.json \
                                   --custom custom_questions_24.json \
                                   --out question_set_final.json

每道题统一加 id 与 source(官方/自拟) 字段。
"""

import argparse, json
from collections import Counter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--official', default='question_set_100.json')
    ap.add_argument('--custom', default='custom_questions_24.json')
    ap.add_argument('--out', default='question_set_final.json')
    args = ap.parse_args()

    off_q = json.load(open(args.official))['questions']
    cus_q = json.load(open(args.custom))['questions']

    merged = []
    for i, q in enumerate(off_q, 1):
        merged.append({"id": i, "source": "official", **q})
    for i, q in enumerate(cus_q, len(off_q) + 1):
        q = {k: v for k, v in q.items() if k != 'source'}
        merged.append({"id": i, "source": "custom", **q})

    doc = {
        "name": "works_cycles_question_set_final",
        "description": f"三梯度测试最终题集：官方 {len(off_q)} + 自拟 {len(cus_q)} = {len(merged)}",
        "count": len(merged),
        "breakdown": {"official": len(off_q), "custom": len(cus_q)},
        "questions": merged,
    }
    json.dump(doc, open(args.out, 'w'), ensure_ascii=False, indent=2)
    print(f"合并完成: {len(off_q)} 官方 + {len(cus_q)} 自拟 = {len(merged)} 题 -> {args.out}")

    print("\n来源:", dict(Counter(q['source'] for q in merged)))
    print("领域:", dict(Counter(q['domain'] for q in merged)))
    print("join 分布:", dict(Counter(q['join_count'] for q in merged)))
    print("含 CTE(递归):", sum(1 for q in merged if 'CTE' in q['features']))


if __name__ == '__main__':
    main()
