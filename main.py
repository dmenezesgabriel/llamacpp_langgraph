"""
LangGraph workflow demo.

Usage:
  python main.py                                          # llamacpp (default)
  python main.py --backend litellm --model gemini/gemini-2.5-flash
"""

from __future__ import annotations

import argparse

QUESTIONS = [
    "What is the capital of France?",
    "Explain LangGraph in one sentence.",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--backend", choices=["llamacpp", "litellm"], default="llamacpp")
    p.add_argument("--model", default="gemini/gemini-2.5-flash")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    import llm as _llm
    _llm.configure(backend=args.backend, model=args.model)

    from graph import build_graph
    graph = build_graph()

    for question in QUESTIONS:
        result = graph.invoke({"question": question, "answer": ""})
        print(f"Q: {result['question']}")
        print(f"A: {result['answer']}\n")
