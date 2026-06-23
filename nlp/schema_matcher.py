"""Map query noun terms to table/column names using fuzzy string matching + synonyms."""

from __future__ import annotations

from difflib import SequenceMatcher

import spacy
from spacy.language import Language

from db.schema_index import SchemaIndex
from nlp.synonyms import SYNONYMS
from nlp.types import SchemaMatch

_FUZZY_THRESHOLD = 0.75  # SequenceMatcher.ratio() below this is ignored


class SchemaMatcher:
    """
    Maps content words in a query to table/column names via:
      1. Synonym dictionary lookup (exact, fast)
      2. Fuzzy string match against schema index terms (difflib, stdlib)

    Usage:
        matcher = SchemaMatcher(nlp, schema_index)
        matches = matcher.match("top 10 movies by IMDB rating")
    """

    def __init__(self, nlp: Language, schema_index: SchemaIndex) -> None:
        self._nlp = nlp
        self._index = schema_index
        self._terms = schema_index.all_terms()  # list of (term, table, col|None)

    def match(self, question: str) -> list[SchemaMatch]:
        doc = self._nlp(question.lower())
        candidates: dict[tuple[str, str | None], SchemaMatch] = {}

        # Extract content words + noun chunks to match against schema
        query_words = _content_words(doc)

        for word in query_words:
            # 1. Synonym lookup
            canonical = SYNONYMS.get(word)
            if canonical:
                hit = self._resolve_canonical(canonical)
                if hit:
                    _keep_best(candidates, hit)
                    continue

            # 2. Fuzzy match against every indexed term
            for term, table, col in self._terms:
                ratio = SequenceMatcher(None, word, term.lower()).ratio()
                if ratio >= _FUZZY_THRESHOLD:
                    match = SchemaMatch(table=table, column=col, confidence=ratio)
                    _keep_best(candidates, match)

        return sorted(candidates.values(), key=lambda m: m.confidence, reverse=True)

    def _resolve_canonical(self, canonical: str) -> SchemaMatch | None:
        """Find the best SchemaMatch for a synonym-resolved term.

        Exact column match beats table match; table match returns column=None
        to avoid picking a spurious column when only the table was intended.
        """
        # Exact column name match → return with that specific column
        for _, table, col in self._terms:
            if col == canonical:
                return SchemaMatch(table=table, column=col, confidence=1.0)
        # Table name match → signal the table without pinning a column
        for _, table, col in self._terms:
            if table == canonical and col is None:
                return SchemaMatch(table=table, column=None, confidence=1.0)
        return None


def _content_words(doc) -> list[str]:
    """Return lemmatized nouns, proper nouns, adjectives, and noun chunks."""
    words: list[str] = []
    for token in doc:
        if token.pos_ in {"NOUN", "PROPN", "ADJ"} and not token.is_stop:
            words.append(token.lemma_)
    for chunk in doc.noun_chunks:
        text = chunk.text.strip()
        if text:
            words.append(text)
    return list(dict.fromkeys(words))  # deduplicate, preserve order


def _keep_best(
    candidates: dict[tuple[str, str | None], SchemaMatch],
    match: SchemaMatch,
) -> None:
    key = (match.table, match.column)
    existing = candidates.get(key)
    if existing is None or match.confidence > existing.confidence:
        candidates[key] = match
