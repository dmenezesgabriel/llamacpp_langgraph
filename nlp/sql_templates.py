"""
SQL template objects: one per Intent.  Each implements build(analysis) → str.
Raises TemplateBuildError when the analysis is too incomplete to generate SQL.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from nlp.types import Entity, Intent, QueryAnalysis, SchemaMatch


class TemplateBuildError(ValueError):
    """Raised when a template cannot produce valid SQL from the given analysis."""


class SQLTemplate(ABC):
    @abstractmethod
    def build(self, analysis: QueryAnalysis) -> str: ...


# ---------------------------------------------------------------------------
# RANK: SELECT * FROM table ORDER BY col [DESC] LIMIT n
# ---------------------------------------------------------------------------


class RankTemplate(SQLTemplate):
    def build(self, analysis: QueryAnalysis) -> str:
        table = _require_table(analysis)
        col = _require_column(analysis)
        n = _cardinal(analysis.entities) or 10
        direction = _rank_direction(analysis)
        label_col = _LABEL_COLS.get(table)
        if label_col and label_col != col:
            return f'SELECT "{label_col}", "{col}" FROM {table} ORDER BY "{col}" {direction} LIMIT {n}'
        return f'SELECT * FROM {table} ORDER BY "{col}" {direction} LIMIT {n}'


# ---------------------------------------------------------------------------
# AGGREGATE: SELECT agg_fn(col) FROM table [WHERE filters]
# ---------------------------------------------------------------------------


class AggregateTemplate(SQLTemplate):
    def build(self, analysis: QueryAnalysis) -> str:
        table = _require_table(analysis)
        col_matches = [m for m in analysis.schema_matches if m.column is not None]

        # Detect potential GROUP BY: a categorical column different from value column
        group_col = _find_group_column(analysis)
        value_col = _find_value_column(analysis)
        agg_fn = _aggregate_fn(analysis)

        if group_col and value_col and group_col != value_col:
            return (
                f'SELECT "{group_col}", {agg_fn}("{value_col}") '
                f'FROM {table} '
                f'GROUP BY "{group_col}" '
                f'ORDER BY {agg_fn}("{value_col}") DESC'
            )

        if value_col:
            where = _date_filter(analysis, table)
            where_clause = f" WHERE {where}" if where else ""
            return f'SELECT {agg_fn}("{value_col}") FROM {table}{where_clause}'

        # COUNT(*) fallback when no specific column
        where = _date_filter(analysis, table)
        where_clause = f" WHERE {where}" if where else ""
        if group_col:
            return (
                f'SELECT "{group_col}", COUNT(*) '
                f'FROM {table} '
                f'GROUP BY "{group_col}" '
                f'ORDER BY COUNT(*) DESC'
            )
        return f"SELECT COUNT(*) FROM {table}{where_clause}"


# ---------------------------------------------------------------------------
# FILTER: SELECT * FROM table WHERE col op value [LIMIT 20]
# ---------------------------------------------------------------------------


class FilterTemplate(SQLTemplate):
    def build(self, analysis: QueryAnalysis) -> str:
        table = _require_table(analysis)
        col = _require_column(analysis)
        num = _cardinal(analysis.entities)
        if num is not None:
            return f'SELECT * FROM {table} WHERE "{col}" > {num} LIMIT 20'
        cat = _string_entity(analysis.entities)
        if cat:
            return f"SELECT * FROM {table} WHERE \"{col}\" = '{cat}' LIMIT 20"
        raise TemplateBuildError(
            f"FilterTemplate needs a numeric or string entity; got {analysis.entities!r}"
        )


# ---------------------------------------------------------------------------
# TREND: SELECT time_col, agg(val_col) FROM table GROUP BY 1 ORDER BY 1
# ---------------------------------------------------------------------------


class TrendTemplate(SQLTemplate):
    def build(self, analysis: QueryAnalysis) -> str:
        table = _require_table(analysis)
        time_col = _find_time_column(analysis)
        if not time_col:
            raise TemplateBuildError(
                f"TrendTemplate needs a time/date column; schema matches: {analysis.schema_matches!r}"
            )
        value_col = _find_value_column(analysis)
        agg_fn = _aggregate_fn(analysis)
        if value_col:
            return (
                f'SELECT "{time_col}", {agg_fn}("{value_col}") '
                f'FROM {table} '
                f'GROUP BY "{time_col}" '
                f'ORDER BY "{time_col}"'
            )
        return (
            f'SELECT "{time_col}", COUNT(*) '
            f'FROM {table} '
            f'GROUP BY "{time_col}" '
            f'ORDER BY "{time_col}"'
        )


# ---------------------------------------------------------------------------
# COMPARE: SELECT group_col, agg(val_col) FROM table GROUP BY group_col
# ---------------------------------------------------------------------------


class CompareTemplate(SQLTemplate):
    def build(self, analysis: QueryAnalysis) -> str:
        table = _require_table(analysis)
        group_col = _find_group_column(analysis)
        if not group_col:
            raise TemplateBuildError(
                f"CompareTemplate needs a categorical column; schema matches: {analysis.schema_matches!r}"
            )
        value_col = _find_value_column(analysis)
        agg_fn = _aggregate_fn(analysis)
        if value_col and value_col != group_col:
            return (
                f'SELECT "{group_col}", {agg_fn}("{value_col}") '
                f'FROM {table} '
                f'GROUP BY "{group_col}" '
                f'ORDER BY {agg_fn}("{value_col}") DESC'
            )
        return (
            f'SELECT "{group_col}", COUNT(*) '
            f'FROM {table} '
            f'GROUP BY "{group_col}" '
            f'ORDER BY COUNT(*) DESC'
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_LABEL_COLS: dict[str, str] = {
    "movies": "Title",
    "cars": "Name",
    "nyc_taxi": "tpep_pickup_datetime",
    "seattle_weather": "date",
}

TEMPLATES: dict[Intent, SQLTemplate] = {
    Intent.RANK: RankTemplate(),
    Intent.AGGREGATE: AggregateTemplate(),
    Intent.FILTER: FilterTemplate(),
    Intent.TREND: TrendTemplate(),
    Intent.COMPARE: CompareTemplate(),
}


def build_sql(analysis: QueryAnalysis) -> str:
    """Build SQL from analysis, or raise TemplateBuildError if not possible."""
    template = TEMPLATES.get(analysis.intent)
    if template is None:
        raise TemplateBuildError(f"No template for intent {analysis.intent!r}")
    return template.build(analysis)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_table(analysis: QueryAnalysis) -> str:
    t = analysis.primary_table
    if not t:
        raise TemplateBuildError("No table identified in schema matches")
    return t


def _require_column(analysis: QueryAnalysis) -> str:
    c = analysis.primary_column
    if not c:
        raise TemplateBuildError("No column identified in schema matches")
    return c


def _cardinal(entities: list[Entity]) -> int | float | None:
    for e in entities:
        if e.entity_type in {"CARDINAL", "ORDINAL"} and isinstance(e.value, (int, float)):
            return e.value
    return None


def _string_entity(entities: list[Entity]) -> str | None:
    for e in entities:
        if e.entity_type in {"GPE", "ORG", "PERSON", "NORP", "LITERAL"} and isinstance(e.value, str):
            return e.value
    return None


_AGG_MAP: list[tuple[set[str], str]] = [
    ({"total", "sum"},                    "SUM"),
    ({"count", "how many", "how much"},   "COUNT"),
    ({"max", "maximum", "highest"},       "MAX"),
    ({"min", "minimum", "lowest"},        "MIN"),
    ({"average", "avg", "mean", "median"},"AVG"),
]

_ASC_KEYWORDS = {"lowest", "cheapest", "worst", "least", "minimum", "slowest", "shortest"}
_DESC_KEYWORDS = {"highest", "most", "best", "top", "largest", "fastest", "popular", "expensive"}


def _aggregate_fn(analysis: QueryAnalysis) -> str:
    """Detect aggregation function from keywords in the original question."""
    q = analysis.question.lower()
    for keywords, fn in _AGG_MAP:
        if any(kw in q for kw in keywords):
            return fn
    return "AVG"


def _rank_direction(analysis: QueryAnalysis) -> str:
    """Return DESC by default; ASC only for explicit 'lowest/cheapest/worst' queries."""
    q = analysis.question.lower()
    if any(kw in q for kw in _ASC_KEYWORDS):
        return "ASC"
    return "DESC"


def _date_filter(analysis: QueryAnalysis, table: str) -> str | None:
    date_ents = [e for e in analysis.entities if e.entity_type == "DATE"]
    if not date_ents:
        return None
    # Simple date filtering: only handles YYYY or "Month YYYY" formats
    val = str(date_ents[0].value)
    if val.isdigit() and len(val) == 4:
        time_col = _guess_time_col(table)
        if time_col:
            return f"YEAR(\"{time_col}\") = {val}"
    return None


def _guess_time_col(table: str) -> str | None:
    """Map known table names to their datetime column."""
    _TIME_COLS = {
        "nyc_taxi": "tpep_pickup_datetime",
        "seattle_weather": "date",
        "movies": "Release Date",
    }
    return _TIME_COLS.get(table)


def _find_time_column(analysis: QueryAnalysis) -> str | None:
    """Return the first datetime/date column in schema matches for primary table."""
    table = analysis.primary_table
    return _guess_time_col(table) if table else None


_TIME_COLS = {"date", "tpep_pickup_datetime", "tpep_dropoff_datetime", "Release Date"}
_CATEGORICAL_COLS = {
    "payment_type", "VendorID", "weather", "Origin",
    "Major Genre", "Source", "MPAA Rating", "Creative Type",
    "store_and_fwd_flag", "Distributor", "Director",
}


def _find_value_column(analysis: QueryAnalysis) -> str | None:
    """Return the best value column from schema matches, scoped to the primary table."""
    table = analysis.primary_table
    candidates = [
        m for m in analysis.schema_matches
        if m.column
        and m.column not in _TIME_COLS
        and m.column not in _CATEGORICAL_COLS
        and (table is None or m.table == table)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.confidence).column


def _find_group_column(analysis: QueryAnalysis) -> str | None:
    """Return a low-cardinality categorical column for GROUP BY, scoped to primary table."""
    table = analysis.primary_table
    for m in analysis.schema_matches:
        if (
            m.column
            and m.column in _CATEGORICAL_COLS
            and (table is None or m.table == table)
        ):
            return m.column
    return None
