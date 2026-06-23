"""Extract typed entities from a query using spaCy NER + POS fallback."""

from __future__ import annotations

from typing import Any

import spacy
from spacy.language import Language

from nlp.types import Entity

# spaCy entity labels we care about
_KEPT_LABELS = {"CARDINAL", "DATE", "ORDINAL", "TIME", "GPE", "ORG", "PERSON", "NORP"}


def _load_nlp() -> Language:
    return spacy.load("en_core_web_sm")


class EntityExtractor:
    """
    Wraps spaCy to pull typed entities out of a natural-language query.

    Usage:
        extractor = EntityExtractor()
        entities = extractor.extract("top 10 movies from 2010")
    """

    def __init__(self, nlp: Language | None = None) -> None:
        self._nlp = nlp or _load_nlp()

    def extract(self, question: str) -> list[Entity]:
        doc = self._nlp(question)
        seen_spans: set[tuple[int, int]] = set()
        entities: list[Entity] = []

        for ent in doc.ents:
            if ent.label_ not in _KEPT_LABELS:
                continue
            seen_spans.add((ent.start, ent.end))
            entities.append(Entity(
                value=_coerce(ent.text, ent.label_),
                entity_type=ent.label_,
            ))

        # POS fallback: NUM tokens not already covered by a named entity
        for token in doc:
            if token.pos_ == "NUM" and not _in_any_span(token.i, seen_spans):
                entities.append(Entity(value=_coerce(token.text, "CARDINAL"), entity_type="CARDINAL"))

        return entities


def _in_any_span(idx: int, spans: set[tuple[int, int]]) -> bool:
    return any(start <= idx < end for start, end in spans)


def _coerce(text: str, label: str) -> Any:
    """Try to return a Python int or float for numeric entities; str otherwise."""
    if label in {"CARDINAL", "ORDINAL"}:
        try:
            return int(text.replace(",", ""))
        except ValueError:
            try:
                return float(text.replace(",", ""))
            except ValueError:
                pass
    return text
