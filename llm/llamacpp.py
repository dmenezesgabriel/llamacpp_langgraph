import os
import re
from pathlib import Path

from llama_cpp import Llama

from .base import BaseLLM

_DEFAULTS = dict(
    max_tokens=512,
    temperature=0.1,
    top_p=0.9,
    top_k=40,
    repeat_penalty=1.1,
    mirostat_mode=2,
    mirostat_tau=3.0,
    mirostat_eta=0.1,
    echo=False,
)

_MODEL_PATH = Path(__file__).parent.parent / "models" / "LFM2.5-8B-A1B-Q4_K_M.gguf"


class LlamaCppBackend(BaseLLM):
    def __init__(self) -> None:
        n_threads = max(1, (os.cpu_count() or 4))
        print(f"Loading model: {_MODEL_PATH.name} …")
        self._llm = Llama(
            model_path=str(_MODEL_PATH),
            n_ctx=8192,
            n_threads=n_threads,
            n_batch=512,
            use_mlock=False,
            verbose=False,
        )
        print("Model loaded ✓\n")

    def call(self, prompt: str, stop: list[str] | None = None, **overrides) -> str:
        params = {**_DEFAULTS, **overrides}
        if stop:
            params["stop"] = stop
        response = self._llm(prompt, **params)
        text: str = response["choices"][0]["text"]
        # Strip chain-of-thought tags emitted by LFM2.5
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"</think>.*$", "", text, flags=re.DOTALL)
        return text.strip()
