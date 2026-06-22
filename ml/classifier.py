from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

_TRAINING_DATA: list[tuple[str, str]] = [
    # data_query
    ("what is the average fare amount", "data_query"),
    ("how many trips were there", "data_query"),
    ("show me the top 5 pickup locations", "data_query"),
    ("what columns are in the nyc_taxi table", "data_query"),
    ("list all tables", "data_query"),
    ("what datasets do you have", "data_query"),
    ("which movies have the highest gross", "data_query"),
    ("average horsepower by cylinders", "data_query"),
    ("how many rainy days each year", "data_query"),
    ("total revenue by month", "data_query"),
    ("count trips per day", "data_query"),
    ("describe the seattle weather table", "data_query"),
    ("what is the distribution of fare amounts", "data_query"),
    ("show me cars with more than 6 cylinders", "data_query"),
    ("what are the fields in the movies table", "data_query"),
    ("give me the schema of nyc_taxi", "data_query"),
    ("which genre has the most movies", "data_query"),
    ("compare average tip by payment type", "data_query"),
    ("what is the highest temperature in seattle", "data_query"),
    ("sum of tips for each vendor", "data_query"),
    ("what is the correlation between fare and distance", "data_query"),
    ("how many available datasets", "data_query"),
    # general_chat
    ("hello how are you", "general_chat"),
    ("what can you help me with", "general_chat"),
    ("thanks", "general_chat"),
    ("who are you", "general_chat"),
    ("what is machine learning", "general_chat"),
    ("explain sql to me", "general_chat"),
    ("can you write a poem", "general_chat"),
    ("what time is it", "general_chat"),
    ("how does duckdb work", "general_chat"),
    ("tell me a joke", "general_chat"),
    ("what is a pivot table", "general_chat"),
    ("help me understand langgraph", "general_chat"),
    ("recommend a good book", "general_chat"),
    ("how do i connect to a database", "general_chat"),
    ("what programming language should i learn", "general_chat"),
    ("explain what a data warehouse is", "general_chat"),
    ("what is the difference between sql and nosql", "general_chat"),
    ("how does aggregation work", "general_chat"),
    ("goodbye", "general_chat"),
    ("nice to meet you", "general_chat"),
    ("can you help me debug my code", "general_chat"),
]


class IntentClassifier:
    def __init__(self) -> None:
        self._pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2))),
            ("clf", LogisticRegression(max_iter=300)),
        ])
        questions, labels = zip(*_TRAINING_DATA)
        self._pipeline.fit(list(questions), list(labels))

    def predict(self, question: str) -> str:
        """Return 'data_query' or 'general_chat'."""
        return self._pipeline.predict([question])[0]
