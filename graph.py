"""
Multi-node hybrid NLP + LLM text-to-SQL workflow.

Routing:
  classical NLP (analyze_query) → high confidence → SQL template → validate → execute → narrate
                                 → low confidence  → LLM SQL gen → execute → narrate
  template validation failure   → LLM SQL gen     → execute → narrate
"""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from db.schema_index import SchemaIndex
from db.tools import run_query
from llm import call_llm
from nlp import analyze_query
from nlp.sql_templates import TemplateBuildError, build_sql
from nlp.types import QueryAnalysis

_CONFIDENCE_THRESHOLD = 0.7


class AgentState(TypedDict):
    question: str
    analysis: QueryAnalysis | None
    sql: str | None
    sql_error: str | None   # set when EXPLAIN fails; clears on valid sql
    query_result: str | None
    answer: str


# ---------------------------------------------------------------------------
# Node factories — closed over schema_index
# ---------------------------------------------------------------------------


def _make_analyze_node(schema_index: SchemaIndex):
    def analyze_node(state: AgentState) -> AgentState:
        analysis = analyze_query(state["question"], schema_index)
        return {**state, "analysis": analysis}
    return analyze_node


def _make_template_node():
    def template_node(state: AgentState) -> AgentState:
        try:
            sql = build_sql(state["analysis"])  # type: ignore[arg-type]
            return {**state, "sql": sql, "sql_error": None}
        except TemplateBuildError as e:
            # Signal routing to fall through to LLM
            return {**state, "sql": None, "sql_error": str(e)}
    return template_node


def _make_llm_sql_node(schema_index: SchemaIndex):
    def llm_sql_node(state: AgentState) -> AgentState:
        analysis: QueryAnalysis = state["analysis"]  # type: ignore[assignment]
        prompt = _llm_sql_prompt(analysis, schema_index)
        raw = call_llm(prompt, max_tokens=1200, temperature=0.1, stop=["```", ";;\n"])
        sql = _extract_sql(raw)
        return {**state, "sql": sql, "sql_error": None}
    return llm_sql_node


def _make_validate_node():
    from db.loader import get_connection

    def validate_node(state: AgentState) -> AgentState:
        sql = state.get("sql")
        if not sql:
            return {**state, "sql_error": "No SQL to validate"}
        try:
            get_connection().execute(f"EXPLAIN {sql}")
            return {**state, "sql_error": None}
        except Exception as exc:  # noqa: BLE001
            return {**state, "sql": None, "sql_error": str(exc)}
    return validate_node


def _make_execute_node():
    def execute_node(state: AgentState) -> AgentState:
        sql = state.get("sql")
        if not sql:
            return {**state, "query_result": f"Error: no valid SQL (last error: {state.get('sql_error')})"}
        result = run_query(sql, max_rows=20)
        return {**state, "query_result": result}
    return execute_node


def _make_narrate_node():
    def narrate_node(state: AgentState) -> AgentState:
        result = state.get("query_result", "")
        # Propagate SQL execution errors without LLM narration
        if result.startswith("Error:") or result.startswith("SQL error:"):
            return {**state, "answer": result}
        # Single-scalar: return the value directly (no LLM call)
        if _is_scalar(result):
            value = _extract_scalar(result)
            return {**state, "answer": value}
        prompt = _narrate_prompt(state["question"], state.get("sql", ""), result)
        # Disable mirostat for narration: it makes the model verbose in <think>,
        # exhausting tokens before emitting the actual 1-2 sentence answer.
        answer = call_llm(prompt, max_tokens=800, temperature=0.2, mirostat_mode=0)
        return {**state, "answer": answer.strip()}
    return narrate_node


# ---------------------------------------------------------------------------
# Routing functions (conditional edges)
# ---------------------------------------------------------------------------


def _route_after_analyze(state: AgentState) -> Literal["template_sql", "llm_sql"]:
    analysis = state.get("analysis")
    if analysis and analysis.confidence >= _CONFIDENCE_THRESHOLD:
        return "template_sql"
    return "llm_sql"


def _route_after_validate(state: AgentState) -> Literal["execute_query", "llm_sql"]:
    if state.get("sql_error"):
        return "llm_sql"
    return "execute_query"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_graph(schema_index: SchemaIndex) -> StateGraph:
    builder = StateGraph(AgentState)

    builder.add_node("analyze_query", _make_analyze_node(schema_index))
    builder.add_node("template_sql", _make_template_node())
    builder.add_node("llm_sql", _make_llm_sql_node(schema_index))
    builder.add_node("validate_sql", _make_validate_node())
    builder.add_node("execute_query", _make_execute_node())
    builder.add_node("narrate", _make_narrate_node())

    builder.set_entry_point("analyze_query")
    builder.add_conditional_edges("analyze_query", _route_after_analyze)
    builder.add_edge("template_sql", "validate_sql")
    builder.add_conditional_edges("validate_sql", _route_after_validate)
    builder.add_edge("llm_sql", "execute_query")
    builder.add_edge("execute_query", "narrate")
    builder.add_edge("narrate", END)

    return builder.compile()


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def _llm_sql_prompt(analysis: QueryAnalysis, schema_index: SchemaIndex) -> str:
    table = analysis.primary_table or "unknown"
    schema = schema_index.schema_snippet(table)
    sample_values = _sample_values_hint(schema_index, table)
    entities_str = ", ".join(
        f"{e.entity_type}:{e.value!r}" for e in analysis.entities
    )
    return (
        f"Generate a single DuckDB SQL SELECT query for this question.\n\n"
        f"Question: {analysis.question}\n"
        f"Intent: {analysis.intent.value}\n"
        f"Detected entities: {entities_str or 'none'}\n"
        f"Schema: {schema}\n"
        f"{sample_values}"
        f"\nRULES:\n"
        f"- Column names in the schema are shown with double quotes — use them exactly as shown.\n"
        f"  Example: \"Worldwide Gross\" / \"Production Budget\" — not Worldwide_Gross / Production_Budget.\n"
        f"- Use only column names that appear in the schema above.\n"
        f"- For date extraction use YEAR(col) consistently in both SELECT and GROUP BY — do not mix YEAR() with EXTRACT().\n"
        f"- Use positional GROUP BY (GROUP BY 1, 2) to avoid repeating expressions.\n"
        f"- Return ONLY the SQL query, no explanation, no markdown fences."
    )


def _sample_values_hint(schema_index: SchemaIndex, table: str) -> str:
    """Build a compact sample-values line for categorical columns in the table."""
    tinfo = schema_index.get_table(table)
    if not tinfo:
        return ""
    pairs = [
        f'"{c.name}": {c.sample_values}'
        for c in tinfo.columns
        if c.sample_values
    ]
    if not pairs:
        return ""
    return "Categorical column values: " + ", ".join(pairs) + "\n"


def _narrate_prompt(question: str, sql: str, result: str) -> str:
    return (
        f"Summarize the following query result in 1-2 sentences of plain English.\n\n"
        f"Question: {question}\n"
        f"Result:\n{_truncate_result(result)}\n\n"
        f"Answer:"
    )


def _truncate_result(result: str, max_lines: int = 20) -> str:
    """Truncate by lines so the model always sees complete rows, never a cut-off header."""
    lines = result.splitlines()
    if len(lines) <= max_lines:
        return result
    return "\n".join(lines[:max_lines]) + f"\n… ({len(lines) - max_lines} more lines)"


def _is_scalar(result: str) -> bool:
    """True when the result is a single-cell table (one data row, one column)."""
    lines = [l for l in result.strip().splitlines() if l.startswith("|")]
    return len(lines) == 2  # header row + one data row


def _extract_scalar(result: str) -> str:
    lines = [l for l in result.strip().splitlines() if l.startswith("|")]
    if len(lines) >= 2:
        parts = [p.strip() for p in lines[1].split("|") if p.strip()]
        return parts[0] if parts else result
    return result


def _extract_sql(raw: str) -> str:
    """Strip markdown fences and leading/trailing whitespace from LLM output."""
    sql = raw.strip()
    for fence in ("```sql", "```", "'''sql", "'''"):
        if sql.startswith(fence):
            sql = sql[len(fence):]
        if sql.endswith(fence[::-1].replace("lqs", "")):
            sql = sql[: sql.rfind(fence[0] * 3)]
    return sql.strip().rstrip(";")
