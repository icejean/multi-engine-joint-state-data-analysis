#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 M+S 路线的「一次性注入」schema 资源文件：{库名}_schema.json。

把某个库的 sys_tables / sys_table_fields / sys_foreignkeys 三张元数据表打包成一个 JSON
（数据字典 + 外键关系），并附带 information_schema 的列类型。用途：M 轴（Agent）不用逐表
list_objects / 查 sys_* 表探索，一次性加载该文件即可拿到完整 schema——M+S 路线第 4 点。

用法:
  python gen_schema_resource.py works_cycles_er
      → data/works_cycles/works_cycles_er_schema.json

前置: 该库需已注册为数据源（.datasources.json）且 MySQL 可连。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import _connect  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "works_cycles"


def gen(db):
    conn = _connect(db)
    cur = conn.cursor()
    try:
        # 1) sys_tables → 表名/描述/类型
        cur.execute("SELECT table_name, table_desc, table_type FROM sys_tables ORDER BY table_name")
        table_rows = cur.fetchall()

        # 2) sys_table_fields → 字段名/描述
        cur.execute(
            "SELECT table_name, field_name, field_desc FROM sys_table_fields "
            "ORDER BY table_name, field_name"
        )
        field_rows = cur.fetchall()

        # 3) sys_foreignkeys → 外键关系
        cur.execute(
            "SELECT from_table, from_column, to_table, to_column, column_seq, column_count "
            "FROM sys_foreignkeys ORDER BY constraint_name, column_seq"
        )
        fk_rows = cur.fetchall()

        # 4) information_schema.columns → 列类型（数据表，不含 sys_*）
        cur.execute(
            "SELECT table_name, column_name, column_type "
            "FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name NOT LIKE %s "
            "ORDER BY table_name, ordinal_position",
            (db, "sys\\_%"),
        )
        type_map = {}
        for tbl, col, ctype in cur.fetchall():
            type_map[(tbl, col)] = ctype
    finally:
        conn.close()

    # 组装 tables（每表带 columns：name/type/desc）
    fields_by_table = {}
    for tbl, fld, desc in field_rows:
        fields_by_table.setdefault(tbl, []).append(
            {"name": fld, "type": type_map.get((tbl, fld), ""), "desc": desc}
        )

    tables = [
        {
            "name": t,
            "desc": d,
            "table_type": ty,
            "columns": fields_by_table.get(t, []),
        }
        for t, d, ty in table_rows
    ]

    foreign_keys = [
        {
            "from": f"{ft}.{fc}",
            "to": f"{tt}.{tc}",
            "seq": seq,
            "count": cnt,
        }
        for ft, fc, tt, tc, seq, cnt in fk_rows
    ]

    doc = {
        "database": db,
        "description": (
            "该库的完整数据字典（表/字段描述）+ 外键关系 + 列类型，一次性加载即免逐表探索。"
            "sys_* 三张元数据表的内容已打包进本文件（对应库已 drop 这三张表，改读本文件）。"
        ),
        "tables": tables,
        "foreign_keys": foreign_keys,
        "stats": {
            "tables": len(tables),
            "columns": len(field_rows),
            "foreign_keys": len(foreign_keys),
        },
    }

    out = OUT_DIR / f"{db}_schema.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 生成 {out}")
    print(f"   {len(tables)} 表 / {len(field_rows)} 字段 / {len(foreign_keys)} 外键")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("db", help="数据库名，如 works_cycles_er")
    args = ap.parse_args()
    gen(args.db)
