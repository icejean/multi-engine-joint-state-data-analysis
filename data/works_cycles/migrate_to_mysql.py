#!/usr/bin/env python3
"""SQLite works_cycles -> 3 个 MySQL 三梯度库(可复现)。

用法:
    python3 migrate_to_mysql.py [--env <path>] [--sqlite works_cycles.sqlite] \
        [--map obfuscation_map.json] [--desc descriptions.json]

凭据(--env): 缺省时自动解析 —— 优先 repo 根 .env(开源第三方复现), 回退
/opt/dataai/templates/.env(本机开发)。显式 --env <path> 可覆盖。

三个库(同名数据, 元数据逐级增加):
    works_cycles       裸数据(65 表, 混淆名, 无元数据)
    works_cycles_dict  + sys_tables + sys_table_fields(数据字典)
    works_cycles_er    + sys_foreignkeys(ER 关系)

数据清理说明:
    BIRD 的 works_cycles.sqlite 里 CountryRegion 首行是 CSV 表头误入
    (值='Cou','Name','ModifiedDate'), 已在源库清理:
        DELETE FROM CountryRegion WHERE ModifiedDate = 'ModifiedDate';
"""

import argparse, json, os, re, sqlite3, sys
import pymysql

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # .../dataai-test/data/works_cycles
REPO_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # .../dataai-test

TYPE_MAP_DB = {
    'works_cycles':      {'dict': False, 'er': False},
    'works_cycles_dict': {'dict': True,  'er': False},
    'works_cycles_er':   {'dict': True,  'er': True},
}


def load_env(path):
    env = {}
    for line in open(path):
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


def build_dict_tables(cur):
    """数据字典梯度: sys_tables + sys_table_fields"""
    cur.execute("""CREATE TABLE sys_tables (
        table_name VARCHAR(64) NOT NULL,
        table_desc VARCHAR(512) NOT NULL,
        table_type VARCHAR(16) NOT NULL COMMENT 'fact | dim | junction'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""")
    cur.execute("""CREATE TABLE sys_table_fields (
        table_name VARCHAR(64) NOT NULL,
        field_name VARCHAR(64) NOT NULL,
        field_desc VARCHAR(512) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""")


def build_er_table(cur):
    """ER 梯度: sys_foreignkeys"""
    cur.execute("""CREATE TABLE sys_foreignkeys (
        constraint_name VARCHAR(64) NOT NULL,
        from_table VARCHAR(64) NOT NULL,
        from_column VARCHAR(64) NOT NULL,
        to_table VARCHAR(64) NOT NULL,
        to_column VARCHAR(64) NOT NULL,
        column_seq INT NOT NULL COMMENT '复合外键中的列序号(1-based)',
        column_count INT NOT NULL COMMENT '外键总列数(1=单列,N=复合)',
        source VARCHAR(16) NOT NULL COMMENT 'manual | inferred',
        confidence DECIMAL(3,2) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--env', default=None, help='凭据文件路径;缺省自动:repo 根 .env → /opt/dataai/templates/.env')
    ap.add_argument('--sqlite', default='works_cycles.sqlite')
    ap.add_argument('--map', default='obfuscation_map.json')
    ap.add_argument('--desc', default='descriptions.json')
    args = ap.parse_args()

    if args.env:
        env = load_env(args.env)
    else:
        local = os.path.join(REPO_ROOT, ".env")
        env = load_env(local if os.path.exists(local) else "/opt/dataai/templates/.env")
    omap = json.load(open(args.map))
    desc = json.load(open(args.desc))

    # 1. 读 SQLite schema + 数据
    con = sqlite3.connect(args.sqlite)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    # schema: 原名表 -> {原名列: (类型, pk)}
    schema = {}
    for t in tables:
        cols = {}
        for (cid, name, typ, nn, dv, pk) in con.execute(f'PRAGMA table_info("{t}")'):
            cols[name] = (typ, pk)
        schema[t] = cols

    # 2. 连 MySQL
    my = pymysql.connect(host=env['MYSQLHOST'], port=int(env['MYSQLPORT']),
                         user=env['MYSQLUSER'], password=env['MYSQLPASSWORD'],
                         charset='utf8mb4', autocommit=False)
    cur = my.cursor()

    # 反向映射: 缩写 -> 原名
    abbrev2orig = {v['abbrev']: k for k, v in omap.items()}

    total_rows = 0
    for dbname, cfg in TYPE_MAP_DB.items():
        cur.execute(f"DROP DATABASE IF EXISTS `{dbname}`")
        cur.execute(f"CREATE DATABASE `{dbname}` DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_bin")
        cur.execute(f"USE `{dbname}`")
        print(f"\n===== {dbname} (dict={cfg['dict']}, er={cfg['er']}) =====")

        # 3. 建 65 张数据表 + 导数据
        for t in tables:
            m = omap[t]
            tab = m['abbrev']
            # 原列 -> 缩写列, 保持列顺序
            col_defs = []
            col_names_obf = []
            pk_obf = set(m['pk'])
            for orig, obf in m['columns'].items():
                typ, pk = schema[t][orig]
                # 仅 TEXT/BLOB 需要算最大长度来定类型
                tup = (typ or '').upper()
                max_len = 0
                if not any(x in tup for x in ('INT', 'REAL', 'DOUB', 'FLOAT', 'DEC', 'NUM', 'DATE', 'TIME')):
                    max_len = con.execute(f'SELECT MAX(LENGTH("{orig}")) FROM "{t}"').fetchone()[0] or 0
                myt = to_mysql_type(typ, obf in pk_obf, max_len)
                col_defs.append(f"`{obf}` {myt}")
                col_names_obf.append((orig, obf))
            col_defs.append(f"PRIMARY KEY ({', '.join('`'+p+'`' for p in m['pk'])})")
            cur.execute(f"CREATE TABLE `{tab}` ({', '.join(col_defs)}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin")

            # 导数据(批处理)
            orig_cols = [o for o, _ in col_names_obf]
            obf_cols = [o for _, o in col_names_obf]
            sel = 'SELECT ' + ', '.join(f'"{o}"' for o in orig_cols) + f' FROM "{t}"'
            rows = con.execute(sel).fetchall()
            # 判断哪些是 datetime 列
            is_dt = ['DATE' in (schema[t][o][0] or '').upper() or 'TIME' in (schema[t][o][0] or '').upper() for o in orig_cols]
            ins = f"INSERT INTO `{tab}` ({', '.join('`'+c+'`' for c in obf_cols)}) VALUES ({', '.join(['%s']*len(obf_cols))})"
            batch = []
            for row in rows:
                batch.append([clean_value(v, is_dt[i]) for i, v in enumerate(row)])
                if len(batch) >= 2000:
                    try:
                        cur.executemany(ins, batch)
                    except Exception as e:
                        print(f"  [失败表] {t} 第一行: {batch[0]}")
                        raise
                    batch = []
            if batch:
                try:
                    cur.executemany(ins, batch)
                except Exception as e:
                    print(f"  [失败表] {t} 第一行: {batch[0]}")
                    raise
            total_rows += len(rows)

        # 4. 数据字典(元数据表)
        if cfg['dict']:
            build_dict_tables(cur)
            # sys_tables
            for t in tables:
                m = omap[t]
                d = desc[t]
                cur.execute("INSERT INTO sys_tables (table_name, table_desc, table_type) VALUES (%s,%s,%s)",
                            (m['abbrev'], d['desc'], d['type']))
            # sys_table_fields
            for t in tables:
                m = omap[t]
                d = desc[t]
                for orig, obf in m['columns'].items():
                    fd = d['fields'].get(orig, '')
                    cur.execute("INSERT INTO sys_table_fields (table_name, field_name, field_desc) VALUES (%s,%s,%s)",
                                (m['abbrev'], obf, fd))

        # 5. ER(外键元数据表)
        if cfg['er']:
            build_er_table(cur)
            # 复合外键分组: 同 constraint_name 的列归一组
            groups = {}
            for t in tables:
                for fk in omap[t]['fks']:
                    groups.setdefault(fk['constraint'], []).append(
                        (t, fk['from_col'], fk['to_table'], fk['to_col']))
            n_fk = 0
            for cname, cols in groups.items():
                cnt = len(cols)
                for seq, (t, fc, tt, tc) in enumerate(cols, 1):
                    cur.execute("""INSERT INTO sys_foreignkeys
                        (constraint_name, from_table, from_column, to_table, to_column,
                         column_seq, column_count, source, confidence)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,'manual',1.00)""",
                        (cname, omap[t]['abbrev'], fc, tt, tc, seq, cnt))
                    n_fk += 1
            print(f"  sys_foreignkeys: {n_fk} 条")

        my.commit()
        print(f"  数据表 {len(tables)} 张, 行数累计 {total_rows}")

    my.close()
    con.close()
    print(f"\n完成: 3 个库已建, 总导入行数 {total_rows}")


if __name__ == '__main__':
    main()
