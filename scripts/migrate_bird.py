#!/usr/bin/env python3
"""SQLite -> MySQL(混淆名, 单库, M+S 用)。

用法:
    python3 migrate_bird.py formula_1
    python3 migrate_bird.py financial

前置: 已跑 prep_bird.py(生成 obfuscation_map.json)。
凭据: repo 根 .env → /opt/dataai/templates/.env。

输出: MySQL 库 {db}(表/列用混淆名, 无 sys_* 元数据表——M+S 的 schema 走注入的 schema.json)。
"""
import argparse, json, os, re, sqlite3
import pymysql

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # dataai-test
DATA = os.path.join(ROOT, 'data')


def load_env():
    local = os.path.join(ROOT, '.env')
    env_path = local if os.path.exists(local) else '/opt/dataai/templates/.env'
    env = {}
    for line in open(env_path):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def to_mysql_type(sqlite_type, is_pk, max_len=0):
    t = (sqlite_type or '').upper()
    if 'INT' in t:
        return 'BIGINT'
    if any(x in t for x in ('REAL', 'FLOAT', 'DOUB', 'DEC', 'NUM')):
        return 'DOUBLE'
    if any(x in t for x in ('DATE', 'TIME')):
        return 'DATETIME'
    if 'BLOB' in t:
        return 'MEDIUMBLOB'
    if is_pk or max_len <= 255:
        return f'VARCHAR({max(1, max_len) + 10})'
    return 'MEDIUMTEXT'


def clean_value(v, is_datetime):
    if v is None:
        return None
    if is_datetime and isinstance(v, str):
        return re.sub(r'\.\d+$', '', v)  # 去掉 .0 / .263000000 小数秒
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('db')
    args = ap.parse_args()
    db = args.db

    env = load_env()
    ddir = os.path.join(DATA, db)
    omap = json.load(open(os.path.join(ddir, 'obfuscation_map.json'), encoding='utf-8'))

    # 1. 读 SQLite schema + 数据
    con = sqlite3.connect(os.path.join(ddir, f'{db}.sqlite'))
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    schema = {}
    for t in tables:
        cols = {}
        for (cid, name, typ, nn, dv, pk) in con.execute(f'PRAGMA table_info("{t}")'):
            cols[name] = (typ, pk)
        schema[t] = cols

    # 2. 连 MySQL
    my = pymysql.connect(host=env.get('MYSQLHOST', '127.0.0.1'),
                         port=int(env.get('MYSQLPORT', 3306)),
                         user=env['MYSQLUSER'], password=env['MYSQLPASSWORD'],
                         charset='utf8mb4', autocommit=False)
    cur = my.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{db}`")
    cur.execute(f"CREATE DATABASE `{db}` DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_bin")
    cur.execute(f"USE `{db}`")
    print(f"===== {db} =====")

    total_rows = 0
    for t in tables:
        m = omap[t]
        tab = m['abbrev']
        pk_obf = set(m['pk'])
        col_defs, col_names_obf = [], []
        for orig, obf in m['columns'].items():
            typ, pk = schema[t][orig]
            tup = (typ or '').upper()
            max_len = 0
            if not any(x in tup for x in ('INT', 'REAL', 'DOUB', 'FLOAT', 'DEC', 'NUM', 'DATE', 'TIME')):
                max_len = con.execute(f'SELECT MAX(LENGTH("{orig}")) FROM "{t}"').fetchone()[0] or 0
            myt = to_mysql_type(typ, obf in pk_obf, max_len)
            col_defs.append(f"`{obf}` {myt}")
            col_names_obf.append((orig, obf))
        if pk_obf:
            col_defs.append(f"PRIMARY KEY ({', '.join('`'+p+'`' for p in m['pk'])})")
        cur.execute(f"CREATE TABLE `{tab}` ({', '.join(col_defs)}) "
                    f"ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin")

        orig_cols = [o for o, _ in col_names_obf]
        obf_cols = [o for _, o in col_names_obf]
        sel = 'SELECT ' + ', '.join(f'"{o}"' for o in orig_cols) + f' FROM "{t}"'
        rows = con.execute(sel).fetchall()
        is_dt = ['DATE' in (schema[t][o][0] or '').upper() or 'TIME' in (schema[t][o][0] or '').upper()
                 for o in orig_cols]
        ins = f"INSERT INTO `{tab}` ({', '.join('`'+c+'`' for c in obf_cols)}) VALUES ({', '.join(['%s']*len(obf_cols))})"
        batch = []
        for row in rows:
            batch.append([clean_value(v, is_dt[i]) for i, v in enumerate(row)])
            if len(batch) >= 2000:
                cur.executemany(ins, batch)
                batch = []
        if batch:
            cur.executemany(ins, batch)
        total_rows += len(rows)
        print(f"  {t} -> {tab}: {len(rows)} 行")

    my.commit()
    my.close()
    con.close()
    print(f"\n完成: {db} 库已建, {len(tables)} 表 / {total_rows} 行")


if __name__ == '__main__':
    main()
