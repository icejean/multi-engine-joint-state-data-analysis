# REPLAY_GUIDE_formula_1.md — formula_1 (BIRD dev) Replay Guide

> Reproducing the §4.4 **formula_1** (BIRD dev F1 racing, obfuscated) SQL convergence experiment from scratch.
> Shares the same `prep_bird.py` pipeline as `financial` (see REPLAY_GUIDE_financial.md); this doc only marks the differences.
> Assets: `data/formula_1/`, `scripts/`, `analysis/root-cause/`.

---

## 0. Positioning and conventions (read first)

- **Data domain**: relational (SQL). The BIRD dev `formula_1` database (F1 racing, 13 tables).
- **Mechanism**: **M+S** (one-shot injection of schema.json + notes.md) + a single-shot baseline (B1).
- **Convergence curve**: run the same DB over multiple rounds, swapping in a new notes.md each round (accumulating from scratch).
- **Honesty boundary**: M+S goes through the real Portal execution chain, requiring the full DataAI Portal stack —
  the open-source DataAI project is at <https://github.com/icejean/dataai_with_jupyterlab_and_rstudio> (`docs/DataAI-Portal-AI数据分析平台简介.md` is the Portal introduction entry).
  single-shot calls the LLM API directly + pymysql, third-party reproducible.
- **Scoring**: `results_equal_relaxed`.

---

## 1. Data source & download

- **Source**: BIRD dev set, database `formula_1`. Download the dev set from <https://bird-bench.github.io>, giving `dev.json`, `dev_databases/formula_1/formula_1.sqlite`, `database_description/*.csv` (13 tables).
- **Included in this repo**: `dev.json` / `dev_tables.json` (BIRD original question set, input to prep_bird.py), `question_set.json` / `question_set_obfuscated.json`, `obfuscation_map.json`, `formula_1_schema.json`, `formula_1_notes.md`, `gold.json`, `gold_errors.json`, `database_description/*.csv`, `convergence_curve.json`, `results_f1_*.json`, `run_*.log`, `b1_*.log`.
- **Not included**: `formula_1.sqlite` (binary DB, download required).

---

## 2. Preprocessing (obfuscation / renaming)

```bash
python3 scripts/prep_bird.py formula_1
#   → data/formula_1/{question_set.json, obfuscation_map.json, formula_1_schema.json}

python3 scripts/transform_gold_sql.py --questions data/formula_1/question_set.json \
    --map data/formula_1/obfuscation_map.json --out data/formula_1/question_set_obfuscated.json
```

---

## 3. Database creation & loading

```bash
python3 scripts/migrate_bird.py formula_1
```

---

## 4. Question set (174 questions)

- **Single source of truth**: `data/formula_1/question_set_obfuscated.json` (174 questions).

---

## 5. gold source / generation / fixes

```bash
python3 scripts/gen_gold_bird.py formula_1
```

- Output: `data/formula_1/gold.json` + `gold_errors.json` (cross-validation "original SQLite vs obfuscated MySQL").

---

## 6. Resource files (M+S one-shot injection)

- `data/formula_1/formula_1_schema.json` + `formula_1_notes.md`.

---

## 7. Running the benchmark

```bash
# M+S convergence curve
python3 scripts/run_bench_bird_mplus.py --db formula_1 --all \
    --results results_f1_round1.json

# single-shot baseline (B1)
python3 scripts/run_bench_bird_singleshot.py --db formula_1 --all \
    --results results_f1_ss.json

# pass^3 (same converged notes × 3 rounds; stats: average pass@1 / all-3)
python3 scripts/run_bench_bird_mplus.py --db formula_1 --all --results results_f1_pass3_run1.json
python3 scripts/run_bench_bird_mplus.py --db formula_1 --all --results results_f1_pass3_run2.json
python3 scripts/run_bench_bird_mplus.py --db formula_1 --all --results results_f1_pass3_run3.json

# convergence summary
python3 scripts/summarize_convergence.py --db formula_1 \
    --results results_f1_round1.json --round 1 --notes "empty(scratch)"
```

---

## 8. Scoring

```bash
python3 scripts/score.py --selftest
python3 scripts/statistical_analysis.py      # p2-statistical-results.md §B1
```

---

## 9. Root-cause analysis (doc index)

| Topic | Doc |
|---|---|
| BIRD dev cross-DB convergence | `analysis/root-cause/bird-dev-convergence.md` |
| Cross-model comparison | `analysis/root-cause/glm52-7q-root-cause.md`, `bird-dev-pro-vs-flash.md` |
| gold audit | `analysis/root-cause/gold-fixes-bird-dev.md` + `analysis/gold-verification.md` |
| Statistical method | `analysis/p2-statistical-results.md` (§B1) |

---

## 10. Iteration timeline (convergence process, not per-round numbers)

Same structure as financial: prep → DB build → round1 from scratch → root cause / fix notes / re-run → B1 same-DB baseline → **pass^3 (three rounds)** → closure (converge to grounding-saturated, lock hard-floor). formula_1's DB-specific notes involve F1 semantic pitfalls like lap-time `TIME_TO_SEC`. Exploration variants (result prefix): `round1-5`/`round5b` (convergence rounds), `note1-3test` (notes incremental validation), `notesfix`/`goldfix`/`driftfix`/`stablefix`/`regfix`/`q128fix` (targeted fixes), `smoke`/`smoke2` (smoke tests).

> Exact numbers are authoritative in `analysis/p2-statistical-results.md` §B1 and `convergence_curve.json`.

---

## 11. Related files

**Data (`data/formula_1/`)**: `dev.json` / `dev_tables.json`, `question_set.json`, `question_set_obfuscated.json`, `obfuscation_map.json`, `formula_1_schema.json`, `formula_1_notes.md`, `gold.json`, `gold_errors.json`, `database_description/*.csv` (13 tables), `convergence_curve.json`, `results_f1_*.json` (incl. round/note*test/fix/pass3 variants), `run_*.log`, `b1_*.log`.

**Scripts**: same as financial (`scripts/{prep_bird,transform_gold_sql,migrate_bird,gen_gold_bird,run_bench_bird_mplus,run_bench_bird_singleshot,summarize_convergence,analyze_b1_singleshot}.py` + `run_b1_singleshot.sh`).
