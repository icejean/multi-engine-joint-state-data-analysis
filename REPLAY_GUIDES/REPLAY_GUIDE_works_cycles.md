# REPLAY_GUIDE_works_cycles.md — works_cycles (BIRD AdventureWorks) Replay Guide

> Reproducing the §4 **works_cycles** (BIRD dev AdventureWorks, obfuscated) SQL experiment from scratch:
> data acquisition → obfuscation → DB loading → question set/gold → running S / M / M+S (incl. pass^3) → scoring → root cause & iteration timeline.
> Assets: `data/works_cycles/`, `scripts/`, `analysis/root-cause/`.

---

## 0. Positioning and conventions (read first)

- **Data domain**: relational (SQL). The BIRD dev `works_cycles` database = the Microsoft AdventureWorks sample DB (65 tables).
- **Mechanism comparison**: the same 126 questions × three metadata tiers, comparing three mechanisms —
  - **S** (single-shot Text2SQL): a single LLM call, metadata pre-injected, no execution feedback.
  - **M** (agent self-iteration): multi-round tool calls + execution feedback + on-the-fly exploration of `sys_*` metadata tables.
  - **M+S** (agent + one-shot injection): replaces M's "on-the-fly exploration" with "one-shot loading of `schema.json` + `notes.md` by absolute path".
- **Honesty boundary**: M / M+S go through the real Portal execution chain (openclaw → MCP → dataai-sql kernel), so reproducing them requires deploying the full DataAI Portal stack —
  the open-source DataAI project is at <https://github.com/icejean/dataai_with_jupyterlab_and_rstudio> (the `docs/DataAI-Portal-AI数据分析平台简介.md` doc is the entry point to the Portal introduction).
  The S axis calls the LLM API directly + scores via pymysql, and is **fully reproducible by third parties**.
- **Scoring convention**: M/S scoring uses `results_equal_relaxed` (value multiset comparison, relaxed on extra output columns) so the two axes are comparable.

---

## 1. Data source & download

- **Source**: BIRD (BIg Bench) dev set, database `works_cycles` (AdventureWorks).
- **Download**: <https://bird-bench.github.io> → download the dev set, which gives you:
  - `dev.json` / `train.json` / `dev_tables.json` / `train_tables.json` (question sets + table structures)
  - `dev_databases/works_cycles/works_cycles.sqlite` (the database)
  - `dev_databases/works_cycles/database_description/*.csv` (English column descriptions for 65 tables)
- **Included in this repo** (no download needed to reproduce scoring & conclusions): `question_set_final_obfuscated.json`, `gold.json`, `obfuscation_map.json`, `descriptions.json`, `works_cycles_er_schema.json`, `works_cycles_er_notes.md`, `database_description/*.csv`, and all `results_*.json`.
- **Not included** (download required): `works_cycles.sqlite` (binary DB file), `train.json` / `dev.json` (BIRD question sets, large).

---

## 2. Preprocessing (obfuscation / renaming)

Scripts are in `data/works_cycles/` (DB-specific rules). All commands below run from the **repo root**:

```bash
cd data/works_cycles

# 1) Question selection: pick discriminative questions from BIRD train.json (≥2 JOIN preferred; 98 questions)
python3 select_questions.py --train-json <BIRD>/train.json --db-id works_cycles \
    --target 100 --out question_set_100.json

# 2) Merge official 98 + self-authored 28 → final question set (126 = 96 official + 30 self-authored)
python3 merge_question_sets.py --official question_set_100.json \
    --custom custom_questions_24.json --out question_set_final.json

# 3) Obfuscation map (table-name abbreviation + non-FK column de-vowel/truncate-4 + FK column → ref1/ref2)
python3 generate_obfuscation_map.py --sqlite works_cycles.sqlite --out obfuscation_map.json

# 4) gold SQL rewrite (original-name SQLite dialect → obfuscated-name MySQL dialect)
python3 transform_gold_sql.py --questions question_set_final.json \
    --map obfuscation_map.json --out question_set_final_obfuscated.json

# 5) Chinese descriptions (table type fact/dim/junction + field gloss)
python3 generate_descriptions.py --map obfuscation_map.json \
    --desc-dir database_description --out descriptions.json

# 6) Three-tier metadata JSON (L1 bare / L2 dictionary / L3 ER)
python3 build_metadata_gradients.py --db-dir <BIRD>/dev_databases/works_cycles --out-dir metadata
```

> The obfuscation rules align with the Sakila three-tier DBs (`actr/addr/cust` de-vowel style). `obfuscation_map.json` is an **invertible mapping** (original name ↔ abbreviated name + PK + FK), shared by DB creation, gold translation, and score trace-back.

---

## 3. Database creation & loading

```bash
# SQLite → three MySQL tiers (reads obfuscation_map.json + descriptions.json)
python3 data/works_cycles/migrate_to_mysql.py
```

- Produces three DBs (same data, metadata increasing tier by tier):
  - `works_cycles` (bare data, 65 tables, obfuscated names, no sys tables) → M0 / S0
  - `works_cycles_dict` (+ `sys_tables` / `sys_table_fields`) → M1 / S1
  - `works_cycles_er` (+ `sys_foreignkeys`) → M2 / S2
- Data cleanup: in BIRD's `works_cycles.sqlite`, the first row of `CountryRegion` is a CSV header accidentally inserted; the script already fixed it with `DELETE ... WHERE ModifiedDate='ModifiedDate'`.
- Credentials: repo-root `.env` (`MYSQLHOST/MYSQLPORT/MYSQLUSER/MYSQLPASSWORD`), falling back to `/opt/dataai/templates/.env`.

---

## 4. Question set (126 questions)

- **Single source of truth**: `data/works_cycles/question_set_final_obfuscated.json` (126 questions, with `id/question_id/question/evidence/SQL_obfuscated/source`).
- Composition: **96 official + 30 self-authored** = 126 questions (the final split per `question_set_final.json`'s `source` field; the intermediate inputs are `question_set_100.json` = 98 and `custom_questions_24.json` = 28, with 2 ill-posed official questions Q88/Q92 dropped during cleanup — see paper §4.6/§7.1).
- Self-authored questions cover scenarios BIRD doesn't (e.g. BOM `WITH` recursion, `end_dt`/`rt_chng_dt` history-table conventions).

---

## 5. gold source / generation / fixes

```bash
# gold source = the SQL_obfuscated field of question_set_final_obfuscated.json; executed against works_cycles
python3 scripts/gen_gold_wc.py
```

- Output: `data/works_cycles/gold.json` (baseline for scorable questions) + `data/works_cycles/gold_errors.json` (dropped: execution failure / degenerate gold "empty-set aggregation → NULL").
- **gold fixes** (see `analysis/root-cause/gold-fixes-bird-dev.md`, `analysis/gold-verification.md`): the final gold = **gold-v4**, fixing 3 questions (Q14/72/79 were gold bugs); "35 places" → gold-v4 fixed 3 more.

---

## 6. Resource files (M+S one-shot injection)

```bash
# Pack MySQL sys_tables/sys_table_fields/sys_foreignkeys into a data dictionary + foreign keys + column types
python3 scripts/gen_schema_resource.py works_cycles_er
```

- Produces `data/works_cycles/works_cycles_er_schema.json`.
- `data/works_cycles/works_cycles_er_notes.md`: iteratively accumulated notes (DB-specific conventions, see §10).

---

## 7. Running the benchmark (S / M / M+S / pass^3)

```bash
# S axis (single-shot, third-party reproducible; key read from ~/.openclaw / ~/.claude / ~/.dsh)
python3 scripts/run_bench_wc_singleshot.py --all --levels S0,S1,S2 \
    --model deepseek-v4-flash --base-url <DeepSeek-OpenAI-endpoint> --results results_wc_s_full.json

# M axis (agent self-iteration, requires full Portal stack; add --backend dsh for domestic-ICT environments)
python3 scripts/run_bench_wc.py --all --levels M0,M1,M2 \
    --model deepseek-v4-flash --results results_wc_m_126_full.json

# M+S axis (one-shot injection of schema.json + notes.md)
python3 scripts/run_bench_wc_mplus.py --all --levels M0,M1,M2 \
    --model deepseek-v4-flash --results results_wc_mplus_126.json

# pass^3 (each question × 3 rounds; statistics: average / all-3 / union)
bash scripts/run_mplus_pass.sh    # or run_pass.sh
```

- **pass^3 convention**: run each question 3 times, reporting average (pass@1) / all-3 correct / union (≥1 round correct), corresponding to the variance & drift analysis in §4.3.
- **Checkpoint/resume**: results are written per question; already-run `(question_id, level)` are auto-skipped.
- **S0 drift/stability experiment** (`scripts/run_s0_drift.sh`): S0 single-shot non-determinism control (drift vs temperature=0 stable), results `results_wc_s0_drift_r{1,2,3}.json` / `results_wc_s0_stab_r{1..5}.json`.
- **Cross-model** (M+S with a different model, verifying "M+S holds across models"): glm-5.2 (`scripts/run_mplus_glm52.sh` + `run_mplus_glm52_pass.sh` → `results_wc_mplus_126_glm52*.json`), glm-5.1/GLM-5-Pro (`results_wc_mplus_glm5pro_126*.json`).
- **Exploration variants** (result-file prefix = process): `pilot`/`pilot_clean` (26-question pilot), `m_26*`/`s_26*` (26-question subset), `m_tier1_verify`/`fix*`/`q*` (targeted verification/single-question retry), `mplus_126_pass4` (ceiling closure).

---

## 8. Scoring

```bash
python3 scripts/score.py --selftest          # self-check (gold itself as candidate; expect 100%)
python3 scripts/rescore_wc.py                # re-score
python3 scripts/statistical_analysis.py      # McNemar + bootstrap CI + pass@k → p2-statistical-results.md
```

- Scoring engine: `results_equal` in `scripts/score.py` (value multiset comparison, row/column order ignored, numeric tolerance 2 decimals).

---

## 9. Root-cause analysis (doc index, all under `analysis/root-cause/`)

| Topic | Doc |
|---|---|
| Convergence endpoint / round5 | `works-cycles-final-report.md`, `works-cycles-root-cause-round2.md` |
| S-axis root cause | `s-axis-root-cause-analysis.md`, `s-axis-full-root-cause.md` |
| M-axis root cause | `m-axis-root-cause-analysis.md`, `m-axis-full-root-cause.md` |
| Cross-model comparison | `mplus-126-glm52-vs-deepseek.md`, `glm52-7q-root-cause.md`, `bird-dev-pro-vs-flash.md` |
| pass^3 variance | `pass3-variance-report.md` |
| pass4 ceiling | `pass4-failure-root-cause.md` |
| Single-question root cause | `q90-root-cause-analysis.md` |
| gold audit | `gold-fixes-bird-dev.md` (+ `analysis/gold-verification.md`) |
| BIRD dev convergence (cross-DB) | `bird-dev-convergence.md` |

---

## 10. Iteration timeline (the process of reaching "closure", not per-round numbers)

The endpoint of reproduction is not any single round's number, but pushing the experiment to a **closed state** — mechanism conclusions self-consistent, ceiling locked, boundaries honest. Proceed in order:

1. **Question selection + DB build**: BIRD dev `works_cycles` — 98 selected + 28 self-authored → 126 questions; three-tier DBs `works_cycles/_dict/_er`.
2. **S axis**: run the single-shot baseline (S0/S1/S2 three metadata-pre-injection tiers), establishing the "single-shot ceiling" and the "pre-injection degrades on large schemas" boundary.
3. **M axis**: run agent self-iteration (M0/M1/M2), observing the gain of "execution feedback + metadata exploration" over S, and the rounds/cost.
4. **M+S**: run the injection mode against M — quantifying the rounds/tokens saved by "exploration → one-shot injection", and whether accuracy holds.
5. **pass^3**: each question × 3 rounds, quantifying model drift (drift-question share) and the all-3 convention.
6. **pass4 / closure**: per-question root cause → fix notes/gold → re-run, pushing accuracy to the ceiling and locking the remaining hard-floor questions (data defects that no mechanism can remove).
7. **Cross-model validation**: re-run M+S with glm-5.2, confirming "M+S holds across models".

The loop "failure root cause → fix notes/gold → re-run" is the core loop documented in the §9 root-cause docs. The final state = the SQL line's three DBs (works_cycles / financial / formula_1) lead single-shot SOTA by a clear margin.

> Exact numbers are authoritative in `analysis/p2-statistical-results.md` and the corresponding `results_*.json`.

---

## 11. Related files

**Data (`data/works_cycles/`)**: `question_set_final_obfuscated.json`, `question_set_100.json`, `custom_questions_24.json`, `obfuscation_map.json`, `descriptions.json`, `gold.json`, `gold_errors.json`, `works_cycles_er_schema.json`, `works_cycles_er_notes.md`, `database_description/*.csv` (65 tables), `metadata/works_cycles_L{1,2,3}_*.json`, `metadata/fk_diff_sqlite_vs_tablesjson.md` (FK-convention diff note), `results_wc_*.json` (incl. s0_drift/s0_stab/glm52/glm5pro/pass4 variants).

**Scripts**: `data/works_cycles/{select_questions,merge_question_sets,generate_obfuscation_map,transform_gold_sql,generate_descriptions,build_metadata_gradients,migrate_to_mysql,_rootcause2_dump}.py` + `scripts/{gen_gold_wc,gen_schema_resource,run_bench_wc,run_bench_wc_mplus,run_bench_wc_singleshot,score,rescore_wc,statistical_analysis}.py` + `scripts/run_{mplus_pass,pass,s0_drift,mplus_glm52,mplus_glm52_pass}.sh`.

**Not shipped (download required)**: `works_cycles.sqlite`, `train.json`/`train_tables.json`/`train_gold.sql`, `Customer_classic.csv` (raw / large data).

**Analysis docs**: the §9 root-cause docs + `analysis/{p2-statistical-results,pass3-variance-report,tech-route-selection,stateful-analysis-report}.md`.
