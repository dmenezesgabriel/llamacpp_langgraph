"""
LangGraph + DuckDB data analyst demo.

Backends: llama-cpp-python (default) or LiteLLM → GitHub Copilot
Datasets: NYC Taxi (April 2019), Seattle Weather, Movies, Cars

Usage:
  python main.py                                    # llama-cpp (default)
  python main.py --backend litellm                  # GitHub Copilot gpt-4o-mini
  python main.py --backend litellm --model github_copilot/claude-sonnet-4-6
  python main.py --backend litellm -i               # interactive + Copilot

Graph topology:
  disambiguate → [schema_inspector → query_planner → query_executor → reflector]* → responder
"""

from __future__ import annotations

import argparse


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LangGraph data analyst agent")
    p.add_argument(
        "--backend",
        choices=["llamacpp", "litellm"],
        default="llamacpp",
        help="LLM backend to use (default: llamacpp)",
    )
    p.add_argument(
        "--model",
        default="github_copilot/gpt-4o-mini",
        help="Model name for the litellm backend",
    )
    p.add_argument("-i", "--interactive", action="store_true", help="Run in interactive REPL mode")
    return p.parse_args()


from graph import build_graph  # noqa: E402

# ---------------------------------------------------------------------------
# Demo questions
# ---------------------------------------------------------------------------

DEMO_QUESTIONS = [
    # General chat
    "What datasets do you have available?",
    # Schema exploration
    "What columns are in the nyc_taxi table?",
    # Aggregation query
    "What is the average fare amount and average tip amount for NYC taxi trips?",
    # Filtered query
    "What are the top 5 pickup locations by number of trips in the NYC taxi data?",
    # Cross-domain
    "In the seattle_weather dataset, how many rainy days were there each year?",
    # Movies
    "Which 5 movies have the highest worldwide gross according to the movies table?",
    # Cars
    "What is the average horsepower by number of cylinders in the cars dataset?",
]


def run_demo(questions: list[str] | None = None) -> None:
    graph = build_graph()

    questions = questions or DEMO_QUESTIONS
    accumulated_messages: list = []

    print("=" * 70)
    print("  LangGraph + llama-cpp-python + DuckDB — Data Analyst Agent")
    print("  Model : LFM2.5-8B-A1B-Q4_K_M (Liquid Foundation Model 2.5)")
    print("=" * 70)
    print()

    for question in questions:
        print(f"\n{'─'*70}")
        print(f"🧑  {question}")
        print("─" * 70)

        accumulated_messages.append({"role": "user", "content": question})

        initial_state = {
            "messages": accumulated_messages,
            "user_question": question,
            "intent": "",
            "target_table": "",
            "schema_context": "",
            "sql_query": "",
            "sql_result": "",
            "reflection_notes": "",
            "reflection_retries": 0,
            "final_answer": "",
        }

        result = graph.invoke(initial_state)

        answer = result.get("final_answer", "")
        if not answer:
            last_msg = result["messages"][-1]
            answer = getattr(last_msg, "content", str(last_msg))

        print(f"\n🤖  {answer}\n")

        # Keep conversation history
        accumulated_messages = list(result["messages"])


def interactive_mode() -> None:
    """Simple REPL for interactive use."""
    graph = build_graph()
    accumulated_messages: list = []

    print("=" * 70)
    print("  LangGraph + llama-cpp-python + DuckDB — Data Analyst Agent")
    print("  Type 'quit' or 'exit' to stop.")
    print("=" * 70)
    print()

    while True:
        try:
            question = input("🧑  You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not question:
            continue
        if question.lower() in {"quit", "exit", "bye"}:
            print("Bye!")
            break

        accumulated_messages.append({"role": "user", "content": question})

        initial_state = {
            "messages": accumulated_messages,
            "user_question": question,
            "intent": "",
            "target_table": "",
            "schema_context": "",
            "sql_query": "",
            "sql_result": "",
            "reflection_notes": "",
            "reflection_retries": 0,
            "final_answer": "",
        }

        result = graph.invoke(initial_state)

        answer = result.get("final_answer", "")
        if not answer:
            last_msg = result["messages"][-1]
            answer = getattr(last_msg, "content", str(last_msg))

        print(f"\n🤖  {answer}\n")
        accumulated_messages = list(result["messages"])


if __name__ == "__main__":
    args = _parse_args()

    import llm as _llm_module
    _llm_module.configure(backend=args.backend, model=args.model)

    from db.loader import get_connection as _get_conn
    _get_conn()  # load datasets before the graph runs

    if args.interactive:
        interactive_mode()
    else:
        run_demo()
