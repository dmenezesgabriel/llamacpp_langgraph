# LangGraph + llama-cpp-python + DuckDB — Data Analyst Agent

A fully local, privacy-friendly data analyst agent that combines:

| Component | Role |
|-----------|------|
| **LFM2.5-8B-A1B-Q4_K_M** (llama-cpp) | Local LLM inference (no cloud API needed) |
| **DuckDB** (in-memory) | Fast analytical SQL engine |
| **LangGraph** | Multi-node agent graph with reflection loop |
| **vega-datasets / DuckDB public data** | Open-source reference datasets |

---

## Architecture

```
User question
     │
     ▼
┌─────────────┐       intent=general_chat
│ disambiguate│──────────────────────────────┐
└──────┬──────┘                              │
       │ intent=data_query                   │
       ▼                                     │
┌─────────────────┐                          │
│ schema_inspector│  fetches schema + sample │
└──────┬──────────┘                          │
       ▼                                     │
┌──────────────┐                             │
│ query_planner│  generates DuckDB SQL       │
└──────┬───────┘                             │
       ▼                                     │
┌──────────────┐                             │
│query_executor│  runs SQL via DuckDB        │
└──────┬───────┘                             │
       ▼                                     │
┌──────────┐  ok                             │
│ reflector│─────────────────────────────────┤
└──────┬───┘                                 │
       │ retry (up to 3×)                    │
       └──► query_planner                    │
                                             ▼
                                      ┌──────────┐
                                      │ responder│  final natural-language answer
                                      └──────────┘
```

## Datasets

| Table | Source | Rows |
|-------|--------|------|
| `nyc_taxi` | [DuckDB public parquet](https://blobs.duckdb.org/data/taxi_2019_04.parquet) — 1% sample | ~74k |
| `seattle_weather` | [vega-datasets/GitHub](https://raw.githubusercontent.com/vega/vega-datasets/main/data/seattle-weather.csv) | 1,461 |
| `movies` | [vega-datasets/GitHub](https://raw.githubusercontent.com/vega/vega-datasets/main/data/movies.json) | 3,201 |
| `cars` | [vega-datasets/GitHub](https://raw.githubusercontent.com/vega/vega-datasets/main/data/cars.json) | 406 |

## DuckDB Tools

| Tool | Description |
|------|-------------|
| `list_tables` | List all registered tables |
| `get_schema` | Column names, types, nullability |
| `sample_data` | N sample rows from a table |
| `get_column_stats` | min/max/avg/distinct/null + top values |
| `run_query` | Execute a read-only SQL SELECT |
| `get_table_overview` | Row count + schema + sample in one call |

## LLM Tuning

Key llama.cpp parameters used for the **LFM2.5-8B** model:

| Parameter | Value | Reason |
|-----------|-------|--------|
| `temperature` | 0.05–0.1 | Near-deterministic for SQL/data tasks |
| `mirostat_mode` | 2 | Adaptive perplexity control → fewer hallucinations |
| `mirostat_tau` | 3.0 | Tight target perplexity for factual tasks |
| `repeat_penalty` | 1.1 | Prevents token repetition loops |
| `n_ctx` | 8192 | Fits schema + history + SQL + reflection |
| `n_batch` | 512 | Fast prompt ingestion |
| `top_p` | 0.9 | Nucleus sampling for focused output |
| `top_k` | 40 | Vocabulary restriction |

## Installation

```bash
uv sync
```

## Usage

**Demo mode** (runs 7 pre-set questions):
```bash
.venv/bin/python main.py
```

**Interactive REPL**:
```bash
.venv/bin/python main.py --interactive
```

## Example Questions

```
What datasets do you have available?
What columns are in the nyc_taxi table?
What is the average fare amount for NYC taxi trips?
What are the top 5 pickup locations by number of trips?
How many rainy days were there each year in Seattle?
Which 5 movies have the highest worldwide gross?
What is the average horsepower by number of cylinders?
```
