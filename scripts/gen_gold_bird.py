#!/usr/bin/env python3
"""执行混淆后的 gold SQL -> gold.json, 并交叉验证混淆改写 + 迁移的正确性。

用法:
    python3 gen_gold_bird.py formula_1
    python3 gen_gold_bird.py financial

交叉验证: 每条题 原 SQL(跑 sqlite 原名) vs 混淆 SQL(跑 MySQL 混淆名) 结果一致
(行数一致 + 值多重集一致, 日期截断到日), 才算 transform/migrate 没写错。

输出:
    data/{db}/gold.json        可判分题的基准 (columns + rows, 来自 MySQL 混淆执行)
    data/{db}/gold_errors.json 被剔除的题 (原 SQL 执行失败 / 退化 gold / 交叉验证不一致)
"""
import argparse, json, os, re, sqlite3
from collections import Counter

import pymysql

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
DATA = os.path.join(ROOT, 'data')

from score import _ser, _load_creds  # noqa: E402

_AGG_RE = re.compile(r"\b(AVG|SUM|COUNT|MIN|MAX)\s*\(", re.I)
_GBY_RE = re.compile(r"\bGROUP\s+BY", re.I)


def _connect(db):
    creds = _load_creds()
    conn = pymysql.connect(host=creds.get('MYSQLHOST', '127.0.0.1'),
                           port=int(creds.get('MYSQLPORT', 3306)),
                           user=creds['MYSQLUSER'], password=creds['MYSQLPASSWORD'],
                           charset='utf8mb4', database=db)
    cur = conn.cursor()
    cur.execute("SET SESSION sql_mode = ''")  # 对齐 SQLite 宽松语义(去 ONLY_FULL_GROUP_BY 等)
    cur.close()
    return conn


def _norm_xval(v):
    """交叉验证用宽松规范化: 日期截断到日, 数值 2 位, NULL/空串等价。"""
    if v is None:
        return ('null', None)
    if isinstance(v, str):
        s = v.strip()
        if s == '':
            return ('null', None)
        m = re.match(r'^(\d{4}-\d{2}-\d{2})', s)
        if m:
            return ('date', m.group(1))
        try:
            return ('num', round(float(s), 2))
        except ValueError:
            return ('str', s)
    if isinstance(v, bool):
        return ('str', str(v))
    if isinstance(v, (int, float)):
        return ('num', round(float(v), 2))
    return ('str', str(v))


def _mset(rows):
    return Counter(tuple(sorted(_norm_xval(c) for c in row)) for row in rows)


def _is_degenerate_null(sql, rows):
    if not rows:
        return False
    if not all(c is None for row in rows for c in row):
        return False
    return bool(_AGG_RE.search(sql)) and not _GBY_RE.search(sql)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    args = ap.parse_args()
    db = args.db
    ddir = os.path.join(DATA, db)

    qs = json.load(open(os.path.join(ddir, 'question_set_obfuscated.json'), encoding='utf-8'))['questions']

    my = _connect(db)
    mcur = my.cursor()
    scon = sqlite3.connect(os.path.join(ddir, f'{db}.sqlite'))

    gold, errors = [], []
    xval_mismatch = 0
    for q in qs:
        qid = q['id']
        # 1. 原 SQL 跑 sqlite(原名)
        try:
            scur = scon.execute(q['SQL'])
            orig_cols = [d[0] for d in (scur.description or [])]
            orig_rows = [[_ser(v) for v in row] for row in scur.fetchall()]
        except Exception as e:
            errors.append({'id': qid, 'reason': f"原 SQL 执行失败(sqlite): {type(e).__name__}: {e}"})
            continue

        # 2. 混淆 SQL 跑 MySQL(混淆名)
        try:
            mcur.execute(q['SQL_obfuscated'].rstrip(';'))
            obf_cols = [d[0] for d in (mcur.description or [])]
            obf_rows = [[_ser(v) for v in row] for row in mcur.fetchall()]
        except Exception as e:
            errors.append({'id': qid, 'reason': f"混淆 SQL 执行失败(MySQL): {type(e).__name__}: {e}"})
            continue

        # 3. 交叉验证(行数 + 值多重集一致)
        if len(orig_rows) != len(obf_rows) or _mset(orig_rows) != _mset(obf_rows):
            xval_mismatch += 1
            # 行数相同但值不同 + ORDER BY..LIMIT → 大概率是平局/NULL 的非确定 gold, 非 transform bug
            if (len(orig_rows) == len(obf_rows)
                    and re.search(r'\bORDER\s+BY\b', q['SQL'])
                    and re.search(r'\bLIMIT\b', q['SQL'])):
                reason = f"非确定 gold(ORDER BY 平局/NULL + LIMIT): sqlite/MySQL 各 {len(orig_rows)} 行但值不同"
            else:
                reason = f"交叉验证不一致: sqlite {len(orig_rows)} 行 vs MySQL {len(obf_rows)} 行"
            errors.append({'id': qid, 'reason': reason})
            continue

        # 4. 退化 gold(空集聚合 -> NULL)
        if _is_degenerate_null(q['SQL_obfuscated'], obf_rows):
            errors.append({'id': qid, 'reason': '空集聚合→NULL(退化 gold)'})
            continue

        gold.append({
            'id': qid,
            'question_id': q['question_id'],
            'db_id': db,
            'join_count': q['join_count'],
            'features': q['features'],
            'difficulty': q['difficulty'],
            'columns': obf_cols,
            'rows': obf_rows,
        })

    mcur.close(); my.close(); scon.close()

    json.dump(gold, open(os.path.join(ddir, 'gold.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)
    json.dump(errors, open(os.path.join(ddir, 'gold_errors.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=2)

    print(f"{db}: {len(gold)}/{len(qs)} 题可判分")
    print(f"  交叉验证不一致: {xval_mismatch} 题")
    if errors:
        print(f"  剔除 {len(errors)} 题 -> gold_errors.json")
        for e in errors[:20]:
            print(f"    ✗ Q{e['id']:<3d} {e['reason'][:110]}")


if __name__ == '__main__':
    main()
