"""
LLM wrapper using LiteLLM with GitHub Copilot as the inference provider.

Exposes a single `call_llm(prompt, **kwargs)` function used by all graph nodes.
"""

from __future__ import annotations

import re

import litellm

# GitHub Copilot model via LiteLLM
MODEL = "github_copilot/gpt-4o"

# Default generation parameters
LLM_DEFAULTS = dict(
    max_tokens=512,
    temperature=0.1,
)


def call_llm(prompt: str, stop: list[str] | None = None, **overrides) -> str:
    """
    Call the LLM via LiteLLM and return the generated text (stripped).

    Args:
        prompt  : The full prompt string (already formatted).
        stop    : Optional list of stop tokens.
        **overrides: Any LLM_DEFAULTS key can be overridden per call.
    """
    params = {**LLM_DEFAULTS, **overrides}

    messages = [{"role": "user", "content": prompt}]

    kwargs: dict = {"model": MODEL, "messages": messages, **params}
    if stop:
        kwargs["stop"] = stop

    response = litellm.completion(**kwargs)
    text: str = response.choices[0].message.content or ""

    # Strip internal chain-of-thought reasoning if present
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"</think>.*$", "", text, flags=re.DOTALL)

    return text.strip()
