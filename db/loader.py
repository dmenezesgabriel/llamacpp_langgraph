"""
DuckDB in-memory database loader.

Downloads datasets once to data/ (via db/downloader.py) then loads them
from local files — no DuckDB httpfs extension required.

Datasets:
  - nyc_taxi       : NYC Yellow Taxi trips April 2019 (1 % sample ≈ 74 k rows)
  - seattle_weather : Seattle daily weather 2012-2015 (vega-datasets)
  - movies          : IMDB-style movie ratings (vega-datasets)
  - cars            : Classic cars dataset (vega-datasets)
"""

from __future__ import annotations

import duckdb

from db.downloader import ensure_downloaded

# Shared singleton connection (in-memory)
_conn: duckdb.DuckDBPyConnection | None = None


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return the shared in-memory DuckDB connection, initialising it on first call."""
    global _conn
    if _conn is None:
        _conn = _build_connection()
    return _conn


def _build_connection() -> duckdb.DuckDBPyConnection:
    print("📦  Downloading / verifying datasets …")
    paths = ensure_downloaded()

    conn = duckdb.connect(":memory:")
    print("📦  Loading datasets into DuckDB …")

    taxi_path = paths["nyc_taxi.parquet"]
    if taxi_path.exists():
        _load_parquet(conn, "nyc_taxi", str(taxi_path))
    else:
        _create_synthetic_nyc_taxi(conn)
    _load_csv(conn, "seattle_weather", str(paths["seattle_weather.csv"]))
    _load_json(conn, "movies", str(paths["movies.json"]))
    _load_json(conn, "cars", str(paths["cars.json"]))

    print("✅  All datasets loaded.\n")
    return conn


def _load_parquet(conn: duckdb.DuckDBPyConnection, table: str, path: str) -> None:
    print(f"   • {table} (parquet) … ", end="", flush=True)
    try:
        conn.execute(
            f"""
            CREATE TABLE {table} AS
            SELECT * FROM read_parquet('{path}')
            USING SAMPLE 1 PERCENT (bernoulli)
            """
        )
        count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # type: ignore[index]
        print(f"{count:,} rows ✓")
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED ({exc})")


def _load_csv(conn: duckdb.DuckDBPyConnection, table: str, path: str) -> None:
    print(f"   • {table} (csv) … ", end="", flush=True)
    try:
        conn.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto('{path}')")
        count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # type: ignore[index]
        print(f"{count:,} rows ✓")
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED ({exc})")


def _create_synthetic_nyc_taxi(conn: duckdb.DuckDBPyConnection, n_rows: int = 10_000) -> None:
    """Generate a realistic synthetic nyc_taxi table when the real file is unavailable."""
    print(f"   • nyc_taxi (synthetic, {n_rows:,} rows) … ", end="", flush=True)
    try:
        conn.execute(f"""
            CREATE TABLE nyc_taxi AS
            SELECT
                (1 + (random() * 2)::INTEGER)                       AS VendorID,
                TIMESTAMP '2019-04-01' + INTERVAL (random() * 2592000) SECONDS
                                                                     AS tpep_pickup_datetime,
                (1 + (random() * 4)::INTEGER)                        AS passenger_count,
                ROUND((random() * 20)::DECIMAL, 2)                   AS trip_distance,
                (1 + (random() * 262)::INTEGER)                      AS PULocationID,
                (1 + (random() * 262)::INTEGER)                      AS DOLocationID,
                ROUND((5 + random() * 40)::DECIMAL, 2)               AS fare_amount,
                ROUND((random() * 10)::DECIMAL, 2)                   AS tip_amount,
                ROUND((random() * 3)::DECIMAL, 2)                    AS tolls_amount,
                ROUND((5 + random() * 50)::DECIMAL, 2)               AS total_amount,
                (1 + (random() * 4)::INTEGER)                        AS payment_type
            FROM range({n_rows})
        """)
        print("✓")
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED ({exc})")


def _load_json(conn: duckdb.DuckDBPyConnection, table: str, path: str) -> None:
    print(f"   • {table} (json) … ", end="", flush=True)
    try:
        if table == "movies":
            conn.execute(
                f"""
                CREATE TABLE {table} AS
                SELECT CAST(Title AS VARCHAR) AS Title, * EXCLUDE (Title)
                FROM read_json_auto('{path}')
                """
            )
        else:
            conn.execute(f"CREATE TABLE {table} AS SELECT * FROM read_json_auto('{path}')")
        count = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # type: ignore[index]
        print(f"{count:,} rows ✓")
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED ({exc})")
