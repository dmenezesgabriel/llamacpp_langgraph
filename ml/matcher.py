from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _expand(name: str) -> str:
    """'nyc_taxi_trips' → 'nyc taxi trips nyc_taxi_trips' for richer TF-IDF overlap."""
    return name.replace("_", " ") + " " + name


class FieldMatcher:
    """TF-IDF cosine similarity matcher for table and column names."""

    TABLE_THRESHOLD = 0.10
    COLUMN_THRESHOLD = 0.10
    TOP_K_COLUMNS = 5

    def match_table(self, question: str, tables: list[str]) -> str | None:
        """Return the best-matching table name, or None if below threshold."""
        if not tables:
            return None
        corpus = [_expand(t) for t in tables]
        vec = TfidfVectorizer().fit(corpus)
        scores = cosine_similarity(vec.transform([question]), vec.transform(corpus))[0]
        best = int(scores.argmax())
        return tables[best] if scores[best] >= self.TABLE_THRESHOLD else None

    def match_columns(self, question: str, columns: list[str]) -> list[str]:
        """Return up to TOP_K_COLUMNS column names most relevant to the question."""
        if not columns:
            return []
        corpus = [_expand(c) for c in columns]
        vec = TfidfVectorizer().fit(corpus)
        scores = cosine_similarity(vec.transform([question]), vec.transform(corpus))[0]
        ranked = sorted(zip(scores, columns), reverse=True)
        return [col for score, col in ranked if score >= self.COLUMN_THRESHOLD][: self.TOP_K_COLUMNS]
