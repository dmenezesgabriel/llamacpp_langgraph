"""
LangGraph-based data analyst agent.

Graph topology
──────────────
                      ┌─────────────┐
             ┌────────► disambiguate │
             │        └──────┬──────┘
             │               │
             │         intent: data_query
             │               │
             │        ┌──────▼──────────┐
             │        │ schema_inspector │   ← fetches schema + sample
             │        └──────┬──────────┘
             │               │
             │        ┌──────▼──────┐
             │        │ query_planner│   ← generates SQL
             │        └──────┬──────┘
             │               │
             │        ┌──────▼──────┐
             │        │query_executor│  ← runs SQL via DuckDB
             │        └──────┬──────┘
             │               │
             │        ┌──────▼──────┐
             │        │  reflector  │   ← checks quality; may loop back
             │        └──────┬──────┘
             │         ok │  │ retry
             │            │  └──────────────────► query_planner (up to 3×)
             │        ┌───▼─────────┐
             └────────│  responder  │   ← formats final natural-language answer
                      └─────────────┘
             intent: general_chat ──────► responder (directly)
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from db.loader import get_connection
from db.tools import (
    TOOL_REGISTRY,
    get_schema,
    get_table_overview,
    list_tables,
    run_query,
    sample_data,
)
from llm import call_llm

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_REFLECTION_RETRIES = 3

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    """Full state carried through the graph."""

    # Conversation history (LangGraph message accumulator)
    messages: Annotated[list, add_messages]

    # ── Fields set during routing / planning ──
    user_question: str          # original user question
    intent: str                 # "data_query" | "general_chat"
    target_table: str           # table chosen by disambiguator
    schema_context: str         # schema + sample text
    sql_query: str              # generated SQL
    sql_result: str             # raw SQL result text
    reflection_notes: str       # feedback from reflector
    reflection_retries: int     # how many times we've looped back
    final_answer: str           # formatted answer for the user
    _routing: str               # internal routing signal ("ok" | "retry")


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def _tool_list_prompt() -> str:
    tables = list_tables()
    lines = ["Available DuckDB tools:", ""]
    for name, info in TOOL_REGISTRY.items():
        lines.append(f"  • {name}: {info['description']}")
    lines += ["", tables]
    return "\n".join(lines)


def _schema_prompt(table: str) -> str:
    return get_table_overview(table)


# ---------------------------------------------------------------------------
# Node 1 – disambiguate
# ---------------------------------------------------------------------------


def disambiguate(state: AgentState) -> AgentState:
    """
    Classify the user's question and identify the most relevant table.

    Strategy (in priority order):
      1. Keyword-based rule detection (fast, reliable for data questions)
      2. LLM classification as fallback for ambiguous cases
      3. Fuzzy table-name matching

    Sets: intent, target_table
    """
    question = state["user_question"]
    question_lower = question.lower()
    available = [r[0] for r in get_connection_tables()]

    # ── 1. Rule-based table detection ────────────────────────────────────────
    # Check if any known table name appears in the question
    matched_table: str | None = None
    for t in available:
        if t.lower() in question_lower or t.lower().replace("_", " ") in question_lower:
            matched_table = t
            break
    
    # Fallback aliases
    if not matched_table:
        if "taxi" in question_lower:
            matched_table = "nyc_taxi"
        elif "weather" in question_lower:
            matched_table = "seattle_weather"
        elif "movie" in question_lower:
            matched_table = "movies"
        elif "car" in question_lower:
            matched_table = "cars"
    # ── 2. Rule-based intent detection ───────────────────────────────────────
    # Strong data-query signals: mentions a known table OR asks for statistics
    DATA_KEYWORDS = {
        "average", "avg", "mean", "total", "sum", "count", "how many", "how much",
        "top", "bottom", "highest", "lowest", "most", "least", "best", "worst",
        "percent", "percentage", "distribution", "correlation", "compare",
        "which", "what is the", "list", "show me", "give me",
        "columns", "schema", "fields", "dataset", "table", "data",
        "trips", "fare", "tip", "revenue", "weather", "rainy", "warm",
        "movie", "genre", "horsepower", "cylinders", "mpg", "fuel",
        "pickup", "dropoff", "night", "day",
    }
    has_data_keyword = any(kw in question_lower for kw in DATA_KEYWORDS)
    rule_intent = "data_query" if (matched_table or has_data_keyword) else None

    # ── 3. LLM classification (only for ambiguous cases) ─────────────────────
    if rule_intent is None:
        tables_info = list_tables()
        prompt = f"""\
You are a data assistant router.

{tables_info}

User: "{question}"

Is this a DATA QUERY (needs SQL/data lookup) or GENERAL CHAT?
Reply with exactly one of: data_query OR general_chat

Answer:"""
        raw = call_llm(prompt, stop=["\n", " ", "."], max_tokens=15, temperature=0.0)
        llm_intent = "data_query" if "data" in raw.lower() else "general_chat"
        intent = llm_intent
    else:
        intent = rule_intent

    # ── 4. Table selection ────────────────────────────────────────────────────
    if matched_table:
        table = matched_table
    elif intent == "data_query":
        # No explicit table mentioned — ask the LLM to pick one
        tables_info = list_tables()
        prompt = f"""\
{tables_info}

User question: "{question}"

Which single table name from the list above is most relevant?
Reply with ONLY the table name (e.g.: nyc_taxi):"""
        raw = call_llm(prompt, stop=["\n", " ", ".", ","], max_tokens=20, temperature=0.0)
        raw = raw.strip().lower()
        # Validate
        if raw in available:
            table = raw
        else:
            # Fuzzy fallback
            table = next(
                (t for t in available if t in raw or raw in t),
                available[0] if available else "none"
            )
    else:
        table = "none"

    print(f"  [disambiguate] intent={intent}, table={table}, rule={rule_intent is not None}")
    return {**state, "intent": intent, "target_table": table}



def get_connection_tables() -> list[tuple]:
    return get_connection().execute("SHOW TABLES").fetchall()


# ---------------------------------------------------------------------------
# Node 2 – schema_inspector
# ---------------------------------------------------------------------------


def schema_inspector(state: AgentState) -> AgentState:
    """
    Fetch schema + sample data for the target table.

    Sets: schema_context
    """
    table = state["target_table"]
    ctx = _schema_prompt(table)
    print(f"  [schema_inspector] loaded context for '{table}' ({len(ctx)} chars)")
    return {**state, "schema_context": ctx}


# ---------------------------------------------------------------------------
# Node 3 – query_planner
# ---------------------------------------------------------------------------


def query_planner(state: AgentState) -> AgentState:
    """
    Generate a DuckDB SQL query to answer the user's question.

    Uses schema context + (on retry) reflection notes.
    Sets: sql_query
    """
    question = state["user_question"]
    question_lower = question.lower()
    schema_ctx = state["schema_context"]
    reflection = state.get("reflection_notes", "")
    retries = state.get("reflection_retries", 0)
    table = state.get("target_table", "")

    # ── Rule-based SQL overrides for common meta-questions ────────────────────
    if any(kw in question_lower for kw in ("what tables", "what datasets", "which tables",
                                            "available tables", "available datasets",
                                            "list tables", "list datasets", "show tables")):
        sql = "SHOW TABLES;"
        print(f"  [query_planner] rule-based SQL: {sql}")
        return {**state, "sql_query": sql}

    if any(kw in question_lower for kw in ("what columns", "which columns", "describe",
                                            "schema of", "columns in", "fields in",
                                            "columns are in", "structure of")) and table:
        sql = f"DESCRIBE {table};"
        print(f"  [query_planner] rule-based SQL: {sql}")
        return {**state, "sql_query": sql}

    # ── LLM-based SQL generation ──────────────────────────────────────────────
    retry_section = ""
    if reflection:
        retry_section = f"""
Previous SQL attempt failed or was incomplete.
Feedback from reflector:
{reflection}

Please fix the SQL based on this feedback.
"""

    prompt = f"""\
You are an expert DuckDB SQL writer.

{schema_ctx}

User question: "{question}"
{retry_section}
Rules:
- Write ONLY a single DuckDB-compatible SELECT statement (no SHOW, no DESCRIBE).
- Start the SQL with SELECT or WITH.
- Use exact column names from the schema above (case-sensitive where noted).
- Do NOT add markdown, backticks, explanations, or comments.
- End the SQL with a semicolon.
IMPORTANT: If you need to reason about the query, write your reasoning inside <think>...</think> tags. After the </think> tag, output ONLY the raw SQL query.

SQL:"""

    sql = call_llm(
        prompt,
        stop=["\n\n", "```", "User:", "Question:"],
        max_tokens=256,
        temperature=0.05,
    )

    # Strip any accidental markdown fences or explanations
    sql = re.sub(r"```[a-z]*", "", sql).strip()
    # Remove lines that don't look like SQL
    sql_lines = [l for l in sql.splitlines() if l.strip() and
                 not l.strip().startswith("--") and
                 not l.strip().lower().startswith("note")]
    sql = " ".join(sql_lines).strip()
    # Ensure it starts with SELECT/WITH
    if not re.match(r"^\s*(SELECT|WITH|SHOW|DESCRIBE)", sql, re.IGNORECASE):
        # Try to find SELECT in the text
        m = re.search(r"(SELECT\s+.+)", sql, re.IGNORECASE | re.DOTALL)
        sql = m.group(1) if m else f"SELECT * FROM {table} LIMIT 10"
    
    # Truncate at the first semicolon (if any) to remove conversational trailing garbage
    if ";" in sql:
        sql = sql.split(";")[0].strip() + ";"
    else:
        sql += ";"

    print(f"  [query_planner] SQL: {sql[:120]}{'…' if len(sql)>120 else ''}")
    return {**state, "sql_query": sql}


# ---------------------------------------------------------------------------
# Node 4 – query_executor
# ---------------------------------------------------------------------------


def query_executor(state: AgentState) -> AgentState:
    """
    Execute the generated SQL via DuckDB.

    Sets: sql_result
    """
    sql = state["sql_query"]
    result = run_query(sql, max_rows=20)
    print(f"  [query_executor] result preview: {result[:200]}")
    return {**state, "sql_result": result}


# ---------------------------------------------------------------------------
# Node 5 – reflector
# ---------------------------------------------------------------------------


def reflector(state: AgentState) -> AgentState:
    """
    Evaluate the SQL result.  If the result looks wrong/empty/errored,
    provide corrective feedback and signal a retry.

    Strategy:
      1. Rule-based: immediately flag SQL errors / empty results
      2. LLM-based: quality check for subtle issues

    Sets: reflection_notes, reflection_retries
    """
    question = state["user_question"]
    sql = state["sql_query"]
    result = state["sql_result"]
    retries = state.get("reflection_retries", 0)

    # Hard stop on max retries to avoid infinite loops
    if retries >= MAX_REFLECTION_RETRIES:
        print(f"  [reflector] max retries reached ({MAX_REFLECTION_RETRIES}), accepting result")
        return {**state, "reflection_notes": "", "_routing": "ok"}

    # ── Rule-based error detection ────────────────────────────────────────────
    result_lower = result.lower()
    sql_lower = sql.lower().strip()

    # Detect SQL execution errors
    if any(err in result_lower for err in ("sql error:", "error:", "syntax error",
                                            "not allowed", "parser error",
                                            "catalog error", "binder error")):
        issue = (
            f"The SQL produced an error: {result[:200]}. "
            "Rewrite the SQL correctly using only columns that exist in the schema."
        )
        print(f"  [reflector] rule: SQL error detected, retry {retries+1}")
        return {
            **state,
            "reflection_notes": issue,
            "reflection_retries": retries + 1,
            "_routing": "retry",
        }

    # Detect completely empty result for non-meta queries
    is_meta = sql_lower.startswith(("show", "describe"))
    if not is_meta and "no rows returned" in result_lower and retries == 0:
        issue = (
            "The query returned no rows. Check the WHERE clause conditions — "
            "they may be too restrictive or reference incorrect values."
        )
        print(f"  [reflector] rule: empty result, retry {retries+1}")
        return {
            **state,
            "reflection_notes": issue,
            "reflection_retries": retries + 1,
            "_routing": "retry",
        }

    # ── LLM-based quality check ───────────────────────────────────────────────
    prompt = f"""\
You are a critical data QA reviewer.

User question: "{question}"
SQL executed: {sql}
Result (first 300 chars):
{result[:300]}

Does this result correctly and directly answer the user's question?
Reply with STATUS: ok  or  STATUS: retry
If retry, add: ISSUE: <one sentence on what to fix>

Reply:"""

    raw = call_llm(prompt, stop=["\n\n"], max_tokens=100, temperature=0.0)

    status = "ok"
    issue = ""
    for line in raw.splitlines():
        line = line.strip()
        if line.upper().startswith("STATUS:"):
            val = line.split(":", 1)[1].strip().lower()
            status = "retry" if "retry" in val else "ok"
        elif line.upper().startswith("ISSUE:"):
            issue = line.split(":", 1)[1].strip()

    print(f"  [reflector] status={status}, retries={retries}, issue={issue[:80] if issue else '-'}")

    if status == "retry" and issue:
        return {
            **state,
            "reflection_notes": issue,
            "reflection_retries": retries + 1,
            "_routing": "retry",
        }

    return {**state, "reflection_notes": "", "_routing": "ok"}



def reflector_routing(state: AgentState) -> Literal["query_planner", "responder"]:
    return "query_planner" if state.get("_routing") == "retry" else "responder"


# ---------------------------------------------------------------------------
# Node 6 – responder
# ---------------------------------------------------------------------------


def responder(state: AgentState) -> AgentState:
    """
    Compose a clear, friendly natural-language answer from all gathered context.

    Sets: final_answer, messages
    """
    question = state["user_question"]
    intent = state.get("intent", "general_chat")

    if intent == "data_query":
        sql = state.get("sql_query", "")
        result = state.get("sql_result", "")
        schema_ctx = state.get("schema_context", "")

        prompt = f"""\
You are a friendly data analyst.

The user asked: "{question}"

You ran the following SQL:
{sql}

Result:
{result}

Write a concise, clear natural-language answer (2-5 sentences) based on the data above.
Do NOT repeat the SQL. Do NOT add irrelevant information.
IMPORTANT: You MUST write your internal reasoning inside <think>...</think> tags. After the </think> tag, write ONLY your final answer to the user.

Answer:"""
    else:
        # General chat – answer with awareness of available data
        tables_context = list_tables()
        history_parts = []
        for msg in state["messages"]:
            role = getattr(msg, "type", "user")
            content = getattr(msg, "content", str(msg))
            if role == "human":
                history_parts.append(f"User: {content}")
            elif role == "ai":
                history_parts.append(f"Assistant: {content}")
        history_str = "\n".join(history_parts) if history_parts else f"User: {question}"
        prompt = f"""\
You are a helpful data analyst assistant.

Context — data you have access to:
{tables_context}

Conversation:
{history_str}
Assistant:"""

    answer = call_llm(
        prompt,
        stop=["User:", "\nUser", "\n\n\n"],
        max_tokens=400,
        temperature=0.2,
    )

    print(f"  [responder] answer: {answer[:120]}{'…' if len(answer)>120 else ''}")
    return {
        **state,
        "final_answer": answer,
        "messages": [{"role": "assistant", "content": answer}],
    }


# ---------------------------------------------------------------------------
# Intent router
# ---------------------------------------------------------------------------


def intent_routing(state: AgentState) -> Literal["schema_inspector", "responder"]:
    return "schema_inspector" if state.get("intent") == "data_query" else "responder"


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------


def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    builder.add_node("disambiguate", disambiguate)
    builder.add_node("schema_inspector", schema_inspector)
    builder.add_node("query_planner", query_planner)
    builder.add_node("query_executor", query_executor)
    builder.add_node("reflector", reflector)
    builder.add_node("responder", responder)

    builder.set_entry_point("disambiguate")

    # After disambiguate → branch on intent
    builder.add_conditional_edges("disambiguate", intent_routing)

    # Data query path
    builder.add_edge("schema_inspector", "query_planner")
    builder.add_edge("query_planner", "query_executor")
    builder.add_edge("query_executor", "reflector")

    # Reflection loop or proceed
    builder.add_conditional_edges("reflector", reflector_routing)

    # Terminal
    builder.add_edge("responder", END)

    return builder.compile()
