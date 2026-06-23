"""Build a searchable index of table/column names from the live DuckDB connection."""

from __future__ import annotations

from dataclasses import dataclass

from db.tools import get_schema, list_tables, get_column_stats
from db.loader import get_connection


@dataclass
class ColumnInfo:
    name: str
    dtype: str
    sample_values: list[str]  # top categorical values; empty for high-cardinality/numeric cols


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo]

    def all_terms(self) -> list[str]:
        """All searchable strings for this table: its name + all column names."""
        terms = [self.name]
        terms.extend(c.name for c in self.columns)
        return terms


class SchemaIndex:
    """
    Eagerly built at startup; never queries the DB again after __init__.

    Usage:
        idx = SchemaIndex.build()
        print(idx.tables)
        print(idx.all_terms())
    """

    def __init__(self, tables: dict[str, TableInfo]) -> None:
        self._tables = tables

    @classmethod
    def build(cls) -> "SchemaIndex":
        """Build the index from the live DuckDB connection."""
        conn = get_connection()
        table_names = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        tables: dict[str, TableInfo] = {}
        for tname in table_names:
            cols = _build_columns(conn, tname)
            tables[tname] = TableInfo(name=tname, columns=cols)
        return cls(tables)

    @property
    def tables(self) -> list[str]:
        return list(self._tables.keys())

    def get_table(self, name: str) -> TableInfo | None:
        return self._tables.get(name)

    # SQL aggregation keywords — must not be indexed as schema terms (they appear
    # in column names like "passenger_count" but are query operators, not subjects).
    _TERM_STOPWORDS = frozenset(
        {"count", "sum", "avg", "min", "max", "total", "mean", "median", "amount"}
    )

    def all_terms(self) -> list[tuple[str, str, str | None]]:
        """Return (term, table, column_or_none) triples for fuzzy matching."""
        result: list[tuple[str, str, str | None]] = []
        for tname, tinfo in self._tables.items():
            result.append((tname, tname, None))
            for col in tinfo.columns:
                result.append((col.name, tname, col.name))
                # Index individual words from multi-word column names (skip stopwords)
                parts = col.name.replace("_", " ").split()
                if len(parts) > 1:
                    for part in parts:
                        if len(part) > 2 and part.lower() not in self._TERM_STOPWORDS:
                            result.append((part, tname, col.name))
        return result

    def schema_snippet(self, table: str) -> str:
        """Compact schema string for LLM prompts with double-quoted column names."""
        tinfo = self._tables.get(table)
        if not tinfo:
            return f"{table}(unknown)"
        cols = ", ".join(f'"{c.name}" {c.dtype}' for c in tinfo.columns)
        return f"{table}({cols})"


def _build_columns(conn, table_name: str) -> list[ColumnInfo]:
    rows = conn.execute(f"DESCRIBE {table_name}").fetchall()
    columns: list[ColumnInfo] = []
    for col_name, col_type, *_ in rows:
        sample_values = _sample_categorical(conn, table_name, col_name, col_type)
        columns.append(ColumnInfo(name=col_name, dtype=col_type, sample_values=sample_values))
    return columns


def _sample_categorical(conn, table: str, col: str, dtype: str) -> list[str]:
    """Return top 5 values only for low-cardinality non-numeric columns."""
    numeric_markers = {"INTEGER", "BIGINT", "FLOAT", "DOUBLE", "DECIMAL", "TINYINT", "SMALLINT"}
    if any(m in dtype.upper() for m in numeric_markers):
        return []
    qcol = f'"{col}"'  # always quote — handles column names with spaces or capitals
    try:
        distinct = conn.execute(
            f"SELECT approx_count_distinct({qcol}) FROM {table}"
        ).fetchone()[0]
        if distinct > 30:
            return []
        rows = conn.execute(
            f"SELECT CAST({qcol} AS VARCHAR) FROM {table} GROUP BY {qcol} "
            f"ORDER BY count(*) DESC LIMIT 5"
        ).fetchall()
        return [str(r[0]) for r in rows if r[0] is not None]
    except Exception:  # noqa: BLE001
        return []
