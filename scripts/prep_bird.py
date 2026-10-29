#!/usr/bin/env python3
"""BIRD dev 库 prep 管线 (Phase A, 不需要 MySQL):
enrich(raw dev.json) + 混淆映射(全混淆: 表名缩写 + 非FK列去元音截4 + FK列→ref1/ref2)
+ schema.json(混淆名 + 英文描述 + 外键)。

用法:
    python3 prep_bird.py formula_1
    python3 prep_bird.py financial

输入 (data/{db}/):
    dev.json                原始 BIRD 题库 (question_id/db_id/question/evidence/SQL/difficulty)
    {db}.sqlite             数据库 (PRAGMA foreign_key_list 提供 FK, 已核对与 BIRD dev_tables.json 一致)
    database_description/*.csv  英文列描述

输出 (data/{db}/):
    question_set.json           enrich 后的题集 (id/question_id/db_id/question/evidence/SQL/difficulty/join_count/features)
    obfuscation_map.json        表/列/FK 混淆映射
    {db}_schema.json            混淆名 + 英文描述 + 外键 (供 M+S 一次性注入)

随后用 transform_gold_sql.py 把 question_set.json 的 SQL 改写为混淆名 + MySQL 方言。
"""
import argparse, csv, io, json, os, re, sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # dataai-test
DATA = os.path.join(ROOT, 'data')

# ── 表名混淆(去元音风格, 手写) ──────────────────────────────────────────────
TABLE_ABBREV = {
    'formula_1': {
        'circuits': 'crct', 'constructors': 'cnstr', 'drivers': 'drvr',
        'seasons': 'ssn', 'races': 'rcs', 'constructorResults': 'cnstr_rslt',
        'constructorStandings': 'cnstr_std', 'driverStandings': 'drvr_std',
        'lapTimes': 'lp_tm', 'pitStops': 'pt_stp', 'qualifying': 'qlfy',
        'status': 'stat', 'results': 'rslt',
    },
    'financial': {
        'account': 'acct', 'card': 'crd', 'client': 'clnt', 'disp': 'dsp',
        'district': 'dstr', 'loan': 'ln', 'order': 'ord', 'trans': 'trns',
    },
}

# ── 表级英文描述 (type, desc) ──────────────────────────────────────────────
TABLE_DESC = {
    'formula_1': {
        'circuits': ('dim', 'F1 race circuits (track locations)'),
        'constructors': ('dim', 'F1 constructors (teams)'),
        'drivers': ('dim', 'F1 drivers'),
        'seasons': ('dim', 'F1 seasons (years)'),
        'races': ('dim', 'F1 races (one per circuit per season)'),
        'constructorResults': ('fact', 'constructor points per race'),
        'constructorStandings': ('fact', 'constructor standings after each race'),
        'driverStandings': ('fact', 'driver standings after each race'),
        'lapTimes': ('fact', 'lap times per driver per lap'),
        'pitStops': ('fact', 'pit stops per driver per race'),
        'qualifying': ('fact', 'qualifying results per driver per race'),
        'status': ('dim', 'race finish status codes'),
        'results': ('fact', 'race results per driver per race'),
    },
    'financial': {
        'account': ('dim', 'bank accounts'),
        'card': ('dim', 'payment cards issued to accounts'),
        'client': ('dim', 'bank clients (persons)'),
        'disp': ('junction', 'disposition: account-client ownership link'),
        'district': ('dim', 'geographic districts (Czech regions)'),
        'loan': ('fact', 'loans granted to accounts'),
        'order': ('fact', 'payment orders'),
        'trans': ('fact', 'transactions on accounts'),
    },
}

# ── gold 修复(原 SQL 级, 按本地 id 匹配, enrich 时应用; 理由见 docs/gold-fixes-bird-dev.md) ──
GOLD_FIXES = {
    'formula_1': {
        159: {
            'reason': '原 gold 用 SUM(wins) 全表求和 + ORDER BY dob ASC LIMIT 1 取任意行, 语义错(7890=全表总和、Lewis Hamilton 非最老)。改为最老车手(非NULL dob)的 MAX(wins)=0, Philippe Étancelin。',
            'sql': "SELECT MAX(T1.wins), T2.forename, T2.surname FROM driverStandings AS T1 INNER JOIN drivers AS T2 ON T1.driverId = T2.driverId WHERE T2.dob = (SELECT MIN(dob) FROM drivers) GROUP BY T2.forename, T2.surname",
        },
        165: {
            'reason': '「lap record」=最快圈速,但 gold 没取最快(无 ORDER BY 返回全部);且 time 字符串排序跨分钟会错(19:16 < 1:07)。改为 ORDER BY milliseconds ASC LIMIT 1 取最快(Hamilton=1:07.411)。',
            'sql': "SELECT T1.time FROM lapTimes AS T1 INNER JOIN drivers AS T2 ON T1.driverId = T2.driverId WHERE T2.forename = 'Lewis' AND T2.surname = 'Hamilton' ORDER BY T1.milliseconds ASC LIMIT 1",
        },
        125: {
            'reason': '题面「earliest lap time」=lapTimes,但 gold 错用 pitStops 表;且问「list drivers」应返回名字(gold 返回 driverId 不合理,text-to-SQL 常识)。改为 lapTimes + GROUP BY driverId + MIN(milliseconds) + 返回 forename/surname。',
            'sql': "SELECT T2.forename, T2.surname FROM lapTimes AS T1 INNER JOIN drivers AS T2 ON T1.driverId = T2.driverId WHERE T2.nationality = 'German' AND STRFTIME('%Y', T2.dob) BETWEEN '1980' AND '1990' GROUP BY T2.driverId ORDER BY MIN(T1.milliseconds) ASC LIMIT 3",
        },
        128: {
            'reason': '题面「latest lap time」=lapTimes,但 gold 错用 pitStops 表;且问「list drivers」应返回名字。改为 lapTimes + GROUP BY driverId + MAX(milliseconds) + 返回 forename/surname。',
            'sql': "SELECT T2.forename, T2.surname FROM lapTimes AS T1 INNER JOIN drivers AS T2 ON T1.driverId = T2.driverId WHERE T2.nationality = 'Spanish' AND STRFTIME('%Y', T2.dob) < '1982' GROUP BY T2.driverId ORDER BY MAX(T1.milliseconds) DESC LIMIT 10",
        },
        140: {
            'reason': '题面「who has the slowest time」应返回名字,但 gold 返回 driverId(不合理)。改为 JOIN drivers 返回 forename/surname。',
            'sql': "SELECT T3.forename, T3.surname FROM lapTimes AS T1 INNER JOIN races AS T2 ON T1.raceId = T2.raceId INNER JOIN drivers AS T3 ON T1.driverId = T3.driverId WHERE T2.name = 'French Grand Prix' AND T1.lap = 3 ORDER BY T1.time DESC LIMIT 1",
        },
    },
    'financial': {
        21: {
            'reason': '原 gold 用 client.district_id(home district, 26)答「opened accounts in Jesenik branch」,但题面指账户分支口径(account.district_id),应为 25。改为 clnt→disp→acct→dstr 账户分支链。',
            'sql': "SELECT COUNT(T1.client_id) FROM client AS T1 INNER JOIN disp AS T3 ON T1.client_id = T3.client_id INNER JOIN account AS T2 ON T3.account_id = T2.account_id INNER JOIN district AS T4 ON T2.district_id = T4.district_id WHERE T1.gender = 'F' AND T4.A2 = 'Jesenik'",
        },
        92: {
            'reason': '题面 "along with their IDs" 有歧义(gold 解读为 client_id + account_id 两列),原 evidence 为空。补 evidence 消歧,不改 gold SQL。',
            'evidence': 'their IDs refers to both the client ID and the account ID — return client_id and account_id as two separate columns.',
        },
        13: {
            'reason': '原 gold 用 ORDER BY date ASC LIMIT 1 只返回 1 个账户;且 account_id 无 DISTINCT 会把同账户多笔交易重复计(359 行),「accounts」= 唯一实体应为 315。改为 DISTINCT account_id + date = MIN(date)。',
            'sql': "SELECT DISTINCT account_id FROM trans WHERE date = (SELECT MIN(date) FROM trans WHERE STRFTIME('%Y', date) = '1995')",
        },
        83: {
            'reason': '原 evidence 写「north − east」但 gold SQL 做「east − north」(与题面 "East and North" 顺序一致),evidence 自相矛盾误导 agent。改正 evidence 方向对齐 gold。',
            'evidence': 'Difference in no. of committed crimes between 2 regions = Total no. of committed crimes in 1996 in east Bohemia - Total no. of committed crimes in 1996 in north Bohemia. A3 refers to region. Data about no. of committed crimes 1996 appears in A16',
        },
        80: {
            'reason': '题面「opened their accounts in the district」=账户分支,但 gold 用 client 的 home district(49.61%)。改为 clnt→disp→acct→dstr 分支链(50.39%,同 Q21),无 fan-out。',
            'sql': "SELECT CAST(SUM(T2.gender = 'F') AS REAL) * 100 / COUNT(T2.client_id) FROM client AS T2 INNER JOIN disp AS T3 ON T2.client_id = T3.client_id INNER JOIN account AS T4 ON T3.account_id = T4.account_id INNER JOIN district AS T1 ON T4.district_id = T1.district_id WHERE T1.A11 > 10000",
        },
        97: {
            'reason': '题面「accounts at the Prague branch」=账户分支,但 gold 用 client 的 home district(48.87%)。改为 clnt→disp→acct→dstr 分支链(49.78%,同 Q21),无 fan-out。',
            'sql': "SELECT CAST(SUM(T2.gender = 'F') AS REAL) / COUNT(T2.client_id) * 100 FROM client AS T2 INNER JOIN disp AS T3 ON T2.client_id = T3.client_id INNER JOIN account AS T4 ON T3.account_id = T4.account_id INNER JOIN district AS T1 ON T4.district_id = T1.district_id WHERE T1.A3 = 'Prague'",
        },
        53: {
            'reason': '题面「which districts have transactions greater than $10,000」自然读法是单笔 amount>10000(agent 对),gold 却用 SUM(总额)>10000;且应返回 district 名(A2)非 id。改为 DISTINCT A2 + WHERE amount>10000。',
            'sql': "SELECT DISTINCT T2.A2 FROM account AS T1 INNER JOIN district AS T2 ON T1.district_id = T2.district_id INNER JOIN trans AS T3 ON T1.account_id = T3.account_id WHERE STRFTIME('%Y', T3.date) = '1997' AND T3.amount > 10000",
        },
    },
}

VOWELS = set('aeiou')


def split_camel(s):
    s = re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', s)
    s = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', s)
    return s.split()


def abbrev_word(w):
    wl = w.lower()
    core = wl[0] + ''.join(c for c in wl[1:] if c not in VOWELS)
    core = core[:4]
    return core if len(core) >= 2 else wl[:4]


def split_ident(name):
    """先按下划线切, 再按大小写切(snake_case 的 'account_id' -> ['account','id'])。"""
    parts = []
    for seg in re.split(r'[_\s]+', name):
        if seg:
            parts.extend(split_camel(seg))
    return [p for p in parts if p]


def abbrev_col(name):
    return '_'.join(abbrev_word(w) for w in split_ident(name))


# ── enrich: dev.json -> question_set.json ──────────────────────────────────
def features(sql):
    s = sql.upper()
    f, nj = [], len(re.findall(r'\bJOIN\b', s))
    if nj:
        f.append(f"JOIN×{nj}")
    if re.search(r'\bGROUP\s+BY\b', s):
        f.append("GROUP_BY")
    if re.search(r'\bHAVING\b', s):
        f.append("HAVING")
    if re.search(r'\bCASE\b', s):
        f.append("CASE")
    if re.search(r'\(\s*SELECT\b', s):
        f.append("SUBQUERY")
    if re.search(r'\bEXISTS\b', s):
        f.append("EXISTS")
    return f, nj


def enrich(db):
    ddir = os.path.join(DATA, db)
    raw = json.load(open(os.path.join(ddir, 'dev.json'), encoding='utf-8'))
    qs = []
    for i, q in enumerate(raw, 1):
        f, nj = features(q['SQL'])
        qs.append({
            'id': i,
            'question_id': q['question_id'],
            'db_id': q['db_id'],
            'question': q['question'],
            'evidence': q['evidence'],
            'SQL': q['SQL'],
            'difficulty': q['difficulty'],
            'join_count': nj,
            'features': f,
        })
    # 应用 gold 修复(原 SQL 级; 可只补 evidence 不改 SQL)
    for q in qs:
        fix = GOLD_FIXES.get(db, {}).get(q['id'])
        if fix:
            if 'sql' in fix:
                q['SQL'] = fix['sql']
            if 'evidence' in fix:
                q['evidence'] = fix['evidence']
            q['gold_fixed'] = fix['reason']
    doc = {
        'name': f'{db}_question_set',
        'description': f'BIRD dev {db} 全量题集(enrich 后, 待 transform 混淆)',
        'count': len(qs),
        'questions': qs,
    }
    out = os.path.join(ddir, 'question_set.json')
    json.dump(doc, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'enrich: {len(qs)} 题 -> {out}')
    return doc


# ── 混淆映射 ────────────────────────────────────────────────────────────────
def build_map(db):
    ddir = os.path.join(DATA, db)
    abbrev = TABLE_ABBREV[db]
    con = sqlite3.connect(os.path.join(ddir, f'{db}.sqlite'))
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]

    assert set(abbrev.values()) == set(abbrev.values()) and len(set(abbrev.values())) == len(abbrev), \
        "表缩写有重复!"
    missing = [t for t in tables if t not in abbrev]
    assert not missing, f"缺表缩写: {missing}"

    mapping = {}
    for t in tables:
        cols = {r[1]: r for r in con.execute(f'PRAGMA table_info("{t}")')}  # name -> row
        fk_from = []
        for fk in con.execute(f'PRAGMA foreign_key_list("{t}")'):
            if fk[3] not in fk_from:
                fk_from.append(fk[3])
        col_map, used = {}, {}
        for cname in cols:
            if cname in fk_from:
                obf = f"ref{fk_from.index(cname) + 1}"
            else:
                obf = abbrev_col(cname)
                if obf in used:
                    used[obf] += 1
                    obf = f"{obf}{used[obf]}"
                else:
                    used[obf] = 1
            col_map[cname] = obf

        pk = sorted((cols[c][5], col_map[c]) for c in cols if cols[c][5] > 0)
        pk_obf = [n for _, n in pk]

        fks = []
        for fk in con.execute(f'PRAGMA foreign_key_list("{t}")'):
            fk_id, seq, ref_t, from_c, to_c = fk[0], fk[1], fk[2], fk[3], fk[4]
            if not to_c:
                rp = con.execute(f'PRAGMA table_info("{ref_t}")').fetchall()
                to_c = sorted([(r[5], r[1]) for r in rp if r[5] > 0])[0][1]
            fks.append({
                'constraint': f"fk_{abbrev[t]}_{abbrev[ref_t]}",
                'from_col': col_map[from_c],
                'to_table': abbrev[ref_t],
                'to_col': None,
                '_ref_t': ref_t, '_ref_c': to_c,
            })

        mapping[t] = {'abbrev': abbrev[t], 'columns': col_map, 'pk': pk_obf, 'fks': fks}

    for t, m in mapping.items():
        for fk in m['fks']:
            to_t, to_c = fk['_ref_t'], fk['_ref_c']
            fk['to_col'] = mapping[to_t]['columns'][to_c]
            del fk['_ref_t'], fk['_ref_c']

    con.close()

    for t, m in mapping.items():
        vals = list(m['columns'].values())
        assert len(set(vals)) == len(vals), f"{t} 列缩写重复: {vals}"

    out = os.path.join(ddir, 'obfuscation_map.json')
    json.dump(mapping, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    n_fk = sum(len(m['fks']) for m in mapping.values())
    print(f'混淆映射: {len(mapping)} 表 / {n_fk} FK -> {out}')
    return mapping


# ── schema.json(混淆名 + 英文描述 + 外键) ──────────────────────────────────
def _read_text(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def build_schema(db, mapping):
    ddir = os.path.join(DATA, db)
    desc_dir = os.path.join(ddir, 'database_description')
    table_meta = TABLE_DESC[db]

    # 读 sqlite 列类型(与 migrate 同源)
    con = sqlite3.connect(os.path.join(ddir, f'{db}.sqlite'))
    orig_type = {}
    for t in mapping:
        for (cid, name, typ, nn, dv, pk) in con.execute(f'PRAGMA table_info("{t}")'):
            orig_type[(t, name)] = typ
    con.close()

    # 读英文列描述: {table: {orig_col: desc}}
    descs = {}
    for fn in sorted(os.listdir(desc_dir)):
        if not fn.lower().endswith('.csv'):
            continue
        table = os.path.splitext(fn)[0]
        cols = {}
        for row in csv.DictReader(io.StringIO(_read_text(os.path.join(desc_dir, fn)))):
            orig = row.get('original_column_name', '').strip()
            if not orig:
                continue
            cols[orig] = (row.get('column_description', '').strip()
                          or row.get('column_name', '').strip())
        descs[table] = cols

    tables = []
    for t in sorted(mapping, key=lambda x: mapping[x]['abbrev']):
        m = mapping[t]
        typ, tdesc = table_meta[t]
        columns = []
        for orig, obf in m['columns'].items():
            columns.append({
                'name': obf,
                'type': (orig_type.get((t, orig)) or '').lower(),
                'desc': descs.get(t, {}).get(orig, ''),
            })
        tables.append({'name': m['abbrev'], 'desc': tdesc, 'table_type': typ, 'columns': columns})

    # 外键(按 constraint 分组, 编号 seq/count)
    groups = {}
    for t in mapping:
        for fk in mapping[t]['fks']:
            groups.setdefault(fk['constraint'], []).append(
                (mapping[t]['abbrev'], fk['from_col'], fk['to_table'], fk['to_col']))
    foreign_keys = []
    for cname, cols in groups.items():
        cnt = len(cols)
        for seq, (ft, fc, tt, tc) in enumerate(cols, 1):
            foreign_keys.append({'from': f'{ft}.{fc}', 'to': f'{tt}.{tc}', 'seq': seq, 'count': cnt})

    doc = {
        'database': db,
        'description': f'{db} 完整数据字典(混淆名) + 外键 + 列类型, 一次性注入即免逐表探索。',
        'tables': tables,
        'foreign_keys': foreign_keys,
        'stats': {
            'tables': len(tables),
            'columns': sum(len(t['columns']) for t in tables),
            'foreign_keys': len(foreign_keys),
        },
    }
    out = os.path.join(ddir, f'{db}_schema.json')
    json.dump(doc, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'schema.json: {len(tables)} 表 / {len(foreign_keys)} FK -> {out}')
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db', choices=list(TABLE_ABBREV.keys()))
    args = ap.parse_args()

    enrich(args.db)
    mapping = build_map(args.db)
    build_schema(args.db, mapping)
    print(f"\n✅ {args.db} Phase A 完成。下一步:")
    print(f"   python3 scripts/transform_gold_sql.py "
          f"--questions data/{args.db}/question_set.json "
          f"--map data/{args.db}/obfuscation_map.json "
          f"--out data/{args.db}/question_set_obfuscated.json")


if __name__ == '__main__':
    main()
