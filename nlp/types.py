"""Domain types for the NLP analysis pipeline. No external dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Intent(str, Enum):
    AGGREGATE = "aggregate"  # sum, count, average
    RANK = "rank"            # top-N, best, worst
    FILTER = "filter"        # rows matching a condition
    TREND = "trend"          # over time, by period
    COMPARE = "compare"      # group-by comparison
    UNKNOWN = "unknown"      # couldn't classify


@dataclass
class Entity:
    """A detected value extracted from the query (number, date, string literal)."""
    value: Any
    entity_type: str  # CARDINAL, DATE, ORDINAL, GPE, ORG, LITERAL


@dataclass
class SchemaMatch:
    """A query term mapped to a table and optional column."""
    table: str
    column: str | None
    confidence: float  # 0.0–1.0


@dataclass
class QueryAnalysis:
    """Full output of the classical NLP stage."""
    intent: Intent
    intent_confidence: float          # 0.0–1.0
    question: str = ""                # original query, used by templates for keyword detection
    entities: list[Entity] = field(default_factory=list)
    schema_matches: list[SchemaMatch] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        """Combined routing confidence: min of intent and schema signal."""
        if not self.schema_matches:
            return 0.0
        schema_conf = max(m.confidence for m in self.schema_matches)
        return min(self.intent_confidence, schema_conf)

    @property
    def primary_table(self) -> str | None:
        """Best-matched table: highest confidence; ties broken by most schema_matches for that table."""
        if not self.schema_matches:
            return None
        max_conf = max(m.confidence for m in self.schema_matches)
        top = [m for m in self.schema_matches if m.confidence == max_conf]
        if len(top) == 1:
            return top[0].table
        # tie-break: pick the table with the most schema_match entries
        from collections import Counter
        counts = Counter(m.table for m in self.schema_matches)
        return max(top, key=lambda m: counts[m.table]).table

    @property
    def primary_column(self) -> str | None:
        """Best-matched column with a non-None column field."""
        cols = [m for m in self.schema_matches if m.column is not None]
        if not cols:
            return None
        return max(cols, key=lambda m: m.confidence).column
