"""Classical NLP analysis pipeline: question → QueryAnalysis."""

from __future__ import annotations

import spacy
from spacy.language import Language

from db.schema_index import SchemaIndex
from nlp.entities import EntityExtractor
from nlp.intent import IntentClassifier
from nlp.schema_matcher import SchemaMatcher
from nlp.types import QueryAnalysis

_nlp: Language | None = None


def _get_nlp() -> Language:
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


def analyze_query(question: str, schema_index: SchemaIndex) -> QueryAnalysis:
    """
    Run the full classical NLP pipeline on a natural-language question.

    Returns a QueryAnalysis with intent, entities, schema matches, and a
    routing confidence score.  This is the sole entry-point for the nlp package.

    Usage:
        analysis = analyze_query("top 10 movies by IMDB rating", schema_index)
    """
    nlp = _get_nlp()
    intent, intent_conf = IntentClassifier(nlp).classify(question)
    entities = EntityExtractor(nlp).extract(question)
    schema_matches = SchemaMatcher(nlp, schema_index).match(question)
    return QueryAnalysis(
        intent=intent,
        intent_confidence=intent_conf,
        question=question,
        entities=entities,
        schema_matches=schema_matches,
    )
