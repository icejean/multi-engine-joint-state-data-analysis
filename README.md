# Multi-engine Joint State Data Analysis

Experimental resources for the paper **"AI Data Analysis: A New Approach — Multi-engine Joint State Data Analysis"**.

This repository holds the benchmarks, resource files, scripts, and results that substantiate the paper's claims across four engines — SQL (BIRD), Cypher (CypherBench), and ML in Python and R (TabReD) — under the **M+S deterministic grounding method** (`schema.json` + `notes.md`, one-shot injection replacing per-table exploration).

## Paper

- **Title**: AI Data Analysis: A New Approach — Multi-engine Joint State Data Analysis
- **arXiv**: *(pending)*
- **PDF**: [`paper/paper.pdf`](paper/paper.pdf)
- **LaTeX source**: [`paper/paper.tex`](paper/paper.tex), [`paper/refs.bib`](paper/refs.bib)

## Repository layout

```
paper/      Paper source (LaTeX + bibliography) and compiled PDF
analysis/   Process documents: methodology, experiment reports, root-cause analyses
scripts/    Reproducibility scripts (gold generation, evaluation, grounding, benchmarks)
data/       Resource files (schema.json + notes.md), gold, and results per benchmark
```

## Headline results

| Direction | Benchmark | Result |
|---|---|---|
| SQL (three databases) | BIRD dev | AdventureWorks 97.6%, financial 95.3%, formula_1 97.1% (single-shot ceiling) |
| Cypher (single graph) | CypherBench movie | 96.5% execution accuracy, all-3 94.0% |
| ML (Python) | TabReD weather | RMSE 1.5450 / R² 0.8408 (default params, ten-million scale) |
| ML (R) | TabReD weather | rtorch MLP 1.5419°C, float32 GBDT 1.5449 |

## Reproducing the results

### SQL — BIRD dev (`works_cycles`, `financial`, `formula_1`)

1. Download the BIRD dev databases (see *Data* below).
2. Generate the resource files and gold:
   - `scripts/gen_schema_resource.py` — packs the data dictionary into `{db}_schema.json`
   - `scripts/gen_gold_bird.py` / `gen_gold_wc.py` — verifies gold per question (35+ gold errors fixed)
3. Run the benchmark (S / M / M+S modes):
   - `scripts/run_bench_wc_singleshot.py` (S axis)
   - `scripts/run_bench_wc_mplus.py` (M / M+S axis)
4. Score: `scripts/score.py`, `scripts/rescore_wc.py`

### Cypher — CypherBench movie

1. Download the CypherBench movie subgraph.
2. `scripts/import_movie.py`, `scripts/gen_schema_movie.py`, `scripts/gen_gold_movie.py`
3. `scripts/run_bench_movie.py`, `scripts/score_cypher.py`

### ML — TabReD weather (Python and R)

- Python (official pipeline, default params): `scripts/spike_tabred_weather_full.py`
- R (GPU MLP): `scripts/spike_tabred_weather_torch_10pct.R`
- R (float32 GBDT direct channel): `scripts/gbdt_float.cpp` + `scripts/run_gbdt_float_full.R`

## Data

Raw benchmark data is **not** included (large binaries). Download from the official sources:

- **BIRD**: https://bird-bench.github.io
- **CypherBench**: https://github.com/megagonlabs/cypherbench (dataset: https://huggingface.co/datasets/megagonlabs/cypherbench)
- **TabReD**: https://github.com/yandex-research/tabred (`uvx tabred download`, requires a Kaggle account)
- **Airport routes** (Neo4j graph-examples demo data — 8,627 airports / 73,954 routes; the §5.1 single-graph graph-algorithm demo filters this to domestic (China) routes and relabels them as an invoice-issuing network): https://github.com/neo4j-graph-examples/airport-routes (load `data/neo4j.dump`; requires Neo4j 4.4 + GDS plugin)

After downloading, place the data under `data/` following the layout in the resource files.

## Data governance

Private / internally-deployed data used for **qualitative** validation — `newbc-ri` (production R&D management DB), `kg-main` (knowledge graph), and Shanghai housing prices — is **not** publicly available and is therefore excluded from this repository. Their quantitative evidence is left to future work (see the paper §5.1, §7.2).

## Citation

If you use this work, please cite the paper (arXiv ID to be added once published).

## License

[MIT](LICENSE) — the resource files, scripts, and documents in this repository are free to use, modify, and redistribute with attribution.
