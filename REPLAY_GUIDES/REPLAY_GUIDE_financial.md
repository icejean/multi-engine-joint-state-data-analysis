# REPLAY_GUIDE_financial.md — financial (BIRD dev) Replay Guide

> Reproducing the §4.4 **financial** (BIRD dev Czech bank, obfuscated) SQL convergence experiment from scratch.
> Shares the same `prep_bird.py` pipeline as `formula_1` (see REPLAY_GUIDE_formula_1.md).
> Assets: `data/financial/`, `scripts/`, `analysis/root-cause/`.

---

## 0. Positioning and conventions (read first)

- **Data domain**: relational (SQL). The BIRD dev `financial` database (Czech bank, 8 tables).
- **Mechanism**: **M+S** (one-shot injection of `schema.json` + `notes.md`, agent multi-round execution feedback); against a **single-shot** baseline (the B1 experiment).
- **Convergence curve**: run the same DB over multiple rounds, swapping in a new notes.md each round (accumulating from scratch), quantifying "notes accumulation → monotonic accuracy convergence".
- **Honesty boundary**: M+S goes through the real Portal execution chain (openclaw → MCP → dataai-sql kernel), so reproducing it requires deploying the full DataAI Portal stack —
  the open-source DataAI project is at <https://github.com/icejean/dataai_with_jupyterlab_and_rstudio> (`docs/DataAI-Portal-AI数据分析平台简介.md` is the Portal introduction entry).
  single-shot calls the LLM API directly + scores via pymysql, and is third-party reproducible.
- **Scoring**: `results_equal_relaxed` (value multiset comparison, relaxed on extra output columns).

---

## 1. Data source & download

- **Source**: BIRD dev set, database `financial`. Download the dev set from <https://bird-bench.github.io>, giving you:
  - `dev.json` (question set), `dev_databases/financial/financial.sqlite` (database), `dev_databases/financial/database_description/*.csv` (English column descriptions for 8 tables).
- **Included in this repo**: `dev.json` / `dev_tables.json` (BIRD original question set, input to prep_bird.py), `question_set.json` / `question_set_obfuscated.json`, `obfuscation_map.json`, `financial_schema.json`, `financial_notes.md`, `gold.json`, `gold_errors.json`, `database_description/*.csv`, `convergence_curve.json`, `results_fin_*.json`, `run_round*.log`, `b1_*.log`.
- **Not included**: `financial.sqlite` (binary DB, download required).

---

## 2. Preprocessing (obfuscation / renaming)

```bash
# 1) enrich + obfuscation map + schema.json (reads dev.json + financial.sqlite + database_description/*.csv)
python3 scripts/prep_bird.py financial
#   → data/financial/{question_set.json, obfuscation_map.json, financial_schema.json}

# 2) gold SQL rewrite (original-name SQLite dialect → obfuscated-name MySQL dialect)
python3 scripts/transform_gold_sql.py --questions data/financial/question_set.json \
    --map data/financial/obfuscation_map.json --out data/financial/question_set_obfuscated.json
```

> Obfuscation rules: table-name abbreviation + non-FK column de-vowel/truncate-4 + FK column → `ref1/ref2` (same rules as works_cycles).

---

## 3. Database creation & loading

```bash
# SQLite → MySQL (obfuscated names, single DB, no sys_* metadata tables — schema comes from the injected schema.json)
python3 scripts/migrate_bird.py financial
```

- Credentials: repo-root `.env` (falling back to `/opt/dataai/templates/.env`).

---

## 4. Question set (106 questions)

- **Single source of truth**: `data/financial/question_set_obfuscated.json` (106 questions, with `id/question_id/question/evidence/SQL_obfuscated`).

---

## 5. gold source / generation / fixes

```bash
# Execute the obfuscated SQL → gold.json, and cross-validate "original SQLite vs obfuscated MySQL" for consistency
python3 scripts/gen_gold_bird.py financial
```

- Output: `data/financial/gold.json` + `data/financial/gold_errors.json` (dropped: original-SQL execution failure / degenerate gold / cross-validation mismatch).
- **gold fixes**: see `analysis/root-cause/gold-fixes-bird-dev.md`, `analysis/gold-verification.md`.

---

## 6. Resource files (M+S one-shot injection)

- `data/financial/financial_schema.json` (produced by prep_bird.py; obfuscated names + English descriptions + foreign keys).
- `data/financial/financial_notes.md` (iteratively accumulated notes, see §10 convergence).

---

## 7. Running the benchmark

```bash
# M+S convergence curve (swap in a new notes.md each round)
python3 scripts/run_bench_bird_mplus.py --db financial --all \
    --results results_fin_round1.json       # round 1 (notes from scratch)
# ...accumulate notes round by round, then re-run round2/round3...

# single-shot baseline (B1, same-DB control; --with-notes optional)
python3 scripts/run_bench_bird_singleshot.py --db financial --all \
    --results results_fin_ss.json
python3 scripts/run_bench_bird_singleshot.py --db financial --all --with-notes \
    --results results_fin_ss_notes.json

# pass^3 (same converged notes × 3 rounds, quantifying model drift; stats: average pass@1 / all-3)
python3 scripts/run_bench_bird_mplus.py --db financial --all --results results_fin_pass3_run1.json
python3 scripts/run_bench_bird_mplus.py --db financial --all --results results_fin_pass3_run2.json
python3 scripts/run_bench_bird_mplus.py --db financial --all --results results_fin_pass3_run3.json

# convergence summary (append one entry per round to convergence_curve.json)
python3 scripts/summarize_convergence.py --db financial \
    --results results_fin_round1.json --round 1 --notes "empty(scratch)"
```

- **B1 same-DB baseline**: `scripts/run_b1_singleshot.sh` (serial s1/s1n in background, logs to `data/financial/b1_*.log`); analysis via `scripts/analyze_b1_singleshot.py`.
- **Checkpoint/resume**: results are written per question; already-run questions are auto-skipped.
- **Exploration variants** (result-file prefix = process): `round1-4` (convergence rounds), `notes`/`notes2-4` (4 notes versions × 3 rounds each), `note2test`/`note11` (notes incremental validation), `fix2/3`/`evfix`/`goldfix`/`promptfix` (targeted fixes), `temp0` (temperature=0 stability), `hard` (hard-floor analysis), `glm52_*` (cross-model), `q13q61` etc. (single-question retries), `full106` (full 106 questions).

---

## 8. Scoring

```bash
python3 scripts/score.py --selftest          # self-check
python3 scripts/statistical_analysis.py      # McNemar + bootstrap CI (p2-statistical-results.md §B1)
```

---

## 9. Root-cause analysis (doc index)

| Topic | Doc |
|---|---|
| BIRD dev cross-DB convergence | `analysis/root-cause/bird-dev-convergence.md` |
| Cross-model comparison | `analysis/root-cause/glm52-7q-root-cause.md`, `bird-dev-pro-vs-flash.md` |
| gold audit | `analysis/root-cause/gold-fixes-bird-dev.md` + `analysis/gold-verification.md` |
| Statistical method | `analysis/p2-statistical-results.md` (§B1 same-DB single-shot baseline) |

---

## 10. Iteration timeline (convergence process, not per-round numbers)

1. **prep + DB build**: `prep_bird.py` obfuscation → `migrate_bird.py` build the MySQL DB.
2. **round1 (from scratch)**: inject only schema.json, no notes; run M+S to get the lower bound.
3. **root cause → fix notes → re-run**: per-round root-cause on failures, distilling "semantic ambiguity" into notes rules, then re-run — this is the body of the convergence curve.
4. **B1 same-DB baseline**: run single-shot (s1 without notes / s1n with notes), giving the same-DB "M+S leads single-shot" control.
5. **pass^3**: same converged notes × 3 rounds, giving the two conventions "average pass@1" and "all-3" (the latter stricter).
6. **Closure**: accuracy converges to the final grounding-saturated value; drift root causes and hard-floor questions are locked.

> Exact numbers are authoritative in `analysis/p2-statistical-results.md` §B1 and `convergence_curve.json`.

---

## 11. Related files

**Data (`data/financial/`)**: `dev.json` / `dev_tables.json`, `question_set.json`, `question_set_obfuscated.json`, `obfuscation_map.json`, `financial_schema.json`, `financial_notes.md`, `gold.json`, `gold_errors.json`, `database_description/*.csv` (8 tables), `convergence_curve.json`, `results_fin_*.json` (incl. round/notes/fix/temp0/hard/glm52/pass3 variants), `run_round*.log`, `b1_*.log`.

**Scripts**: `scripts/{prep_bird,transform_gold_sql,migrate_bird,gen_gold_bird,run_bench_bird_mplus,run_bench_bird_singleshot,summarize_convergence,analyze_b1_singleshot,score,statistical_analysis}.py` + `scripts/run_b1_singleshot.sh`.
