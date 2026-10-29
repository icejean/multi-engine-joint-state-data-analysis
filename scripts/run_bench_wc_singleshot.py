#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
works_cycles S 系列(single-shot Text2SQL)基准运行器 —— Sakila run_bench_singleshot.py 的 works_cycles 版。

与 M 系列(run_bench_wc.py, Agent 自迭代)对照:单次 LLM 调用、无工具循环、无数据探测、
无执行反馈。元数据预注入提示词(SPEC §3.2.2 的「预注入」分支):

  S0 = 裸 schema(表/列/类型)
  S1 = schema + 数据字典(sys_tables / sys_table_fields)
  S2 = schema + 字典 + ER 图(sys_foreignkeys)

模型对齐 M 系列(默认 DeepSeek V4 Flash),走 DeepSeek OpenAI 兼容端点
(https://api.deepseek.com/chat/completions),key 读自 ~/.openclaw / ~/.claude / ~/.dsh。

与 sakila 版(run_bench_singleshot.py)的关键差异:
  1. works_cycles 有 65 表 / 455 列(远超 sakila 的 16 表 / 102 列),预注入元数据规模
     大一个数量级。S 系列「预注入」在大 schema 下预期退化(LLM 需从 65 表中挑对表/列),
     这正是 SPEC §3.2.2 已声明的诚实边界:「预注入(S 系列)在大 schema 下不可行」。
  2. 判分用 results_equal_relaxed(与 run_bench_wc.py 的 M 系列一致,放宽多输出列),
     使 S/M 两轴可比。
  3. 额外采集每档平均输入/输出 token:S0→S1→S2 提示词逐级变大,输入 token 梯度是
     S 系列独有的成本信号(对比 M 系列「元数据越丰富成本越低」)。
  4. extract_sql 支持 CTE(从第一个 WITH 或 SELECT 起),BOM 题(Q99~Q103)用 WITH。

数据库映射(三库数据一致,元数据逐级增加):
  schema  dump 自 works_cycles   (裸数据 65 表,无 sys 表)
  字典/ER dump 自 works_cycles_er (sys_tables / sys_table_fields / sys_foreignkeys)

用法:
  python run_bench_wc_singleshot.py --ids 1,26,33,113,99 --levels S0,S1,S2
  python run_bench_wc_singleshot.py --all --levels S0,S1,S2
  python run_bench_wc_singleshot.py --ids 1,26,33 --levels S0,S2 --results results_wc_s_26.json
  python run_bench_wc_singleshot.py --dump-only   # 只看三档元数据规模,不调 LLM
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
import pymysql

SCRIPT_DIR = Path(__file__).resolve().parent
WC_DIR = SCRIPT_DIR / ".." / "data" / "works_cycles"
QUESTIONS_JSON = WC_DIR / "question_set_final_obfuscated.json"
GOLD_JSON = WC_DIR / "gold.json"
RESULTS_JSON = WC_DIR / "results_wc_singleshot.json"

# 去掉 SOCKS 代理(httpx 无 socksio),保留 http 代理
for _k in ("ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

DB_DATA = "works_cycles"        # 裸数据(65 表,无 sys 表)—— dump schema 用
DB_META = "works_cycles_er"     # 完整元数据(字典 + ER)—— dump 字典/ER 用

MODEL = "deepseek-v4-flash"
BASE_URL = "https://api.deepseek.com"
LLM_TIMEOUT = 240  # 对齐 M 系列的 AGENT_TIMEOUT;27K 字符大 schema 提示词 + 推理模型需更宽裕

from score import results_equal_relaxed, execute_sql_columns, diff_extra_columns, _connect  # noqa: E402


def _read_key(base_url):
    """按 base_url 从 openclaw.json 的 provider 取 apiKey;fallback ~/.claude / ~/.dsh。"""
    # 1) openclaw.json 的 provider(权威,openclaw agent 用的就是这份)
    try:
        d = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json")))
        for prov in d.get("models", {}).get("providers", {}).values():
            if prov.get("baseUrl") == base_url or base_url.startswith(prov.get("baseUrl", "")):
                k = prov.get("apiKey")
                if k:
                    return k
    except Exception:
        pass
    # 2) ~/.claude/settings.json 的 ANTHROPIC_AUTH_TOKEN(deepseek key)
    try:
        d = json.load(open(os.path.expanduser("~/.claude/settings.json")))
        tok = d.get("env", {}).get("ANTHROPIC_AUTH_TOKEN")
        if tok:
            return tok
    except Exception:
        pass
    # 3) ~/.dsh/.credentials.yaml 递归找第一个非空 key
    try:
        import yaml
        d = yaml.safe_load(open(os.path.expanduser("~/.dsh/.credentials.yaml")))

        def _find(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if isinstance(v, str) and v:
                        return v
                    r = _find(v)
                    if r:
                        return r
            elif isinstance(o, list):
                for x in o:
                    r = _find(x)
                    if r:
                        return r
            return None
        tok = _find(d)
        if tok:
            return tok
    except Exception:
        pass
    raise RuntimeError(f"找不到 {base_url} 对应的 API key")


def dump_schema(conn):
    """表名 / 列名 / 类型(仅数据表,不含 sys_*)。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name, column_name, column_type
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name NOT LIKE %s
        ORDER BY table_name, ordinal_position
        """,
        (DB_DATA, "sys\\_%"),
    )
    lines = []
    cur_tbl = None
    for tbl, col, ctype in cur.fetchall():
        if tbl != cur_tbl:
            cur_tbl = tbl
            lines.append(f"表 `{tbl}`:")
        lines.append(f"  {col} {ctype}")
    cur.close()
    return "\n".join(lines)


def dump_dictionary(conn):
    """数据字典:sys_tables(table_desc/table_type) + sys_table_fields(field_desc)。"""
    cur = conn.cursor()
    cur.execute("SELECT table_name, table_desc, table_type FROM sys_tables ORDER BY table_name")
    tbl_rows = cur.fetchall()
    cur.execute(
        "SELECT table_name, field_name, field_desc FROM sys_table_fields ORDER BY table_name, field_name"
    )
    fld_rows = cur.fetchall()
    cur.close()
    lines = ["表描述:"]
    for t, d, ty in tbl_rows:
        lines.append(f"  `{t}` [{ty}]: {d}")
    lines.append("字段描述:")
    for t, f, d in fld_rows:
        lines.append(f"  `{t}`.`{f}`: {d}")
    return "\n".join(lines)


def dump_er(conn):
    """ER 图:sys_foreignkeys 的 from -> to(含复合外键列序)。"""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT constraint_name, from_table, from_column, to_table, to_column, column_seq, column_count
        FROM sys_foreignkeys
        ORDER BY constraint_name, column_seq
        """
    )
    rows = cur.fetchall()
    cur.close()
    lines = ["外键关系(ER 图):"]
    for cname, ft, fc, tt, tc, seq, cnt in rows:
        marker = f" [复合外键 {seq}/{cnt}]" if cnt > 1 else ""
        lines.append(f"  {ft}.{fc} -> {tt}.{tc}{marker}")
    return "\n".join(lines)


def build_prompt(level, question, schema, dictionary, er, evidence=None):
    """按档拼提示词,注入元数据。

    meta_instr 与 M 轴(run_bench_wc.py)对齐通用化规范:输出列/过滤条件/复合字段拆分,
    另加 single-shot 专属两条(禁 SELECT *、禁保留字别名)。不包含 M 轴「先查 sys_* 表」、
    「禁切数据源」「禁硬编码」——single-shot 无工具循环/无探索,不适用。
    """
    instr = (
        "你是 Text2SQL 系统。根据下面给出的数据库结构，把用户的问题翻译成一条 MySQL SELECT 语句。\n"
        "只输出 SQL 本身，不要解释，不要 markdown 代码块，不要多余文字。\n"
        "\n"
        "【输出列】SELECT 每一列都要对应题面要求的「一个独立字段」，一列一值，不要自作主张增删列，"
        "不要用 SELECT *。\n"
        "由多个字段组成的复合信息（如姓名＝名＋姓、地址/位置＝省＋市＋邮编）要按字段拆开分别返回，"
        "不要用 CONCAT/CONCAT_WS 拼进同一列（除非题面明确要求拼接成一个字符串）；"
        "题面问「full name/全名」时返回 名+中间名+姓 三列；只问「name/姓名」时返回 名+姓 两列（别多加中间名）。也不要额外输出题面没要求的列（如内部 ID）。\n"
        "\n"
        "【过滤与 JOIN】只加实现题面要求所必需的条件、只 JOIN 题面要求所必需的表，"
        "不要脑补题面没提的约束，也不要额外 JOIN 来缩小范围；"
        "题面问「所有/每个/every/all」时输出应包含该类全部记录，不要额外加会排除部分行的过滤。\n"
        "\n"
        "【有效期/时间态】带结束日期/有效期/失效日期列的表，「当前/生效中」记录 = 该列为 NULL（非空 = 已失效）。"
        "题面问「当前/现在/最新/在职/需要」等当下状态时，要对相关表加 `结束日期列 IS NULL` 过滤——"
        "题面问「历史/曾经/离职/离开」等过去状态时，用 `结束日期列 IS NOT NULL`；"
        "递归 CTE（WITH RECURSIVE）的 base 和 recursive 两层都要加，否则会把已失效的历史行算进去。\n"
        "\n"
        "【取最新值】带变更日期列的历史表（薪资历史、价格历史等），题面问「当前/最新/平均薪资·时薪·价格」时，"
        "先取每人/每物最新一条（变更日期列 = 该对象内的 MAX）再聚合，不要直接对全部历史行 AVG/SUM；"
        "凡 JOIN 到「一人/一物多行」的历史表（薪资历史、任职历史、价格历史）并对它做 AVG/SUM/MAX/COUNT 聚合时，"
        "必须先按 `变更日期列 = 该对象内的 MAX` 过滤到每人最新一行再聚合，否则历史行会重复加权。"
        "但题面只是「第 N 高/最高/排名/排序」（不是问当前/最新），就不取最新、直接按该列排序取。\n"
        "\n"
        "【递归 CTE】WITH RECURSIVE 的层级（level）必须用 `level + 1` 在递归里累加（base 层=1，recursive 层=上一层层级+1）。"
        "禁止用表里预存的层级/深度列（如 bm_lvl/BOMLevel）当「相对当前产品的递归层级」——预存列是「相对根件的全局层级」。"
        "求「最深装配层级」= 递归 CTE 里的 MAX(level)。\n"
        "\n"
        "【去重】JOIN 可能产生一对多（fan-out，一人/一物对应多行）时，要在最终结果里加 DISTINCT 或 GROUP BY 去重"
        "（除非题面明确要「按行计数/所有记录」）。去重对象是实体（人/物/订单/产品），不是值："
        "用 GROUP BY 实体主键 或 DISTINCT 实体标识列，不要对返回值列（金额/名字）做 DISTINCT。"
        "题面问「每个实体有几个/列出实体」时，一律按实体主键去重。\n"
        "\n"
        "【语义按字面理解】题面里的业务名词（如「账户/accounts」）按「能直接命中的表字段」做最字面理解："
        "evidence/题面说 `count(某字段=值)` 时就是数满足条件的行数，不要联想成业务实体（账户→客户/门店）再绕多表 JOIN。\n"
        "\n"
        "【数量比较】over/more than N = 严格 >N（不是 ≥N）；at least N = ≥N；N 及以上 = ≥N。\n"
        "\n"
        "【聚合口径】average/平均 = AVG(...)，除非 evidence/题面明确给了 SUM/COUNT 公式。\n"
        "【输出形状】问 Yes/No（是否/有没有）→ 用 `CASE WHEN ... THEN 'Yes' ELSE 'No' END`；问名字/名称 → 返回 name 列不是 code/ID。\n"
        "\n"
        "【否定条件】题面里的否定词要逐字读：'no/not/without/没有/无/不' 表示「取没有的那部分」，"
        "对应 SQL 用 `= 0`、`IS NULL` 或 `NOT`，不要写成 `> 0`（那会变成「有」的反义）。"
        "例如「没有折扣/无任何 offer」= `折扣列 = 0` 或 `折扣列 IS NULL`，不是 `> 0`。\n"
        "\n"
        "【SQL 细节】CTE/别名不要用 MySQL 保留字（如 usage、order、group）。\n"
    )
    parts = [instr, "【数据库结构】表名、列名、列类型：", schema]
    if level in ("S1", "S2"):
        parts += ["", "【数据字典】表描述与字段描述（据此确定每列含义与关联列，尤其自引用表如物料清单的父/子列）：", dictionary]
    if level == "S2":
        parts += ["", "【外键关系】ER 图（据此写表间 JOIN）：", er]
    parts += ["", "【问题】", question]
    if evidence:
        parts += ["", "【外部知识（用于消歧，来自 BIRD 官方 evidence）】", evidence]
    parts += ["", "SQL："]
    return "\n".join(parts)


def extract_sql(text):
    """从 LLM 回复里提取第一条 SQL 语句(支持 CTE,从第一个 WITH 或 SELECT 起)。"""
    if not text:
        return ""
    # 去 markdown 代码块
    text = re.sub(r"```(?:sql)?", "", text)
    # 从第一个 WITH 或 SELECT 开始到分号或结尾
    m = re.search(r"\b(WITH|SELECT)\b.*", text, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    sql = m.group(0)
    sql = sql.split(";")[0]
    return sql.strip()


def call_llm(api_key, model, base_url, prompt):
    """单次 OpenAI 兼容调用,返回 (content, model, tokens)。"""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=LLM_TIMEOUT) as client:
        resp = client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    # 推理模型的 content 可能为空,兜底 reasoning_content
    content = msg.get("content") or msg.get("reasoning_content") or ""
    usage = data.get("usage") or {}
    tokens = {
        "input": usage.get("prompt_tokens"),
        "output": usage.get("completion_tokens"),
        "total": usage.get("total_tokens"),
    }
    return content, data.get("model"), tokens


def run_one(api_key, model, base_url, level, q, gold, schema, dictionary, er, conn):
    prompt = build_prompt(level, q["question"], schema, dictionary, er, q.get("evidence"))
    result = {
        "question_id": q["id"],
        "s_level": level,
        "final_sql": "",
        "pass": False,
        "error": None,
        "model": None,
        "tokens": None,
        "elapsed_seconds": None,
        "extra_columns": [],
    }
    t0 = time.perf_counter()
    try:
        content, used_model, tokens = call_llm(api_key, model, base_url, prompt)
        result["model"] = used_model
        result["tokens"] = tokens
        sql = extract_sql(content)
        result["final_sql"] = sql
        if not sql:
            result["error"] = "no sql extracted"
            return result
        cand_cols, cand_rows = execute_sql_columns(conn, sql)
        result["pass"] = results_equal_relaxed(gold["rows"], cand_rows)
        if result["pass"]:
            result["extra_columns"] = diff_extra_columns(
                gold["rows"], gold.get("columns", []), cand_rows, cand_cols
            )
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["pass"] = False
    finally:
        result["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
    return result


def load_json(p):
    return json.loads(Path(p).read_text())


def load_existing(results_json):
    if results_json.exists():
        data = load_json(results_json)
        return data.get("runs", [])
    return []


def _stat(vals):
    """算术平均;空序列返回 nan。"""
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else float("nan")


def _print_token_report(runs, levels):
    print(f"\n{'=' * 60}")
    print("== 成本汇总(输入 token 梯度:S0→S1→S2 提示词逐级变大) ==")
    for lvl in levels:
        lv = [r for r in runs if r["s_level"] == lvl and r.get("tokens")]
        if not lv:
            print(f"{lvl}: 无 token 数据")
            continue
        tok_in = _stat([r["tokens"]["input"] for r in lv])
        tok_out = _stat([r["tokens"]["output"] for r in lv])
        tok_tot = _stat([r["tokens"]["total"] for r in lv])
        secs = _stat([r["elapsed_seconds"] for r in lv])
        print(f"{lvl}: 均 token in={tok_in:,.0f} out={tok_out:,.0f} total={tok_tot:,.0f} | "
              f"耗时={secs:.1f}s (n={len(lv)})")


def _dump_only():
    """打印三档元数据规模(不调 LLM),供核对 S 轴预注入量。"""
    conn_meta = _connect(DB_META)
    try:
        schema = dump_schema(conn_meta)
        dictionary = dump_dictionary(conn_meta)
        er = dump_er(conn_meta)
    finally:
        conn_meta.close()
    print(f"schema   {len(schema.splitlines()):5d} 行 / {len(schema):6d} 字符")
    print(f"字典     {len(dictionary.splitlines()):5d} 行 / {len(dictionary):6d} 字符")
    print(f"ER       {len(er.splitlines()):5d} 行 / {len(er):6d} 字符")
    print(f"S0 提示词(裸 schema)   ≈ {len(schema):,} 字符")
    print(f"S1 提示词(+字典)       ≈ {len(schema) + len(dictionary):,} 字符")
    print(f"S2 提示词(+字典+ER)    ≈ {len(schema) + len(dictionary) + len(er):,} 字符")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="逗号分隔的题号(整数),如 1,26,33,113,99")
    ap.add_argument("--all", action="store_true", help="跑全部题(仅含 gold 可判分的题)")
    ap.add_argument("--levels", default="S0,S1,S2")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--results", default="results_wc_singleshot.json")
    ap.add_argument("--sleep", type=int, default=0, help="每道题之间的间隔秒数(限流用)")
    ap.add_argument("--dump-only", action="store_true", help="只打印三档元数据规模,不调 LLM")
    args = ap.parse_args()

    if args.dump_only:
        _dump_only()
        return

    questions = load_json(QUESTIONS_JSON)["questions"]
    gold = {g["id"]: g for g in load_json(GOLD_JSON)}
    levels = [x.strip() for x in args.levels.split(",") if x.strip()]

    if args.all:
        selected = questions
    elif args.ids:
        ids = {int(x.strip()) for x in args.ids.split(",") if x.strip()}
        selected = [q for q in questions if q["id"] in ids]
    else:
        print("请用 --ids 或 --all 指定题")
        sys.exit(2)

    # 只跑 gold 可判分的题(gen_gold_wc.py 已把执行失败的题剔除出 gold)
    no_gold = [q["id"] for q in selected if q["id"] not in gold]
    selected = [q for q in selected if q["id"] in gold]
    if no_gold:
        print(f"⚠️ 跳过无 gold 的 {len(no_gold)} 题: {no_gold}")

    # 元数据 dump(一次性)
    conn_data = _connect(DB_DATA)
    conn_meta = _connect(DB_META)
    try:
        schema = dump_schema(conn_data)
        dictionary = dump_dictionary(conn_meta)
        er = dump_er(conn_meta)
    finally:
        conn_data.close()
        conn_meta.close()

    results_json = WC_DIR / args.results
    api_key = _read_key(args.base_url)

    # 断点续跑
    runs = load_existing(results_json)
    existing = {(r["question_id"], r["s_level"]) for r in runs}
    todo = [(q, lvl) for q in selected for lvl in levels if (q["id"], lvl) not in existing]
    print(f"共 {len(todo)} 次待跑({len(selected)} 题 × {len(levels)} 档),已跳过 {len(existing)} 次")

    conn = _connect(DB_DATA)
    try:
        for i, (q, lvl) in enumerate(todo, 1):
            print(f"\n[{i}/{len(todo)}] {q['id']} ({lvl}) ...", flush=True)
            r = run_one(api_key, args.model, args.base_url, lvl, q, gold[q["id"]],
                        schema, dictionary, er, conn)
            runs.append(r)
            results_json.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2))
            tok = r.get("tokens") or {}
            extra = r.get("extra_columns") or []
            extra_s = f" 多列={extra}" if extra else ""
            st = "✅" if r["pass"] else ("⚠️" if r["error"] else "❌")
            print(f"    {st} pass={r['pass']} tok={tok.get('total', '?')} "
                  f"{r.get('elapsed_seconds', 0):.0f}s err={r['error']}{extra_s}")
            if args.sleep > 0:
                time.sleep(args.sleep)
    finally:
        conn.close()

    # 报告
    print(f"\n{'=' * 60}\n== 报告(S 系列 single-shot)==")
    ex = {}
    for lvl in levels:
        lv = [r for r in runs if r["s_level"] == lvl]
        if not lv:
            continue
        passed = sum(1 for r in lv if r["pass"])
        ex[lvl] = passed / len(lv)
        print(f"\n{lvl}: EX {passed}/{len(lv)} = {ex[lvl]*100:.1f}%")
        extra = [(r["question_id"], r.get("extra_columns")) for r in lv if r.get("extra_columns")]
        if extra:
            print(f"    带多余列(放宽判对但多输出): {len(extra)}/{len(lv)} 题")
            for qid, cols in extra:
                print(f"      Q{qid}: 多出 {cols}")
        dom_stat = {}
        for r in lv:
            d = gold[r["question_id"]]["domain"]
            dom_stat.setdefault(d, [0, 0])
            dom_stat[d][1] += 1
            if r["pass"]:
                dom_stat[d][0] += 1
        for d, (p, tot) in sorted(dom_stat.items()):
            print(f"    {d:14s} {p}/{tot}")
        fails = [r["question_id"] for r in lv if not r["pass"]]
        if fails:
            print(f"    失败: {', '.join(map(str, fails))}")

    _print_token_report(runs, levels)

    if "S0" in ex:
        for lvl in ("S1", "S2"):
            if lvl in ex:
                print(f"\nΔ₄({lvl}) = EX({lvl}) - EX(S0) = {(ex[lvl]-ex['S0'])*100:+.1f} 个百分点")
        if "S1" in ex and "S2" in ex:
            num = ex["S1"] - ex["S0"]
            den = ex["S2"] - ex["S0"]
            capture = (num / den) if den else float("nan")
            print(f"收益捕获率 = Δ₄(S1)/Δ₄(S2) = {capture:.2f}")


if __name__ == "__main__":
    main()
