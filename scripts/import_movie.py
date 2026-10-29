#!/usr/bin/env python3
"""
流式导入器：把 megagonlabs/cypherbench 的 *_simplekg.json 转成 neo4j-admin import 的 CSV。

用法:
    python3 import_movie.py [graph_name] [out_dir]

默认 graph_name=movie，out_dir=import。
生成:
    import/nodes_<Label>.csv   每个节点标签一个文件，首列 :ID 用原始 eid
    import/rels_<Type>.csv     每个关系类型一个文件
    import/run_import.sh       可直接执行的 neo4j-admin database import full 命令

说明:
  - 用 ijson 流式解析，不整读入内存（507MB 的 JSON 也没压力）。
  - 节点 ID 直接用 Wikidata 的 eid（如 "Movie#Q1000094"），全局唯一，
    关系 CSV 里的 subj_id/obj_id 可直接当 :START_ID/:END_ID，无需再做映射。
  - 属性类型按 schema 文件映射：str->string, int->long, float->float,
    date->date, list[str]->string[]（数组默认用 ';' 分隔）。
"""
import ijson
import json
import os
import sys
import collections

GRAPH = sys.argv[1] if len(sys.argv) > 1 else 'movie'
OUT = sys.argv[2] if len(sys.argv) > 2 else 'import'
DATA = f'{GRAPH}_simplekg.json'
SCHEMA = f'{GRAPH}_schema.json'

TYPE_MAP = {
    'str': 'string',
    'int': 'long',
    'float': 'float',
    'date': 'date',
    'list[str]': 'string[]',
}


def csv_field(s):
    """按 CSV 规则转义单个字段（含逗号/引号/换行时加引号并转义引号）。"""
    if any(ch in s for ch in [',', '"', '\n', '\r']):
        return '"' + s.replace('"', '""') + '"'
    return s


def fmt_value(v, typ):
    if v is None:
        return ''
    if typ == 'string[]':
        return csv_field(';'.join(str(x) for x in v))
    if typ == 'long':
        return str(int(v))           # ijson 默认返回 Decimal，int() 取整
    if typ == 'float':
        return repr(float(v))
    if typ == 'date':
        return csv_field(str(v))     # 值已是 "YYYY-MM-DD"
    return csv_field(str(v))         # string


def main():
    if not os.path.exists(DATA):
        sys.exit(f'找不到数据文件 {DATA}')
    if not os.path.exists(SCHEMA):
        sys.exit(f'找不到 schema 文件 {SCHEMA}')

    sch = json.load(open(SCHEMA))
    # 节点: label -> [(属性名, 映射后类型)]
    node_props = {
        e['label']: [(k, TYPE_MAP[t]) for k, t in e['properties'].items()]
        for e in sch['entities']
    }
    # 关系: type -> [(属性名, 映射后类型)]（同 type 可能有多个 subj/obj 定义，属性一致，去重）
    rel_props = {}
    for r in sch['relations']:
        rel_props.setdefault(r['label'],
                             [(k, TYPE_MAP[t]) for k, t in r['properties'].items()])

    os.makedirs(OUT, exist_ok=True)

    # 打开节点文件，写表头
    node_files = {}
    for lbl, props in node_props.items():
        header = [':ID', 'name:string'] + [f'{k}:{t}' for k, t in props]
        f = open(f'{OUT}/nodes_{lbl}.csv', 'w')
        f.write(','.join(header) + '\n')
        node_files[lbl] = f

    # 打开关系文件，写表头
    rel_files = {}
    rel_types = list(rel_props.keys())
    for typ in rel_types:
        props = rel_props[typ]
        header = [':START_ID', ':END_ID'] + [f'{k}:{t}' for k, t in props]
        f = open(f'{OUT}/rels_{typ}.csv', 'w')
        f.write(','.join(header) + '\n')
        rel_files[typ] = f

    # 流式写节点
    node_counts = collections.Counter()
    with open(DATA, 'rb') as f:
        for e in ijson.items(f, 'entities.item'):
            lbl = e['label']
            node_counts[lbl] += 1
            props = node_props[lbl]
            row = [csv_field(e['eid']), csv_field(e.get('name') or '')]
            p = e.get('properties') or {}
            for k, t in props:
                row.append(fmt_value(p.get(k), t))
            node_files[lbl].write(','.join(row) + '\n')

    # 流式写关系
    rel_counts = collections.Counter()
    with open(DATA, 'rb') as f:
        for r in ijson.items(f, 'relations.item'):
            typ = r['label']
            rel_counts[typ] += 1
            props = rel_props[typ]
            row = [csv_field(r['subj_id']), csv_field(r['obj_id'])]
            p = r.get('properties') or {}
            for k, t in props:
                row.append(fmt_value(p.get(k), t))
            rel_files[typ].write(','.join(row) + '\n')

    for fh in list(node_files.values()) + list(rel_files.values()):
        fh.close()

    # 组装 neo4j-admin import 命令
    cmd = ['neo4j-admin', 'database', 'import', 'full']
    for lbl in node_props:
        cmd.append(f'--nodes={lbl}={OUT}/nodes_{lbl}.csv')
    for typ in rel_types:
        cmd.append(f'--relationships={typ}={OUT}/rels_{typ}.csv')
    cmd.append(GRAPH)

    with open(f'{OUT}/run_import.sh', 'w') as f:
        f.write('#!/usr/bin/env bash\nset -euo pipefail\n')
        f.write(' '.join(cmd) + '\n')
    os.chmod(f'{OUT}/run_import.sh', 0o755)

    print('节点统计:')
    for k, v in sorted(node_counts.items()):
        print(f'  {v:>8}  {k}')
    print('关系统计:')
    for k, v in sorted(rel_counts.items()):
        print(f'  {v:>8}  {k}')
    print()
    print('CSV 已生成到', OUT)
    print('导入命令（需先停库）:')
    print('  ' + ' '.join(cmd))
    print('  或直接执行:  ./' + OUT + '/run_import.sh')


if __name__ == '__main__':
    main()
