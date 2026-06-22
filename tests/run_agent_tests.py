"""
Agent test runner.
Sends each test question through the full LangGraph agent and captures:
- The intent classification
- The generated SQL
- The agent's final answer
- Reflection retries used

Results are saved to tests/agent_results.json for comparison with ground_truth.json
"""

from __future__ import annotations

import json
import os
import sys
import time

# Load datasets first
from db.loader import get_connection
_conn = get_connection()

from graph import build_graph

QUESTIONS = [
    {"id": "Q1",  "question": "What datasets / tables do you have available?"},
    {"id": "Q2",  "question": "What columns are in the nyc_taxi table?"},
    {"id": "Q3",  "question": "What is the average fare amount and average tip amount for NYC taxi trips?"},
    {"id": "Q4",  "question": "What are the top 5 pickup locations by number of trips in the NYC taxi data?"},
    {"id": "Q5",  "question": "In the seattle_weather dataset, how many rainy days were there each year?"},
    {"id": "Q6",  "question": "Which 5 movies have the highest worldwide gross?"},
    {"id": "Q7",  "question": "What is the average horsepower by number of cylinders in the cars dataset?"},
    {"id": "Q8",  "question": "What is the total revenue (total_amount) collected in the NYC taxi dataset?"},
    {"id": "Q9",  "question": "What percentage of NYC taxi trips are paid by credit card vs cash?"},
    {"id": "Q10", "question": "What are the top 5 longest taxi trips by distance?"},
    {"id": "Q11", "question": "What is the warmest month on average in Seattle?"},
    {"id": "Q12", "question": "How many movies are there per genre in the movies dataset?"},
    {"id": "Q13", "question": "Which country of origin has the most fuel-efficient cars on average?"},
    {"id": "Q14", "question": "How many NYC taxi trips happened at night (10pm - 6am) vs during the day?"},
    {"id": "Q15", "question": "What is the correlation between fare amount and tip amount in the taxi dataset?"},
]


def run_all() -> None:
    graph = build_graph()
    results = []

    print("=" * 70)
    print("  AGENT TEST RUNNER — LangGraph + DuckDB Agent")
    print("=" * 70)

    for q in QUESTIONS:
        qid = q["id"]
        question = q["question"]
        print(f"\n{'─'*70}")
        print(f"[{qid}] {question}")

        initial_state = {
            "messages": [{"role": "user", "content": question}],
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

        t0 = time.time()
        try:
            result = graph.invoke(initial_state)
            elapsed = time.time() - t0

            answer = result.get("final_answer", "")
            if not answer:
                last = result["messages"][-1]
                answer = getattr(last, "content", str(last))

            entry = {
                "id": qid,
                "question": question,
                "intent": result.get("intent", ""),
                "target_table": result.get("target_table", ""),
                "sql_query": result.get("sql_query", ""),
                "sql_result": result.get("sql_result", ""),
                "reflection_retries": result.get("reflection_retries", 0),
                "final_answer": answer,
                "elapsed_s": round(elapsed, 1),
                "error": None,
            }
            print(f"  intent={entry['intent']}  table={entry['target_table']}  retries={entry['reflection_retries']}  time={elapsed:.1f}s")
            print(f"  SQL: {entry['sql_query'][:100]}{'…' if len(entry['sql_query'])>100 else ''}")
            print(f"  Answer: {answer[:200]}{'…' if len(answer)>200 else ''}")

        except Exception as e:
            elapsed = time.time() - t0
            print(f"  ERROR after {elapsed:.1f}s: {e}")
            entry = {
                "id": qid,
                "question": question,
                "intent": "",
                "target_table": "",
                "sql_query": "",
                "sql_result": "",
                "reflection_retries": 0,
                "final_answer": "",
                "elapsed_s": round(elapsed, 1),
                "error": str(e),
            }

        results.append(entry)

    out_path = os.path.join(os.path.dirname(__file__), "agent_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n\n✅  Agent results saved to: {out_path}")


if __name__ == "__main__":
    run_all()
