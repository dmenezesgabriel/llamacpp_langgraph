"""
Hybrid classical-NLP + LLM text-to-SQL demo.

Usage:
  python main.py                                          # llamacpp (default)
  python main.py --backend litellm --model gemini/gemini-2.5-flash
  python main.py --interactive
"""

from __future__ import annotations

import argparse

# Queries designed to exercise all routing paths:
#   template path (high confidence) and LLM path (ambiguous or complex)
DEMO_QUESTIONS = [
    # --- Template path (high confidence) ---
    "What are the top 10 movies by IMDB rating?",
    "Show me NYC taxi trips longer than 15 miles.",
    "What is the total fare amount collected from all NYC taxi trips?",
    "What is the distribution of car origins (USA, Japan, Europe)?",
    # --- LLM path (lower confidence or complex) ---
    "How many rainy days were there in Seattle each year?",
    "Compare the average fare by payment type for NYC taxis.",
    "Which 5 movies have the highest IMDB votes count in the Drama genre?",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--backend", choices=["llamacpp", "litellm"], default="llamacpp")
    p.add_argument("--model", default="gemini/gemini-2.5-flash")
    p.add_argument("--interactive", action="store_true")
    return p.parse_args()


def _run(graph, question: str) -> None:
    state = graph.invoke({
        "question": question,
        "analysis": None,
        "sql": None,
        "sql_error": None,
        "query_result": None,
        "answer": "",
    })
    analysis = state.get("analysis")
    path = "TEMPLATE" if (analysis and analysis.confidence >= 0.7) else "LLM"
    print(f"Q [{path}]: {state['question']}")
    if state.get("sql"):
        print(f"SQL: {state['sql']}")
    print(f"A: {state['answer']}\n")


if __name__ == "__main__":
    args = _parse_args()

    import llm as _llm
    _llm.configure(backend=args.backend, model=args.model)

    from db.schema_index import SchemaIndex
    schema_index = SchemaIndex.build()

    from graph import build_graph
    graph = build_graph(schema_index)

    if args.interactive:
        print("Text-to-SQL REPL (type 'exit' to quit)\n")
        while True:
            q = input("Question: ").strip()
            if q.lower() in {"exit", "quit"}:
                break
            if q:
                _run(graph, q)
    else:
        for question in DEMO_QUESTIONS:
            _run(graph, question)
