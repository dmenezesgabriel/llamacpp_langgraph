"""
DuckDB in-memory database loader.

Loads well-known open-source datasets from GitHub / public URLs into
an in-memory DuckDB connection at startup.

Datasets:
  - nyc_taxi      : NYC Yellow Taxi trips April 2019 (DuckDB public parquet)
  - seattle_weather: Seattle daily weather 2012-2015 (vega-datasets / GitHub)
  - movies        : IMDB-style movie ratings (vega-datasets / GitHub)
  - cars          : Classic cars dataset (vega-datasets / GitHub)
"""

from __future__ import annotations

import duckdb

# ---------------------------------------------------------------------------
# Public dataset URLs
# ---------------------------------------------------------------------------

DATASETS: dict[str, tuple[str, str]] = {
    "nyc_taxi": (
        "parquet",
        "https://blobs.duckdb.org/data/taxi_2019_04.parquet",
    ),
    "seattle_weather": (
        "csv",
        "https://raw.githubusercontent.com/vega/vega-datasets/main/data/seattle-weather.csv",
    ),
    "movies": (
        "json",
        "https://raw.githubusercontent.com/vega/vega-datasets/main/data/movies.json",
    ),
    "cars": (
        "json",
        "https://raw.githubusercontent.com/vega/vega-datasets/main/data/cars.json",
    ),
}

# Shared singleton connection (in-memory)
_conn: duckdb.DuckDBPyConnection | None = None


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return the shared in-memory DuckDB connection, initialising it on first call."""
    global _conn
    if _conn is None:
        _conn = _build_connection()
    return _conn


def _build_connection() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")

    print("📦  Loading datasets into DuckDB …")
    for table_name, (fmt, url) in DATASETS.items():
        print(f"   • {table_name} ({fmt}) … ", end="", flush=True)
        try:
            if fmt == "parquet":
                # For the large taxi dataset, materialise a representative sample
                # (1 % ≈ 74 k rows) to keep startup fast while still being useful.
                conn.execute(
                    f"""
                    CREATE TABLE {table_name} AS
                    SELECT * FROM read_parquet('{url}')
                    USING SAMPLE 1 PERCENT (bernoulli)
                    """
                )
            elif fmt == "csv":
                conn.execute(
                    f"CREATE TABLE {table_name} AS SELECT * FROM read_csv_auto('{url}')"
                )
            elif fmt == "json":
                if table_name == "movies":
                    # Title comes in as JSON-escaped string; cast to VARCHAR
                    conn.execute(
                        f"""
                        CREATE TABLE {table_name} AS
                        SELECT
                            CAST(Title AS VARCHAR) AS Title,
                            * EXCLUDE (Title)
                        FROM read_json_auto('{url}')
                        """
                    )
                else:
                    conn.execute(
                        f"CREATE TABLE {table_name} AS SELECT * FROM read_json_auto('{url}')"
                    )
            count = conn.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]  # type: ignore[index]
            print(f"{count:,} rows ✓")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED ({exc})")

    print("✅  All datasets loaded.\n")
    return conn
