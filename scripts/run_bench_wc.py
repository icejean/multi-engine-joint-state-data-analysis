#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
works_cycles 三梯度(元数据梯度)基准运行器 —— Sakila run_bench.py 的 works_cycles 版。

驱动 openclaw agent 跑题库 → 提终答 SQL → 判分 → EX / Δ₄ / 收益捕获率 报告。
机制与 Sakila 实验完全一致:同一批题 × 三档元数据,差分衡量「数据字典 / ER 图」的增量价值。

除准确率外,每题额外记录「算力成本」指标(核算大规模生产的 token/时间/美元成本):
  model          实际使用的模型(provider/model,含模型回退)
  turns / tool_rounds  总轮数 / 调用工具的轮数(一次 LLM 调用 = 一轮)
  tokens         {input, output, cache_read, cache_write, reasoning, total}
  cost_usd       美元成本(openclaw 转录自带;DSH 无)
  elapsed_seconds / agent_duration_ms  墙上耗时 / agent 自报耗时
末尾「成本汇总」给出每档平均成本 + 梯度间「每 +1pp 准确率的边际算力代价」,支撑
「算力 × 成本」平衡决策。

可断点续跑:结果逐条落盘到 data/works_cycles/results_wc.json,已跑过的 (question_id, m_level)
自动跳过;中断后重跑同命令即可续。

M 档 → 数据库映射(三库数据一致,元数据逐级增加):
  M0 → works_cycles       裸数据(65 表,混淆名,无 sys 表)
  M1 → works_cycles_dict  + sys_tables / sys_table_fields(数据字典)
  M2 → works_cycles_er    + sys_foreignkeys(ER 图)

用法:
  # 5 题 pilot
  python run_bench_wc.py --ids 1,5,99,100,116
  # 全量 126 题(仅含 gold 可判分的题)
  python run_bench_wc.py --all
  # 指定 M 档(默认 M0,M2)
  python run_bench_wc.py --all --levels M0,M2
  # 信创环境(无 OpenClaw)走 DSH 后端
  python run_bench_wc.py --all --backend dsh --model glm-5.2 --results results_wc_glm52_dsh.json

前置:三个 works_cycles 库需先注册为数据源(.datasources.json),否则 agent 端连不上。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WC_DIR = SCRIPT_DIR / ".." / "data" / "works_cycles"
QUESTIONS_JSON = WC_DIR / "question_set_final_obfuscated.json"
GOLD_JSON = WC_DIR / "gold.json"
RESULTS_JSON = WC_DIR / "results_wc.json"

HOME = Path.home()
DB_BY_LEVEL = {"M0": "works_cycles", "M1": "works_cycles_dict", "M2": "works_cycles_er"}
AGENT_TIMEOUT = 360

# ── DSH(DeepSeek Harness)后端 ─────────────────────────────────────────────
# 信创环境装不了 OpenClaw 时走 dsh headless;与 Portal 的 DeepSeekHarnessAdapter
# (dataai-portal/backend/app/services/agents/deepseek_harness.py)逐字对齐。
DSH_CWD = HOME / ".dsh" / "workspace"
DSH_MODEL_MAP = {
    "deepseek-v4-flash": ("deepseek-official", "deepseek-v4-flash"),
    "deepseek-v4-pro": ("deepseek-official", "deepseek-v4-pro"),
    "glm-5.1": ("zai", "glm-5.1"),
    "glm-5.2": ("zai", "glm-5.2"),
    "glm-5-pro": ("xirang", "GLM-5-Pro"),
    "GLM-5-Pro": ("xirang", "GLM-5-Pro"),
    "deepseek-v3.2-pro": ("xirang", "DeepSeek-V3.2-Pro"),
    "minimax-m3": ("minimax", "MiniMax-M3"),
}
BACKEND_ENV = {"openclaw": "openclaw", "dsh": "deepseek_harness"}

from score import results_equal_relaxed, execute_sql_columns, diff_extra_columns, _connect  # noqa: E402


def load_json(p):
    return json.loads(Path(p).read_text())


def extract_sqls(text):
    """从审计日志提取 SQL 语句列表。

    每条 SQL 前有 `-- @ds:` / `// @ds:` 分隔行,且 SQL 本身可跨多行。
    按分隔行分组、组内多行拼成一条,返回完整语句列表(按执行顺序)。
    """
    stmts, cur = [], []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("-- @ds:") or s.startswith("// @ds:"):
            if cur:
                stmts.append(" ".join(cur))
                cur = []
            continue
        if not s or s.startswith("--") or s.startswith("//"):
            continue
        cur.append(s)
    if cur:
        stmts.append(" ".join(cur))
    return stmts


def write_mcp_chat_id(chat_id):
    p = HOME / ".jupyter-mcp" / "current_chat_id"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(chat_id)


# ── DSH 后端 helpers ──

def _find_dsh():
    """定位 dsh 可执行文件(系统 PATH / ~/.local 优先,兜底裸名)。"""
    found = shutil.which("dsh")
    if found:
        return found
    for local_bin in (HOME / ".local" / "bin" / "dsh", HOME / ".local" / "node_modules" / ".bin" / "dsh"):
        if local_bin.is_file():
            return str(local_bin)
    return "dsh"


def _dsh_model_patch(model):
    """生成 dsh 的 --patch 模型路由覆盖文件,返回路径。"""
    provider, dsh_model = DSH_MODEL_MAP.get(model, ("deepseek-official", model))
    patch = (
        "- id: agent-default-model\n"
        "  config:\n"
        f"    provider: {provider}\n"
        f"    model: {dsh_model}\n"
    )
    safe = re.sub(r"[^A-Za-z0-9_.-]", "-", model)
    p = HOME / ".dsh" / f"model-patch-bench-{safe}.yml"
    p.write_text(patch, encoding="utf-8")
    return str(p)


def _dsh_session_file(chat_id):
    """定位 dsh 会话 JSONL(zstd 或明文),按 session id 全局 glob。"""
    session_id = f"session-{chat_id}"
    base = HOME / ".dsh" / "sessions"
    for suffix in ("session.jsonl.zstd", "session.jsonl"):
        for p in base.glob(f"*/{session_id}/{suffix}"):
            return p
    return None


def _dsh_tool_calls(session_path):
    """统计最新一轮的 tool/call 次数(DSH stdout 无结构化 toolSummary)。"""
    if session_path is None:
        return 0
    if str(session_path).endswith(".zstd"):
        r = subprocess.run(["zstd", "-dc", str(session_path)], capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return 0
        text = r.stdout
    else:
        try:
            text = session_path.read_text(encoding="utf-8")
        except Exception:
            return 0
    max_turn, count = -1, 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "tool/call":
            continue
        turn = obj.get("data", {}).get("turn", 0)
        if turn > max_turn:
            max_turn, count = turn, 1
        elif turn == max_turn:
            count += 1
    return count


# ── 成本指标采集(模型 / 轮数 / token / 美元成本) ───────────────────────────
# 每次 assistant 回合 = 一次计费的 LLM 调用,跨回合累加即整题总成本。
# 元数据梯度测试除了准确率(EX/Δ₄),还要核算「算力 × 成本」的平衡:同一题在三档
# 元数据下的 token/时间/美元成本,可算出「每提升 1pp 准确率要付多少算力」。
# 后端无关的统一口径:
#   model       实际使用的模型(provider/model,含 openclaw 的模型回退)
#   turns       总轮数(assistant 回合数,一次 LLM 调用 = 一轮)
#   tool_rounds 调用工具的轮数(发出 ≥1 次 toolCall 的回合数)
#   tool_calls  总工具调用次数(全部 toolCall 条目数)
#   tokens      {input, output, cache_read, cache_write, reasoning, total}
#   cost_usd    总美元成本(openclaw 转录自带 cost;DSH 无 cost → None)


def _openclaw_cost_from_transcript(session_file):
    """从 openclaw 会话转录 JSONL 提取成本指标。失败返回空 dict。"""
    if not session_file:
        return {}
    p = Path(session_file)
    if not p.exists():
        return {}
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {}
    turns = tool_rounds = tool_calls = 0
    tok_input = tok_output = tok_cache_read = tok_cache_write = tok_reasoning = 0
    cost_usd = 0.0
    has_cost = False
    model = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") != "message":
            continue
        m = obj.get("message") or {}
        if m.get("role") != "assistant":
            continue
        turns += 1
        provider, mid = m.get("provider"), m.get("model")
        if provider or mid:
            model = f"{provider}/{mid}"
        n_calls = 0
        content = m.get("content")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "toolCall":
                    n_calls += 1
        tool_calls += n_calls
        if n_calls > 0:
            tool_rounds += 1
        u = m.get("usage") or {}
        tok_input += u.get("input") or 0
        tok_output += u.get("output") or 0
        tok_cache_read += u.get("cacheRead") or 0
        tok_cache_write += u.get("cacheWrite") or 0
        tok_reasoning += u.get("reasoningTokens") or 0
        c = u.get("cost")
        if isinstance(c, dict) and c.get("total") is not None:
            cost_usd += float(c["total"])
            has_cost = True
    return {
        "model": model,
        "turns": turns,
        "tool_rounds": tool_rounds,
        "tool_calls": tool_calls,
        "tokens": {
            "input": tok_input,
            "output": tok_output,
            "cache_read": tok_cache_read,
            "cache_write": tok_cache_write,
            "reasoning": tok_reasoning,
            "total": tok_input + tok_output + tok_cache_read + tok_cache_write,
        },
        "cost_usd": round(cost_usd, 6) if has_cost else None,
    }


def _dsh_cost_from_session(session_path):
    """从 DSH 会话 JSONL(zstd/明文)提取成本指标。DSH 无美元成本 → cost_usd=None。"""
    if session_path is None:
        return {}
    if str(session_path).endswith(".zstd"):
        r = subprocess.run(["zstd", "-dc", str(session_path)], capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            return {}
        text = r.stdout
    else:
        try:
            text = Path(session_path).read_text(encoding="utf-8")
        except Exception:
            return {}
    model = None
    steps, tool_steps = set(), set()
    tool_calls = 0
    tok_input = tok_output = tok_cache_read = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = obj.get("type")
        d = obj.get("data") or {}
        if t == "request/header":
            cfg = (d.get("header") or {}).get("config") or {}
            if cfg.get("provider") or cfg.get("model"):
                model = f"{cfg.get('provider')}/{cfg.get('model')}"
        elif t == "request/context":
            if d.get("provider") or d.get("model"):
                model = f"{d.get('provider')}/{d.get('model')}"
        elif t == "step/start":
            steps.add((d.get("turn"), d.get("step")))
        elif t == "tool/call":
            tool_calls += 1
            tool_steps.add((d.get("turn"), d.get("step")))
        elif t == "assistant/chunk":
            ch = d.get("chunk") or {}
            if ch.get("type") == "usage":
                u = ch.get("usage") or {}
                tok_input += u.get("inputTokens") or 0
                tok_output += u.get("outputTokens") or 0
                tok_cache_read += u.get("cacheReadTokens") or 0
    return {
        "model": model,
        "turns": len(steps),
        "tool_rounds": len(tool_steps),
        "tool_calls": tool_calls,
        "tokens": {
            "input": tok_input,
            "output": tok_output,
            "cache_read": tok_cache_read,
            "cache_write": 0,
            "reasoning": None,
            "total": tok_input + tok_output + tok_cache_read,
        },
        "cost_usd": None,
    }


def _apply_cost(result, cost):
    """把成本指标 dict 合并进 result(cost 为 None 或字段为 None 时不覆盖)。"""
    if not cost:
        return result
    for k in ("model", "turns", "tool_rounds", "tokens", "cost_usd"):
        if cost.get(k) is not None:
            result[k] = cost[k]
    if cost.get("tool_calls") is not None:
        result["tool_calls"] = cost["tool_calls"]
    return result


def agent_turn(question_id, question, ds_name, m_level, model="deepseek-v4-flash", backend="openclaw", model_patch=None, evidence=None):
    """驱动 agent 回答一题,返回结果 dict。"""
    chat_id = uuid.uuid4().hex
    write_mcp_chat_id(chat_id)

    meta_instr = (
        f"【重要】本次任务只允许查询数据源 `{ds_name}` 这一个数据源，"
        "禁止 list_datasources 后切换到其他任何数据源（这在元数据梯度测试中属于作弊，严格禁止）。"
        "\n\n【重要】生成 SQL 之前，先摸清表结构：先查该数据源内可用的元数据表"
        "（sys_tables、sys_table_fields、sys_foreignkeys）。"
        "如果该数据源内存在这些表，必须先查，并且【数据字典与 ER 图结合使用】："
        "sys_foreignkeys（外键关系表，即 ER 图）给出表间关联列，用来写 JOIN；"
        "sys_tables / sys_table_fields（数据字典）给出每个表、每个字段的含义。"
        "尤其自引用表（如 BOM 组件表自己指向自己）和歧义列，ER 可能不含这种逻辑自引用，"
        "必须靠字典的字段注释来确定关联列，不要只看 ER 忽略字典。"
        "如果该数据源内【不存在】这些 sys_* 元数据表（裸库），就用 list_objects 列出全部表、"
        "再用 preview_data 抽查关键表的列名，据此确定表结构和关联列。"
        "任何一张表查一次报错「不存在」后，立刻改用 list_objects / preview_data，不要反复重试同一张表。"
        "\n\n【重要】输出列：SELECT 每一列都要对应题面要求的「一个独立字段」，一列一值，不要自作主张增删列。"
        "不要用 CONCAT/CONCAT_WS 把多个字段的值拼进同一列，除非题面明确要求「拼接/合并/写成一列/返回单个字符串」。"
        "由多个字段组成的复合信息（如姓名＝名＋姓、地址/位置＝各行＋市＋州＋邮编）要按字段拆开分别返回，不要合成一列；"
        "题面问「full name/全名」时返回 名+中间名+姓 三列；只问「name/姓名」时返回 名+姓 两列（别多加中间名）。"
        "也不要额外输出题面没要求的列（如内部 ID）。"
        "\n\n【重要】过滤条件：只加实现题面要求所必需的条件，不要脑补题面没提的约束；"
        "题面问「所有/每个/every/all」某类记录时，输出应包含该类全部记录，不要额外加会排除部分行的过滤条件（如某地址类型、某状态标志）。"
        "不要「硬编码」：不要把你探索数据时看到的某个具体 ID/值直接写进 WHERE（如 `WHERE id IN (1,2,3)`），"
        "题面的语义条件（如「某类产品」「某地区」「某状态」）要用对应的表字段和 WHERE 条件表达，"
        "除非题面明确给出了具体值（如「product ID 843」）。"
        "\n\n【重要】有效期/时间态：带结束日期/有效期/失效日期列的表（如 `end_dt`），「当前/生效中」的记录 = 该列为 NULL（非空 = 已失效）。"
        "题面问「当前/现在/最新/在职/仍在」等当下状态时，要对相关表加 `结束日期列 IS NULL` 过滤；"
        "题面问「历史/曾经/离职/离开/已离开」等过去状态时，用 `结束日期列 IS NOT NULL`（或按题面语义不过滤）。"
        "递归 CTE（WITH RECURSIVE）的 base 和 recursive 两层都要按上述规则处理，拿不准时按题面字面判断、不要省略过滤。"
        "\n\n【重要】取最新值：带变更日期列的历史表（如薪资历史 `rt_chng_dt`、价格历史），"
        "题面问「当前/最新/平均薪资·时薪·价格」时，先取每人/每物最新一条（变更日期列 = 该对象内的 MAX）再聚合，"
        "不要直接对全部历史行 AVG/SUM/MAX；"
        "★凡 JOIN 到「一人/一物多行」的历史表（薪资历史、任职历史、价格历史）并对它做 AVG/SUM/MAX/COUNT 聚合时，"
        "必须先按 `变更日期列 = 该对象内的 MAX` 过滤到每人最新一行再聚合，否则历史行会重复加权、把平均值/总额算错。"
        "但题面只是「第 N 高/最高/最低/排名/排序」（不是问「当前/最新」），就**不取最新**，直接按该列排序取。"
        "\n\n【重要】递归 CTE：WITH RECURSIVE 的层级（level）必须用 `level + 1` 在递归里累加（base 层=1，recursive 层=上一层层级+1）。"
        "禁止用表里预存的层级/深度列（如 `bm_lvl`/BOMLevel）当「相对当前产品的递归层级」——预存列是「相对根件的全局层级」，不是题面问的「相对某产品的装配层级」。"
        "求「最深装配层级」= 递归 CTE 里的 `MAX(level)`。"
        "\n\n【重要】SQL 细节：CTE/别名不要用 MySQL 保留字（如 usage、order、group）。"
        "\n\n【重要】语义按字面理解、尽早收敛：题面里的业务名词按「能直接命中的表字段」做最字面理解，"
        "不要过度联想成业务实体再绕多表 JOIN（如「账户/accounts」若 addr 表直接有城市字段，就按地址行数 COUNT 理解，"
        "不要联想成客户/门店/供应商）。探索的唯一目的是找到「能回答题面的最小表集合」："
        "一旦确认字段含义，立即写出最终答案 SQL 并停止，不要反复换一种解读、不要继续枚举其他候选实体。"
        "探索最多 12 轮，第 12 轮必须输出最终答案 SQL（不确定也基于已探明信息给最优解）。"
        "\n\n【重要】数量比较：over/more than N = 严格 >N（不是 ≥N）；at least N = ≥N；N 及以上 = ≥N。"
        "\n\n【重要】聚合口径：average/平均 = AVG(...)，除非 evidence/题面明确给了 SUM/COUNT 公式。"
        "\n\n【重要】输出形状：题面问 Yes/No（是否/有没有）→ 用 `CASE WHEN ... THEN 'Yes' ELSE 'No' END`；题面问「名字/名称/是谁」→ 返回 name/名字列，不要返回 code/ID 列。"
        "\n\n【重要】去重判断：JOIN 可能产生一对多（fan-out，一人/一物对应多行）时，写完最终 SQL 前先用 preview_data 抽查关键表的实际数据行，"
        "确认会不会有重复；若会重复，加 DISTINCT 或 GROUP BY 去重（除非题面明确要「按行计数/所有记录」）。"
        "去重对象是**实体**（人/物/订单/产品），不是值：用 `GROUP BY 实体主键` 或 `DISTINCT 实体标识列`，不要对返回值列（小时数/金额/名字）做 DISTINCT。"
        "别只看了字典/ER 就写 JOIN——字典给字段含义、数据才能暴露重复。"
        "\n\n【重要】否定条件：题面里的否定词要逐字读——'no/not/without/没有/无/不' 表示「取没有的那部分」，"
        "对应 SQL 用 `= 0`、`IS NULL` 或 `NOT`，**不要写成 `> 0`**（那会变成「有」的反义）。"
        "例如「没有折扣/无任何 offer」= `折扣列 = 0` 或 `折扣列 IS NULL`，不是 `> 0`。"
        "\n\n【重要】最终答案：系统只取你最后执行的一条 SQL 作为最终答案，它必须是「直接回答题面的数据查询」（SELECT 出题面要的字段）。"
        "绝不能停在探索语句上——如 `SHOW TABLES`、查 `sys_*`/`information_schema`、`SELECT *`、`COUNT(*)` 试数、"
        "或把探索时看到的 ID 写死进 WHERE（如 `WHERE ref3 = 680`）——这些探索只是为了找答案，"
        "找到后必须再输出真正的答案 SQL（用题面的名字/语义条件，如 `WHERE nm = '...'`）。"
        "得到答案后不要再执行任何验证/交叉核对/汇总 SQL，末尾多跑语句会导致答案被判错。"
    )
    msg = f"请使用数据源 {ds_name} 回答下面的问题。\n\n{meta_instr}\n\n{question}"
    if evidence:
        msg += f"\n\n【外部知识（用于消歧，来自 BIRD 官方 evidence）】{evidence}"

    env = os.environ.copy()
    env["DATAAI_CHAT_ID"] = chat_id
    env["AGENT_BACKEND"] = BACKEND_ENV[backend]

    if backend == "dsh":
        cmd = [_find_dsh(), "--profile", "headless"]
        if model_patch:
            cmd += ["--patch", model_patch]
        cmd += ["--session-id", f"session-{chat_id}", msg]
    else:
        session_key = f"agent:main:portal-{chat_id}"
        cmd = [
            "openclaw", "agent", "--agent", "main",
            "--model", model,
            "--session-key", session_key, "--message", msg,
            "--local", "--json", "--timeout", str(AGENT_TIMEOUT),
        ]

    result = {
        "question_id": question_id,
        "m_level": m_level,
        "datasource": ds_name,
        "chat_id": chat_id,
        "final_sql": "",
        "sql_history": [],
        "agent_text": "",
        "tool_calls": 0,
        "pass": False,
        "error": None,
        # ── 成本指标(新) ──
        "model": model,           # 请求的模型;解析出实际模型后覆盖
        "turns": 0,               # 总轮数
        "tool_rounds": 0,         # 调用工具的轮数
        "tokens": None,           # {input, output, cache_read, cache_write, reasoning, total}
        "cost_usd": None,         # 美元成本(openclaw 有,DSH 无)
        "elapsed_seconds": None,  # 墙上耗时(subprocess)
        "agent_duration_ms": None,  # agent 自报耗时(meta.durationMs,openclaw)
        "extra_columns": [],      # 候选多输出的列名(放宽判分后的备注,空=无多余列)
    }

    kwargs = {"capture_output": True, "text": True, "timeout": AGENT_TIMEOUT + 30, "env": env}
    if backend == "dsh":
        kwargs["cwd"] = str(DSH_CWD)
    t0 = time.perf_counter()
    try:
        r = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        result["error"] = "agent timeout"
        result["elapsed_seconds"] = round(time.perf_counter() - t0, 2)
        return result
    result["elapsed_seconds"] = round(time.perf_counter() - t0, 2)

    if r.returncode != 0:
        result["error"] = f"agent rc={r.returncode}: {r.stderr[:300]}"
        return result

    if backend == "dsh":
        result["agent_text"] = (r.stdout or "").strip()
        dsh_session = _dsh_session_file(chat_id)
        result["tool_calls"] = _dsh_tool_calls(dsh_session)
        _apply_cost(result, _dsh_cost_from_session(dsh_session))
    else:
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            result["error"] = f"agent json parse: {e}"
            return result
        payloads = data.get("payloads", [])
        result["agent_text"] = payloads[0].get("text", "") if payloads else ""
        meta = data.get("meta", {})
        result["tool_calls"] = (meta.get("toolSummary", {}) or {}).get("calls", 0)
        result["agent_duration_ms"] = meta.get("durationMs")
        _apply_cost(result, _openclaw_cost_from_transcript(
            (meta.get("agentMeta") or {}).get("sessionFile")
        ))

    # 从审计日志提 SQL(按 -- @ds: 分组,支持多行 SQL)—— 后端无关,统一口径
    audit = HOME / "log" / f"{chat_id}.sql"
    sqls = extract_sqls(audit.read_text()) if audit.exists() else []
    result["sql_history"] = sqls
    result["final_sql"] = sqls[-1] if sqls else ""
    return result


def score_result(result, gold, ds_name):
    """执行终答 SQL 并与 gold 比对(放宽多列),回填 pass / error / extra_columns。

    放宽:候选可比 gold 多输出列(多值),只要 gold 需要的列值都对就判对;
    多出的列记入 extra_columns 备注(用列值多重集匹配,不受别名影响)。
    """
    if not result["final_sql"]:
        if result["error"] is None:
            result["error"] = "no final sql"
        return result
    gold_rows = gold["rows"]
    gold_cols = gold.get("columns", [])
    try:
        conn = _connect(ds_name)
        try:
            cand_cols, cand_rows = execute_sql_columns(conn, result["final_sql"])
            result["pass"] = results_equal_relaxed(gold_rows, cand_rows)
            # 仅在判对时记多余列(此时 gold 各列都已匹配,未匹配候选列 = 真·多余;
            # 判错时未匹配列实为「答错列」,记了反而误导)
            if result["pass"]:
                result["extra_columns"] = diff_extra_columns(
                    gold_rows, gold_cols, cand_rows, cand_cols
                )
        finally:
            conn.close()
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["pass"] = False
    return result


def load_existing(results_json):
    if results_json.exists():
        data = load_json(results_json)
        return data.get("runs", [])
    return []


# 限流特征:DSH 限流以 rc=1 退出,错误码 RATE_LIMIT 落在 stderr。
RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "ratelimit", "too many requests", "429", "throttl", "限流")


def is_rate_limited(result):
    """检测限流:openclaw 空响应(rc=0 空 payload) 或 错误信息含限流特征(DSH rc=1 退出)。"""
    err = result.get("error")
    if err is not None:
        low = err.lower()
        return any(m in low for m in RATE_LIMIT_MARKERS)
    return result.get("tool_calls", 0) == 0 and not result.get("agent_text")


def _stat(vals):
    """算术平均;空序列返回 nan。"""
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else float("nan")


def _print_cost_report(runs, levels, ex):
    """成本汇总:每档平均 token/美元/耗时/轮数 + 梯度间边际成本(每 1pp 准确率的算力代价)。"""
    print(f"\n{'=' * 60}")
    print("== 成本汇总(算力 × 成本平衡) ==")
    rows = {}
    for lvl in levels:
        lv = [r for r in runs if r["m_level"] == lvl and r.get("tokens")]
        if not lv:
            print(f"{lvl}: 无 token 数据(旧结果文件缺成本字段,需新代码重跑)")
            continue
        tok_in = _stat([r["tokens"]["input"] for r in lv])
        tok_out = _stat([r["tokens"]["output"] for r in lv])
        tok_tot = _stat([r["tokens"]["total"] for r in lv])
        cache = _stat([r["tokens"]["cache_read"] for r in lv])
        cost = _stat([r["cost_usd"] for r in lv if r.get("cost_usd") is not None])
        secs = _stat([r["elapsed_seconds"] for r in lv])
        rounds = _stat([r["tool_rounds"] for r in lv])
        rows[lvl] = {"tok_tot": tok_tot, "cost": cost, "secs": secs}
        cost_s = f"{cost:.4f}" if cost == cost else "n/a"  # NaN 检测(DSH 无美元成本)
        print(f"{lvl}: 均 token in={tok_in:,.0f} out={tok_out:,.0f} cache读={cache:,.0f} "
              f"total={tok_tot:,.0f} | 美元/题={cost_s} | 耗时={secs:.1f}s | "
              f"工具轮数={rounds:.1f} (n={len(lv)})")

    # 边际成本:每提升 1pp 准确率(相对上一档)要多付多少 token / 美元 / 秒
    if len(rows) >= 2 and "M0" in ex:
        print("\n边际成本(每 +1pp 准确率):")
        ordered = [lvl for lvl in levels if lvl in ex and lvl in rows]
        for a, b in zip(ordered, ordered[1:]):
            de = (ex[b] - ex[a]) * 100  # 百分点
            if de <= 0:
                print(f"  {a}→{b}: ΔEX={de:+.1f}pp(无正向收益,不核算)")
                continue
            dt = rows[b]["tok_tot"] - rows[a]["tok_tot"]
            dc = rows[b]["cost"] - rows[a]["cost"]
            ds = rows[b]["secs"] - rows[a]["secs"]
            dc_s = f"{dc/de:.4f}" if dc == dc else "n/a"
            print(f"  {a}→{b}: ΔEX={de:+.1f}pp | 每pp 多 {dt/de:,.0f} token | "
                  f"{dc_s} 美元 | {ds/de:.2f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="逗号分隔的题号(整数),如 1,5,99,100,116")
    ap.add_argument("--all", action="store_true", help="跑全部题(仅含 gold 可判分的题)")
    ap.add_argument("--levels", default="M0,M2", help="逗号分隔的 M 档")
    ap.add_argument("--model", default="deepseek-v4-flash")
    ap.add_argument("--backend", choices=["openclaw", "dsh"], default="openclaw",
                    help="agent 后端:openclaw(默认,保复现) 或 dsh(信创环境,DeepSeek Harness)")
    ap.add_argument("--results", default="results_wc.json")
    ap.add_argument("--sleep", type=int, default=0, help="每道题之间的间隔秒数(限流用)")
    ap.add_argument("--retry", type=int, default=0, help="空响应(疑似限流)时的重试次数")
    args = ap.parse_args()

    # DSH 后端:模型路由走 --patch 覆盖文件(整个 run 同一模型,生成一次即可)
    model_patch = None
    if args.backend == "dsh":
        DSH_CWD.mkdir(parents=True, exist_ok=True)
        model_patch = _dsh_model_patch(args.model)

    results_json = WC_DIR / args.results

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

    # 断点续跑
    existing = {(r["question_id"], r["m_level"]) for r in load_existing(results_json)}
    runs = load_existing(results_json)
    todo = [(q, lvl) for q in selected for lvl in levels if (q["id"], lvl) not in existing]

    print(f"共 {len(todo)} 次待跑({len(selected)} 题 × {len(levels)} 档),已跳过 {len(existing)} 次已完成的")

    for i, (q, lvl) in enumerate(todo, 1):
        ds = DB_BY_LEVEL[lvl]
        print(f"\n[{i}/{len(todo)}] {q['id']} ({lvl}, {ds}) ...", flush=True)
        result = None
        for attempt in range(args.retry + 1):
            result = agent_turn(q["id"], q["question"], ds, lvl, args.model, args.backend, model_patch, q.get("evidence"))
            if not is_rate_limited(result):
                break
            if attempt < args.retry:
                wait = max(args.sleep, 15) * (attempt + 1)
                print(f"    ⚠️ 空响应(疑似限流),{wait}s 后重试({attempt+1}/{args.retry})...", flush=True)
                time.sleep(wait)
        score_result(result, gold[q["id"]], ds)
        runs.append(result)
        # 逐条落盘(续跑 + 防丢)
        results_json.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2))
        status = "✅" if result["pass"] else ("❌" if result["error"] else "❌")
        tok = result.get("tokens") or {}
        cost_s = f" ${result['cost_usd']:.4f}" if result.get("cost_usd") is not None else ""
        extra = result.get("extra_columns") or []
        extra_s = f" 多列={extra}" if extra else ""
        print(f"    {status} pass={result['pass']} tok={tok.get('total', 0):,} "
              f"轮数={result.get('tool_rounds', 0)} {result.get('elapsed_seconds', 0):.0f}s"
              f"{cost_s}{extra_s} err={result['error']}")
        if args.sleep > 0:
            time.sleep(args.sleep)

    # 报告
    print(f"\n{'=' * 60}")
    print("== 报告 ==")
    ex = {}
    for lvl in levels:
        lv_runs = [r for r in runs if r["m_level"] == lvl]
        if not lv_runs:
            continue
        passed = sum(1 for r in lv_runs if r["pass"])
        ex[lvl] = passed / len(lv_runs)
        print(f"\n{lvl}: EX {passed}/{len(lv_runs)} = {ex[lvl]*100:.1f}%")
        extra = [(r["question_id"], r.get("extra_columns")) for r in lv_runs if r.get("extra_columns")]
        if extra:
            print(f"    带多余列(放宽判对但多输出): {len(extra)}/{len(lv_runs)} 题")
            for qid, cols in extra:
                print(f"      Q{qid}: 多出 {cols}")
        dom_stat = {}
        for r in lv_runs:
            d = gold[r["question_id"]]["domain"]
            dom_stat.setdefault(d, [0, 0])
            dom_stat[d][1] += 1
            if r["pass"]:
                dom_stat[d][0] += 1
        for d, (p, tot) in sorted(dom_stat.items()):
            print(f"    {d:14s} {p}/{tot}")
        fails = [r["question_id"] for r in lv_runs if not r["pass"]]
        if fails:
            print(f"    失败: {', '.join(map(str, fails))}")

    _print_cost_report(runs, levels, ex)

    if "M0" in ex:
        for lvl in ("M1", "M2"):
            if lvl in ex:
                print(f"\nΔ₄({lvl}) = EX({lvl}) - EX(M0) = {(ex[lvl]-ex['M0'])*100:+.1f} 个百分点")
        if "M1" in ex and "M2" in ex:
            num = ex["M1"] - ex["M0"]
            den = ex["M2"] - ex["M0"]
            capture = (num / den) if den else float("nan")
            print(f"收益捕获率 = Δ₄(M1)/Δ₄(M2) = {capture:.2f}")


if __name__ == "__main__":
    main()
