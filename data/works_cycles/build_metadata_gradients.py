#!/usr/bin/env python3
"""构建 BIRD 数据库的三梯度元数据 (裸数据 / +数据字典 / +ER图)。

用法:
    python3 build_metadata_gradients.py --db-dir <目录> [--out-dir <目录>]

输入 (BIRD 标准结构):
    <db-dir>/<name>.sqlite
    <db-dir>/database_description/*.csv

输出 (每库 3 个自包含 JSON):
    <out-dir>/<name>_L1_bare.json   裸数据: 表 + 列 + 类型 + 主键
    <out-dir>/<name>_L2_dict.json   +数据字典: 再加列描述(display_name/description/value_description)
    <out-dir>/<name>_L3_er.json     +ER图: 再加外键(来自 SQLite 声明)

说明:
    - 外键以 SQLite 里 PRAGMA foreign_key_list 声明的为准 (works_cycles 共 87 条)。
    - 声明里 to 列为空的 FK，目标列解析为目标表主键。
    - FK_CORRECTIONS 记录已知的 BIRD 导出 bug (如 ShipMethodID 错指 Address)。
"""

import argparse, csv, io, json, os, sqlite3, sys

GRADIENTS = {
    "L1_bare": "裸数据",
    "L2_dict": "裸数据 + 数据字典",
    "L3_er":   "裸数据 + 数据字典 + ER图(外键)",
}

# 已知的 FK 纠错: 键 (表, 列) -> 正确的引用表
FK_CORRECTIONS = {
    ("SalesOrderHeader", "ShipMethodID"): "ShipMethod",
}


def load_schema(db_path):
    """返回 (schema, pk_map)。schema=[{name, columns:[{name,type,nullable,primary_key}]}]"""
    con = sqlite3.connect(db_path)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    schema, pk_map = [], {}
    for t in tables:
        cols, pks = [], []
        for (cid, name, typ, nn, dv, pk) in con.execute(f'PRAGMA table_info("{t}")'):
            cols.append({"name": name, "type": typ, "nullable": not nn, "primary_key": bool(pk)})
            if pk:
                pks.append((pk, name))
        pks.sort()
        pk_map[t] = [n for _, n in pks]
        schema.append({"name": t, "columns": cols})
    con.close()
    return schema, pk_map


def _read_text(path):
    """按字节读文件，依次尝试常见编码，兜底 replace。"""
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def load_descriptions(desc_dir):
    """database_description/*.csv -> {table: {原始列名: {display_name, description, value_description}}}"""
    desc = {}
    for fn in sorted(os.listdir(desc_dir)):
        if not fn.lower().endswith('.csv'):
            continue
        table = os.path.splitext(fn)[0]
        cols = {}
        text = _read_text(os.path.join(desc_dir, fn))
        for row in csv.DictReader(io.StringIO(text)):
            orig = row.get('original_column_name', '').strip()
            if not orig:
                continue
            cols[orig] = {
                "display_name": row.get('column_name', '').strip(),
                "description": row.get('column_description', '').strip(),
                "value_description": row.get('value_description', '').strip(),
            }
        desc[table] = cols
    return desc


def load_foreign_keys(db_path, pk_map):
    """返回 (fks, warnings)。fks=[{table,column,references_table,references_column}]"""
    con = sqlite3.connect(db_path)
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    fks, warnings = [], []
    for t in tables:
        for fk in con.execute(f'PRAGMA foreign_key_list("{t}")'):
            fk_id, seq, ref_t, from_c, to_c, *_ = fk
            corr = FK_CORRECTIONS.get((t, from_c))
            if corr:
                warnings.append(f"{t}.{from_c} 声明指向 {ref_t}(疑似错误), 已纠正 -> {corr}")
                ref_t, to_c = corr, ''
            if not to_c:
                pks = pk_map.get(ref_t, [])
                if len(pks) == 1:
                    to_c = pks[0]
                elif len(pks) > 1:
                    warnings.append(f"{t}.{from_c} -> {ref_t} 目标复合主键 {pks}, 未解析, 跳过")
                    continue
                else:
                    warnings.append(f"{t}.{from_c} -> {ref_t} 目标表无主键, 跳过")
                    continue
            fks.append({"table": t, "column": from_c,
                        "references_table": ref_t, "references_column": to_c})
    con.close()
    return fks, warnings


def build_gradient(name, schema, desc, fks, warnings, level):
    tables_out, col_total = [], 0
    for t in schema:
        cols_out = []
        for c in t["columns"]:
            o = {"name": c["name"], "type": c["type"],
                 "nullable": c["nullable"], "primary_key": c["primary_key"]}
            if level >= 2:
                d = desc.get(t["name"], {}).get(c["name"], {})
                o["display_name"] = d.get("display_name", "")
                o["description"] = d.get("description", "")
                o["value_description"] = d.get("value_description", "")
            cols_out.append(o)
            col_total += 1
        tables_out.append({"name": t["name"], "columns": cols_out})

    suffix = ["bare", "dict", "er"][level - 1]
    doc = {
        "database": name,
        "gradient": f"L{level}_{suffix}",
        "gradient_label": list(GRADIENTS.values())[level - 1],
        "stats": {
            "table_count": len(schema),
            "column_count": col_total,
            "foreign_key_count": len(fks) if level >= 3 else 0,
        },
        "tables": tables_out,
    }
    if level >= 3:
        doc["foreign_keys"] = fks
        if warnings:
            doc["fk_warnings"] = warnings
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--db-dir', required=True)
    ap.add_argument('--out-dir', default=None)
    args = ap.parse_args()

    db_dir = os.path.abspath(args.db_dir)
    out_dir = os.path.abspath(args.out_dir) if args.out_dir else db_dir
    os.makedirs(out_dir, exist_ok=True)

    sqlite_files = sorted(f for f in os.listdir(db_dir) if f.lower().endswith('.sqlite'))
    if not sqlite_files:
        sys.exit(f"[错误] {db_dir} 下没有 .sqlite 文件")
    db_file = os.path.join(db_dir, sqlite_files[0])
    name = os.path.splitext(os.path.basename(db_file))[0]
    desc_dir = os.path.join(db_dir, 'database_description')

    print(f"数据库: {name} ({db_file})")
    schema, pk_map = load_schema(db_file)
    print(f"  表 {len(schema)} 张")
    desc = load_descriptions(desc_dir) if os.path.isdir(desc_dir) else {}
    print(f"  数据字典覆盖 {len(desc)} 张表")
    fks, warnings = load_foreign_keys(db_file, pk_map)
    print(f"  外键 {len(fks)} 条, 警告 {len(warnings)} 条")

    for level in (1, 2, 3):
        doc = build_gradient(name, schema, desc, fks, warnings, level)
        suffix = ["bare", "dict", "er"][level - 1]
        out = os.path.join(out_dir, f"{name}_L{level}_{suffix}.json")
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print(f"  -> {os.path.relpath(out, start=os.getcwd())}")

    for w in warnings:
        print(f"  [警告] {w}")


if __name__ == '__main__':
    main()
