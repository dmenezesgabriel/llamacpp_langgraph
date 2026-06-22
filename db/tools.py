"""DuckDB tool functions exposed to the LangGraph agent."""

from __future__ import annotations

import json
import textwrap
from typing import Any

import duckdb

from db.loader import get_connection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _conn() -> duckdb.DuckDBPyConnection:
    return get_connection()


def _rows_to_str(rows: list[tuple[Any, ...]], columns: list[str], max_rows: int = 10) -> str:
    """Pretty-format rows + column headers as a plain-text table."""
    if not rows:
        return "(no rows returned)"
    truncated = rows[:max_rows]
    col_widths = [len(c) for c in columns]
    for row in truncated:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))

    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    header = "| " + " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(columns)) + " |"

    lines = [sep, header, sep]
    for row in truncated:
        lines.append("| " + " | ".join(str(v).ljust(col_widths[i]) for i, v in enumerate(row)) + " |")
    lines.append(sep)
    if len(rows) > max_rows:
        lines.append(f"… ({len(rows) - max_rows} more rows not shown)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 1 – list_tables
# ---------------------------------------------------------------------------


def list_tables() -> str:
    """Return the names of all tables registered in the in-memory DuckDB."""
    rows = _conn().execute("SHOW TABLES").fetchall()
    names = [r[0] for r in rows]
    return f"Available tables: {', '.join(names)}" if names else "No tables found."


# ---------------------------------------------------------------------------
# Tool 2 – get_schema
# ---------------------------------------------------------------------------


def get_schema(table_name: str) -> str:
    """
    Return column names, data types, and nullability for *table_name*.

    Args:
        table_name: Name of the table to inspect.
    """
    try:
        rows = _conn().execute(f"DESCRIBE {table_name}").fetchall()
    except Exception as exc:  # noqa: BLE001
        return f"Error describing table '{table_name}': {exc}"

    lines = [f"Schema for table '{table_name}':", ""]
    lines.append(f"{'Column':<35} {'Type':<20} {'Nullable'}")
    lines.append("-" * 65)
    for col_name, col_type, nullable, *_ in rows:
        lines.append(f"{col_name:<35} {col_type:<20} {nullable or 'YES'}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool 3 – sample_data
# ---------------------------------------------------------------------------


def sample_data(table_name: str, n: int = 5) -> str:
    """
    Return *n* sample rows from *table_name*.

    Args:
        table_name: Name of the table.
        n: Number of sample rows to return (default 5, max 20).
    """
    n = min(max(1, n), 20)
    try:
        rel = _conn().execute(f"SELECT * FROM {table_name} LIMIT {n}")
        columns = [desc[0] for desc in rel.description]
        rows = rel.fetchall()
    except Exception as exc:  # noqa: BLE001
        return f"Error sampling '{table_name}': {exc}"

    return f"Sample ({n} rows) from '{table_name}':\n\n" + _rows_to_str(rows, columns, max_rows=n)


# ---------------------------------------------------------------------------
# Tool 4 – get_column_stats
# ---------------------------------------------------------------------------


def get_column_stats(table_name: str, column_name: str) -> str:
    """
    Return summary statistics for a single column (min, max, avg, distinct count, null count).

    Args:
        table_name: Name of the table.
        column_name: Name of the column.
    """
    try:
        # First detect the column type
        desc = _conn().execute(f"DESCRIBE {table_name}").fetchall()
        col_type: str | None = None
        for row in desc:
            if row[0].lower() == column_name.lower():
                col_type = row[1].upper()
                break
        if col_type is None:
            return f"Column '{column_name}' not found in table '{table_name}'."

        numeric_types = {"INTEGER", "BIGINT", "TINYINT", "SMALLINT", "FLOAT", "DOUBLE", "DECIMAL"}
        is_numeric = any(t in col_type for t in numeric_types)

        null_cnt = _conn().execute(
            f"SELECT count(*) FROM {table_name} WHERE {column_name} IS NULL"
        ).fetchone()[0]  # type: ignore[index]

        distinct_cnt = _conn().execute(
            f"SELECT approx_count_distinct({column_name}) FROM {table_name}"
        ).fetchone()[0]  # type: ignore[index]

        total = _conn().execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]  # type: ignore[index]

        lines = [
            f"Column stats: {table_name}.{column_name} ({col_type})",
            f"  Total rows   : {total:,}",
            f"  Null count   : {null_cnt:,}",
            f"  Distinct (~) : {distinct_cnt:,}",
        ]

        if is_numeric:
            stats = _conn().execute(
                f"SELECT min({column_name}), max({column_name}), avg({column_name}), "
                f"percentile_cont(0.5) WITHIN GROUP (ORDER BY {column_name}) "
                f"FROM {table_name}"
            ).fetchone()
            if stats:
                mn, mx, avg, median = stats
                lines += [
                    f"  Min          : {mn}",
                    f"  Max          : {mx}",
                    f"  Average      : {avg:.4f}" if avg is not None else "  Average      : NULL",
                    f"  Median       : {median}",
                ]
        else:
            top = _conn().execute(
                f"SELECT {column_name}, count(*) AS cnt FROM {table_name} "
                f"GROUP BY {column_name} ORDER BY cnt DESC LIMIT 5"
            ).fetchall()
            lines.append("  Top 5 values :")
            for val, cnt in top:
                lines.append(f"    {str(val):<30} ({cnt:,})")

        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"Error computing stats for '{table_name}.{column_name}': {exc}"


# ---------------------------------------------------------------------------
# Tool 5 – run_query
# ---------------------------------------------------------------------------


def run_query(sql: str, max_rows: int = 20) -> str:
    """
    Execute an arbitrary *read-only* SQL query against the in-memory DuckDB and
    return the results as a formatted table string.

    Args:
        sql: A SQL SELECT statement.
        max_rows: Maximum number of rows to return (default 20, max 50).
    """
    max_rows = min(max(1, max_rows), 50)

    # Safety: block mutations; allow read-only meta queries
    sql_stripped = sql.strip().upper()
    allowed_starts = ("SELECT", "WITH", "SHOW", "DESCRIBE")
    if not any(sql_stripped.startswith(s) for s in allowed_starts):
        return "Error: only SELECT / WITH / SHOW / DESCRIBE queries are allowed."


    try:
        rel = _conn().execute(sql)
        columns = [desc[0] for desc in rel.description]
        rows = rel.fetchall()
    except Exception as exc:  # noqa: BLE001
        return f"SQL error: {exc}"

    header = f"Query returned {len(rows)} row(s).\n\n"
    return header + _rows_to_str(rows, columns, max_rows=max_rows)


# ---------------------------------------------------------------------------
# Tool 6 – get_table_overview
# ---------------------------------------------------------------------------


def get_table_overview(table_name: str) -> str:
    """
    Return a combined overview: row count + schema + 3-row sample for *table_name*.

    Args:
        table_name: Name of the table to overview.
    """
    try:
        cnt = _conn().execute(f"SELECT count(*) FROM {table_name}").fetchone()[0]  # type: ignore[index]
    except Exception as exc:  # noqa: BLE001
        return f"Error reading table '{table_name}': {exc}"

    schema = get_schema(table_name)
    sample = sample_data(table_name, n=3)
    return f"Table '{table_name}' — {cnt:,} rows\n\n{schema}\n\n{sample}"


# ---------------------------------------------------------------------------
# Registry (used by the agent to describe available tools)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, dict] = {
    "list_tables": {
        "fn": list_tables,
        "description": "List all tables available in the in-memory DuckDB database.",
        "args": {},
    },
    "get_schema": {
        "fn": get_schema,
        "description": "Get the schema (columns, types, nullability) for a table.",
        "args": {"table_name": "str — name of the table"},
    },
    "sample_data": {
        "fn": sample_data,
        "description": "Fetch a small sample of rows from a table.",
        "args": {"table_name": "str — name of the table", "n": "int — number of rows (default 5)"},
    },
    "get_column_stats": {
        "fn": get_column_stats,
        "description": "Get min/max/avg/distinct/null statistics for a column.",
        "args": {
            "table_name": "str — name of the table",
            "column_name": "str — name of the column",
        },
    },
    "run_query": {
        "fn": run_query,
        "description": "Execute a read-only SQL SELECT query and return formatted results.",
        "args": {
            "sql": "str — SQL SELECT statement",
            "max_rows": "int — max rows to return (default 20)",
        },
    },
    "get_table_overview": {
        "fn": get_table_overview,
        "description": "Get row count + schema + sample rows for a table in one call.",
        "args": {"table_name": "str — name of the table"},
    },
}
