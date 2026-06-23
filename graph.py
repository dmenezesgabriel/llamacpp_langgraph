"""Simple single-step LangGraph workflow: question → LLM → answer."""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from llm import call_llm


class AgentState(TypedDict):
    question: str
    answer: str


def respond(state: AgentState) -> AgentState:
    answer = call_llm(state["question"], max_tokens=400, temperature=0.2)
    return {"question": state["question"], "answer": answer}


def build_graph() -> StateGraph:
    builder = StateGraph(AgentState)
    builder.add_node("respond", respond)
    builder.set_entry_point("respond")
    builder.add_edge("respond", END)
    return builder.compile()
