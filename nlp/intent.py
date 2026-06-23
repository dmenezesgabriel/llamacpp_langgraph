"""Classify query intent from spaCy lemmas using a keyword config dict."""

from __future__ import annotations

from spacy.language import Language
from spacy.tokens import Doc

from nlp.types import Intent

# Keyword config: lemmatized signal words per intent.
# Order matters: earlier entries win on a tie.
_INTENT_KEYWORDS: dict[Intent, list[str]] = {
    Intent.RANK: [
        "top", "best", "worst", "highest", "lowest", "rank",
        "most", "least", "expensive", "cheapest", "popular",
    ],
    # Temporal period nouns (year/month/week) imply a GROUP BY time → trend
    Intent.TREND: [
        "trend", "over", "monthly", "daily", "weekly", "yearly",
        "annual", "time", "period", "evolution", "change", "grow",
        "year", "month", "week",
    ],
    Intent.AGGREGATE: [
        "total", "sum", "count", "average", "avg", "mean", "median",
        "maximum", "minimum", "max", "min", "how many", "how much",
    ],
    Intent.COMPARE: [
        "compare", "versus", "vs", "difference", "between",
        "breakdown", "distribution", "group",
    ],
    Intent.FILTER: [
        "where", "filter", "only", "with", "without", "exclude",
        "include", "longer", "shorter", "greater", "less", "above",
        "below", "specific", "which",
    ],
}

# When two intents tie, TREND wins over AGGREGATE (temporal specificity beats generic count).
_INTENT_PRIORITY: list[Intent] = [
    Intent.RANK, Intent.TREND, Intent.COMPARE, Intent.AGGREGATE, Intent.FILTER
]


class IntentClassifier:
    """
    Classifies query intent by matching spaCy lemmas against keyword lists.

    Usage:
        clf = IntentClassifier(nlp)
        intent, confidence = clf.classify("top 10 movies by IMDB rating")
    """

    def __init__(self, nlp: Language) -> None:
        self._nlp = nlp

    def classify(self, question: str) -> tuple[Intent, float]:
        doc = self._nlp(question.lower())
        lemmas = {t.lemma_ for t in doc if t.pos_ not in {"PUNCT", "SPACE"}}

        scores: dict[Intent, int] = {}
        for intent, keywords in _INTENT_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in lemmas or kw in question.lower())
            if hits:
                scores[intent] = hits

        if not scores:
            return Intent.UNKNOWN, 0.0

        max_score = max(scores.values())
        # Among intents with equal top score, pick by priority order
        best_intent = next(
            i for i in _INTENT_PRIORITY if scores.get(i, 0) == max_score
        )
        total_hits = sum(scores.values())
        confidence = scores[best_intent] / max(total_hits, 1)

        # Confidence floor: at least 1 hit with 2+ keywords → 0.6
        if scores[best_intent] >= 2:
            confidence = max(confidence, 0.6)
        elif scores[best_intent] == 1:
            confidence = max(confidence, 0.4)

        return best_intent, min(confidence, 1.0)


def _doc_text(doc: Doc) -> str:
    return " ".join(t.text for t in doc)
