#!/usr/bin/env python3
"""
CypherBench 执行评测脚本（movie 子图）。

逐条执行 test_movie.json 的 gold_cypher，把返回结果与 answer_json 按
「排序后的多重集」比对，统计整体 + 按 from_template.match_category 的通过率。
同时也能反向验证导入的类型是否正确（类型错了，gold 查询会报错或对不上）。

用法:
    pip install neo4j
    python3 eval_movie.py [test_movie.json] [--db neo4j] [--limit N]

连接参数自动从 dataai-test/.env 读取（NEO4J_URI / NEO4J_USERNAME /
NEO4J_PASSWORD / NEO4J_DB），不覆盖已 export 的环境变量。
"""
import json
import os
import sys
import datetime
import argparse
from collections import defaultdict
from neo4j import GraphDatabase


def _load_env():
    """从脚本所在目录向上查找并加载 .env（不覆盖已存在的环境变量）。"""
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        p = os.path.join(d, '.env')
        if os.path.isfile(p):
            with open(p, encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    k = k.strip()
                    v = v.strip()
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                        v = v[1:-1]
                    os.environ.setdefault(k, v)
            return
        parent = os.path.dirname(d)
        if parent == d:
            return
        d = parent


_load_env()

URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
USER = os.environ.get('NEO4J_USERNAME', 'neo4j')
PASSWORD = os.environ.get('NEO4J_PASSWORD', 'neo4j')
DB = os.environ.get('NEO4J_DB', 'neo4j')


def canonical(v):
    """把 Neo4j 返回值规整成可 JSON 比对的普通类型。"""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, datetime.time):
        return v.isoformat()
    if isinstance(v, float):
        # 浮点求和顺序会带来 ULP 级差异（如 avg），四舍五入到 6 位小数消噪。
        return round(v, 6)
    if isinstance(v, (int, bool, str)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [canonical(x) for x in v]
    if isinstance(v, dict):
        return {k: canonical(x) for k, x in v.items()}
    return str(v)


def rows_key(rows):
    """把结果表（list[list]）转成可比较的多重集 key（排序后的 JSON 串列表）。"""
    return sorted(
        json.dumps([canonical(c) for c in row], sort_keys=True, ensure_ascii=False)
        for row in rows
    )


def answer_rows(q):
    """answer_json 在 test_movie.json 里是 JSON 字符串，解析成 list[list] 再比对。"""
    a = q['answer_json']
    return json.loads(a) if isinstance(a, str) else a


def run_query(tx, q):
    res = tx.run(q)
    return [list(r.values()) for r in res]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('test', nargs='?', default='test_movie.json')
    ap.add_argument('--db', default=DB)
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 条（0=全部）')
    ap.add_argument('--verbose', action='store_true', help='打印每条的结果')
    args = ap.parse_args()

    test = json.load(open(args.test))
    if args.limit:
        test = test[:args.limit]

    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    stats = defaultdict(lambda: {'total': 0, 'ok': 0, 'match': 0, 'errors': []})

    with driver.session(database=args.db) as session:
        for q in test:
            cat = (q.get('from_template') or {}).get('match_category', 'n/a')
            s = stats[cat]
            s['total'] += 1
            try:
                rows = session.execute_read(run_query, q['gold_cypher'])
                s['ok'] += 1
                matched = rows_key(rows) == rows_key(answer_rows(q))
                if matched:
                    s['match'] += 1
                status = 'OK ' if matched else 'MIS'
                if args.verbose or not matched:
                    print(f"[{status}] {cat:<28} {q['qid'][:8]}  {q['nl_question'][:70]}")
            except Exception as e:
                s['errors'].append((q['qid'], str(e)[:160]))
                print(f"[ERR] {cat:<28} {q['qid'][:8]}  {q['nl_question'][:70]}\n      {e}")

    driver.close()

    # 汇总
    print('\n' + '=' * 72)
    print(f"{'match_category':<32}{'total':>6}{'执行OK':>8}{'匹配':>7}{'匹配率':>9}")
    print('-' * 72)
    tot = ok = mt = 0
    for cat in sorted(stats, key=lambda c: -stats[c]['total']):
        s = stats[cat]
        tot += s['total']; ok += s['ok']; mt += s['match']
        rate = f"{s['match']/s['total']*100:.1f}%" if s['total'] else '-'
        print(f"{cat:<32}{s['total']:>6}{s['ok']:>8}{s['match']:>7}{rate:>9}")
    print('-' * 72)
    print(f"{'合计':<32}{tot:>6}{ok:>8}{mt:>7}{mt/tot*100:>8.1f}%")
    err_total = sum(len(s['errors']) for s in stats.values())
    if err_total:
        print(f"\n执行报错 {err_total} 条（类型或数据问题会集中体现在这里）")


if __name__ == '__main__':
    main()
