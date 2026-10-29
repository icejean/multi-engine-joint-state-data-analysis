#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dump movie 图库的 schema(节点标签 + 属性 + 关系类型 + 方向) → data/movie/movie_schema.json。

这是 M+S 模式里「schema 资源文件」的自动生成器(对应 works_cycles 的
gen_schema_resource.py)。产物是 agent 写 Cypher 的权威结构来源:

  {
    "nodes": {
      "Movie": {"count": 218828, "properties": {
          "name": {"present": 218828, "type": "String", "sample": "The Matrix"},
          "global_box_office_usd": {"present": 1263, "type": "Float", "sample": 1030314141.0}
      }},
      ...
    },
    "relationships": {
      "hasCastMember": {"count": 123456, "from": "Movie", "to": "Person"},
      ...
    }
  }

属性类型靠采样节点值推断(Python type),样本只取一个非空值;`present` = 有该属性的
节点数(count 减 absent 即 null 比例)。notes.md(踩坑清单)不在本脚本范围,由人工补充。

用法:
  python gen_schema_movie.py [--out /abs/movie_schema.json]
"""
import argparse
import json
import os

from score_cypher import connect_graph, _ser

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MOVIE_DIR = os.path.join(SCRIPT_DIR, "..", "data", "movie")
DEFAULT_OUT = os.path.join(MOVIE_DIR, "movie_schema.json")


def _type_of(v):
    if isinstance(v, bool):
        return "Boolean"
    if isinstance(v, int):
        return "Integer"
    if isinstance(v, float):
        return "Float"
    if isinstance(v, str):
        return "String"
    if isinstance(v, list):
        return "List"
    return type(v).__name__


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    driver, database = connect_graph()
    try:
        with driver.session(database=database) as s:
            labels = [r["label"] for r in s.run("CALL db.labels() YIELD label RETURN label")]
            nodes = {}
            for lb in labels:
                cnt = s.run(f"MATCH (n:`{lb}`) RETURN count(n) AS c").single()["c"]
                props = {}
                for r in s.run(f"MATCH (n:`{lb}`) UNWIND keys(n) AS k RETURN k, count(n) AS c ORDER BY c DESC"):
                    k = r["k"]
                    present = r["c"]
                    sample = s.run(
                        f"MATCH (n:`{lb}`) WHERE n.`{k}` IS NOT NULL RETURN n.`{k}` AS v LIMIT 1"
                    ).single()
                    sample_v = sample["v"] if sample else None
                    props[k] = {"present": present, "type": _type_of(sample_v), "sample": _ser(sample_v)}
                nodes[lb] = {"count": cnt, "properties": props}

            rtypes = [r["relationshipType"] for r in
                      s.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType")]
            rels = {}
            for rt in rtypes:
                cnt = s.run(f"MATCH ()-[r:`{rt}`]->() RETURN count(r) AS c").single()["c"]
                ends = s.run(
                    f"MATCH (a)-[r:`{rt}`]->(b) "
                    f"RETURN collect(DISTINCT head(labels(a))) AS froms, collect(DISTINCT head(labels(b))) AS tos LIMIT 1"
                ).single()
                rels[rt] = {
                    "count": cnt,
                    "from": ends["froms"] if ends else [],
                    "to": ends["tos"] if ends else [],
                }
    finally:
        driver.close()

    schema = {"nodes": nodes, "relationships": rels}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
    print(f"schema 已写出: {args.out}")
    print(f"  节点标签 {len(nodes)} 个, 关系类型 {len(rels)} 个")
    for lb, meta in nodes.items():
        print(f"    {lb:20} 节点 {meta['count']:>8}  属性 {len(meta['properties'])} 个")
    for rt, meta in rels.items():
        print(f"    {rt:20} 关系 {meta['count']:>8}  {meta['from']} -> {meta['to']}")


if __name__ == "__main__":
    main()
