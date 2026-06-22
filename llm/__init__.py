from __future__ import annotations

from .base import BaseLLM

_backend: BaseLLM | None = None


def configure(backend: str = "llamacpp", model: str = "github_copilot/gpt-4o-mini") -> None:
    global _backend
    if backend == "litellm":
        from .litellm import LiteLLMBackend
        _backend = LiteLLMBackend(model=model, temperature=0.1, max_tokens=512)
    else:
        from .llamacpp import LlamaCppBackend
        _backend = LlamaCppBackend()


def call_llm(prompt: str, stop: list[str] | None = None, **overrides) -> str:
    if _backend is None:
        configure()
    return _backend.call(prompt, stop=stop, **overrides)  # type: ignore[union-attr]


def get_model() -> BaseLLM:
    """Return the active backend for direct LangGraph tool-binding or structured output."""
    if _backend is None:
        configure()
    return _backend  # type: ignore[return-value]
