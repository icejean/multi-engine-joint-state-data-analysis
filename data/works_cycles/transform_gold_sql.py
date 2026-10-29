#!/usr/bin/env python3
"""把 gold SQL 从「原名 + SQLite 方言」改写为「混淆名 + MySQL 方言」。

用法:
    python3 transform_gold_sql.py --questions question_set_final.json \
        --map obfuscation_map.json --out question_set_final_obfuscated.json

改写步骤:
    1. 重命名与表缩写冲突的 CTE 名(bom -> bt)
    2. 解析 FROM/JOIN 建 别名->表 映射
    3. 替换表名(FROM/JOIN 上下文, 长表名优先)
    4. 替换列名(别名.列 -> 别名.混淆列; 无别名列按全局唯一/单表解析)
    5. 方言翻译(|| -> CONCAT, strftime('%Y',x) -> YEAR(x), CAST(x AS REAL) -> DOUBLE)
"""

import argparse, json, re

# 与表缩写冲突的 CTE 名 -> 新名
CTE_RENAME = {'bom': 'bt'}

# 正则改写器处理不了的复杂 case(派生表输出列 / 子查询别名复用) -> 手写混淆 SQL
# 键用 SQL 里的特征子串做匹配, 避免整串空白不一致
HAND_OBFUSCATED = {
    "COUNT(T3.BusinessEntityID)":
        "SELECT COUNT(T3.ref1) FROM (SELECT T1.ref1 FROM emp AS T1 INNER JOIN prsn AS T2 "
        "ON T1.ref1 = T2.ref1 WHERE T2.sffx IS NULL GROUP BY T1.ref1) AS T3",
    "MAX(T1.RateChangeDate)":
        "SELECT AVG(T1.rt) FROM emp_pay_hist AS T1 INNER JOIN emp_dept_hist AS T2 "
        "ON T1.ref1 = T2.ref3 INNER JOIN dept AS T3 ON T2.ref2 = T3.dprt_id "
        "WHERE T1.rt_chng_dt = (SELECT MAX(T1.rt_chng_dt) FROM emp_pay_hist AS T1 "
        "INNER JOIN dept AS T2 ON T1.ref1 = T2.dprt_id)",
}

KEYWORDS = {'inner', 'left', 'right', 'outer', 'cross', 'join', 'on', 'using',
            'where', 'group', 'order', 'by', 'having', 'limit', 'offset', 'union',
            'all', 'as', 'select', 'from', 'and', 'or', 'not', 'null', 'in', 'is',
            'between', 'like', 'case', 'when', 'then', 'else', 'end', 'distinct',
            'exists', 'asc', 'desc', 'with', 'recursive'}


def build_alias_map(sql, table_set):
    """别名 -> 原表名"""
    alias_map = {}
    for m in re.finditer(r'\b(FROM|JOIN)\s+([A-Za-z_]\w*)', sql, re.I):
        table = m.group(2)
        if table not in table_set:
            continue
        rest = sql[m.end():m.end() + 40]
        am = re.match(r'\s+(?:AS\s+)?([A-Za-z_]\w*)', rest)
        alias = None
        if am and am.group(1).lower() not in KEYWORDS:
            alias = am.group(1)
        alias_map[alias or table] = table
    return alias_map


def build_global_col_map(omap):
    """列名 -> 混淆名(仅当全局唯一, 否则 None)"""
    g = {}
    for table, m in omap.items():
        for col, obf in m['columns'].items():
            if col in g and g[col] != obf:
                g[col] = None  # 有歧义
            else:
                g[col] = obf
    return g


def translate_concat(sql):
    """a || b || c -> CONCAT(a, b, c)"""
    atom = r"'[^']*'|[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?|\d+(?:\.\d+)?"
    pattern = rf"({atom})\s*(?:\|\|\s*(?:{atom})\s*)+"

    def repl(m):
        parts = re.split(r'\s*\|\|\s*', m.group(0))
        return 'CONCAT(' + ', '.join(parts) + ')'

    return re.sub(pattern, repl, sql)


def translate_dialect(sql):
    # || -> CONCAT
    sql = translate_concat(sql)
    # strftime('%Y', x) -> YEAR(x)
    sql = re.sub(r"STRFTIME\('%Y'\s*,\s*([^)]+)\)", r'YEAR(\1)', sql, flags=re.I)
    # CAST(x AS REAL) -> CAST(x AS DOUBLE)
    sql = re.sub(r'CAST\s*\((.*?)\s+AS\s+REAL\s*\)', r'CAST(\1 AS DOUBLE)', sql, flags=re.I | re.S)
    # IIF(cond, a, b) -> IF(cond, a, b)  (MySQL)
    sql = re.sub(r'\bIIF\s*\(', 'IF(', sql, flags=re.I)
    return sql


def resolve_using(sql, omap):
    """JOIN B USING(col) -> JOIN B ON(left.col_obf = right.col_obf)"""
    refs = []  # (表名, 别名, end位置)
    for m in re.finditer(r'\b(FROM|JOIN)\s+([A-Za-z_]\w*)(?:\s+(?:AS\s+)?([A-Za-z_]\w*))?', sql, re.I):
        if m.group(2) in omap:
            refs.append((m.group(2), m.group(3) or m.group(2), m.end()))

    def lookup(tbl, col):
        for c, o in omap[tbl]['columns'].items():
            if c.lower() == col.lower():
                return o
        return None

    for u in reversed(list(re.finditer(r'\bUSING\s*\(([^)]*)\)', sql, re.I))):
        cols = [c.strip() for c in u.group(1).split(',')]
        right = None
        for t, a, end in refs:
            if end < u.start():
                right = (t, a)
        if not right:
            continue
        parts = []
        for col in cols:
            ro = lookup(right[0], col)
            # 左表 = 除 right 外, 含该列的表
            lo = la = None
            for t, a, end in refs:
                if t != right[0]:
                    o = lookup(t, col)
                    if o:
                        lo, la = o, a
                        break
            if lo and ro:
                parts.append(f"{la}.{lo} = {right[1]}.{ro}")
        if parts:
            sql = sql[:u.start()] + "ON " + " AND ".join(parts) + sql[u.end():]
    return sql


def resolve_ambiguous_unqualified(sql, omap):
    """无别名歧义列(ProductID/BusinessEntityID等)按最近的 FROM/JOIN 表解析(双向)"""
    gcol = build_global_col_map(omap)
    ambiguous = {c for c, o in gcol.items() if o is None}
    if not ambiguous:
        return sql
    froms = [(m.start(), m.group(1)) for m in re.finditer(
        r'\b(?:FROM|JOIN)\s+([A-Za-z_]\w*)', sql, re.I) if m.group(1) in omap]
    if not froms:
        return sql
    reps = []
    for col in sorted(ambiguous, key=len, reverse=True):
        for m in re.finditer(rf'\b{re.escape(col)}\b', sql, re.I):
            if m.start() > 0 and sql[m.start() - 1] == '.':
                continue
            # 双向最近 FROM/JOIN 表
            table = min(froms, key=lambda x: abs(x[0] - m.start()))[1]
            for c, o in omap[table]['columns'].items():
                if c.lower() == col.lower():
                    reps.append((m.start(), m.end(), o))
                    break
    for start, end, o in sorted(reps, reverse=True):
        sql = sql[:start] + o + sql[end:]
    return sql


def add_derived_alias(sql):
    """MySQL 要求 FROM 子查询带别名"""
    return re.sub(r'(\bFROM\s+\(.*\))(\s*)$', r'\1 AS _d\2', sql)


def protect_strings(sql):
    """把字符串字面量换成占位符, 避免列名替换误伤字符串"""
    strings = []

    def repl(m):
        strings.append(m.group(0))
        return f"__QLIT{len(strings) - 1}__"

    return re.sub(r"'[^']*'", repl, sql), strings


def restore_strings(sql, strings):
    for i, s in enumerate(strings):
        sql = sql.replace(f"__QLIT{i}__", s)
    return sql


def transform_sql(sql, omap):
    table_set = set(omap.keys())

    # 0a. 预处理带引号的标识符(保留字列如 T3.'Group'), 先于字符串保护
    for table, m in omap.items():
        for col, obf in m['columns'].items():
            sql = re.sub(rf'\.(?:[\'"]){re.escape(col)}(?:[\'"])',
                         f'.{obf}', sql, flags=re.I)

    # 0. 保护字符串字面量
    sql, strings = protect_strings(sql)

    # 1. 重命名冲突 CTE
    for cte, new in CTE_RENAME.items():
        sql = re.sub(rf'\b{cte}\b', new, sql)

    # 2. 别名映射
    alias_map = build_alias_map(sql, table_set)

    # 2b. USING -> ON(原名)
    sql = resolve_using(sql, omap)

    # 3c. 无别名歧义列(按最近 FROM/JOIN 表, 原名)
    sql = resolve_ambiguous_unqualified(sql, omap)

    # 4. 表名替换(长表名优先, 仅 FROM/JOIN 上下文) —— 先于列替换, 避免表名/列名同名冲突
    for table in sorted(omap, key=len, reverse=True):
        abbrev = omap[table]['abbrev']
        sql = re.sub(rf'\b(FROM|JOIN)\s+{re.escape(table)}\b',
                     rf'\1 {abbrev}', sql, flags=re.I)

    # 5a. 别名.列 替换(大小写不敏感, 含带引号的保留字列如 T3.'Group')
    for alias, table in alias_map.items():
        for col, obf in omap[table]['columns'].items():
            sql = re.sub(rf'\b{re.escape(alias)}\.{re.escape(col)}\b',
                         f'{alias}.{obf}', sql, flags=re.I)
            sql = re.sub(rf'\b{re.escape(alias)}\.[\'"]{re.escape(col)}[\'"]',
                         f'{alias}.{obf}', sql, flags=re.I)

    # 5b. 无别名列替换(全局唯一映射, 大小写不敏感, 排除关键字列)
    gcol = build_global_col_map(omap)
    for col, obf in gcol.items():
        if obf is None or col.lower() in KEYWORDS:
            continue
        sql = re.sub(rf'\b{re.escape(col)}\b', obf, sql, flags=re.I)

    # 6. 恢复字符串字面量
    sql = restore_strings(sql, strings)

    # 7. 方言翻译
    sql = translate_dialect(sql)

    # 8. 派生表别名
    sql = add_derived_alias(sql)

    return sql


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--questions', default='question_set_final.json')
    ap.add_argument('--map', default='obfuscation_map.json')
    ap.add_argument('--out', default='question_set_final_obfuscated.json')
    args = ap.parse_args()

    qs = json.load(open(args.questions))
    omap = json.load(open(args.map))

    out = dict(qs)
    for q in out['questions']:
        q['SQL_obfuscated'] = next(
            (obf for key, obf in HAND_OBFUSCATED.items() if key in q['SQL']),
            transform_sql(q['SQL'], omap))

    json.dump(out, open(args.out, 'w'), ensure_ascii=False, indent=2)

    print(f"改写 {len(out['questions'])} 条 -> {args.out}")
    # 抽样展示
    for q in out['questions'][:3]:
        print(f"\n[{q['id']}] 原名:\n  {q['SQL'][:140]}")
        print(f"  混淆:\n  {q['SQL_obfuscated'][:140]}")


if __name__ == '__main__':
    main()
