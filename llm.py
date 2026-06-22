"""
LLM wrapper around llama-cpp-python.

Exposes a single `call_llm(prompt, **kwargs)` function used by all graph nodes.
Llama.cpp parameters are tuned for best balance of latency, reliability and
correctness with the LFM2.5-8B-A1B-Q4_K_M model.
"""

from __future__ import annotations

import os
from pathlib import Path

from llama_cpp import Llama

# ---------------------------------------------------------------------------
# Model parameters – tuned for LFM2.5-8B-A1B-Q4_K_M
# ---------------------------------------------------------------------------

MODEL_PATH = Path(__file__).parent / "models" / "LFM2.5-8B-A1B-Q4_K_M.gguf"

# Context window: large enough for schema + query + reflection rounds.
N_CTX = 8192

# Threads: use all physical cores for inference; avoids hyper-threading noise.
N_THREADS = max(1, (os.cpu_count() or 4))

# --- Generation hyper-parameters ---
# temperature: low → more deterministic / factual; good for SQL generation.
# top_p      : nucleus sampling – keeps the probability mass focused.
# top_k      : limits vocabulary to top-k tokens per step.
# repeat_penalty: discourages repetitive token loops.
# mirostat   : Mirostat 2 adaptive sampling – stabilises perplexity over
#              long generations, reduces hallucination on constrained tasks.

LLM_DEFAULTS = dict(
    max_tokens=512,
    temperature=0.1,        # Near-deterministic for data tasks
    top_p=0.9,
    top_k=40,
    repeat_penalty=1.1,
    mirostat_mode=2,        # Mirostat 2 – great for factual / SQL tasks
    mirostat_tau=3.0,       # Target perplexity (lower = tighter / safer)
    mirostat_eta=0.1,       # Learning rate for Mirostat
    echo=False,
)

print(f"Loading model: {MODEL_PATH.name} …")
_llm = Llama(
    model_path=str(MODEL_PATH),
    n_ctx=N_CTX,
    n_threads=N_THREADS,
    n_batch=512,            # Prompt-processing batch size; larger = faster ingestion
    use_mlock=False,        # Don't lock pages; avoids OOM on constrained systems
    verbose=False,
)
print("Model loaded ✓\n")


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def call_llm(prompt: str, stop: list[str] | None = None, **overrides) -> str:
    """
    Call the local LLM and return the generated text (stripped).

    Args:
        prompt  : The full prompt string (already formatted).
        stop    : Optional list of stop tokens.
        **overrides: Any LLM_DEFAULTS key can be overridden per call.
    """
    params = {**LLM_DEFAULTS, **overrides}
    if stop:
        params["stop"] = stop

    response = _llm(prompt, **params)
    text: str = response["choices"][0]["text"]

    # Strip internal chain-of-thought reasoning (LFM2.5 emits <think>...</think>)
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Also strip any trailing </think> without opening tag
    text = re.sub(r"</think>.*$", "", text, flags=re.DOTALL)

    return text.strip()
