import litellm

from .base import BaseLLM


class LiteLLMBackend(BaseLLM):
    def __init__(self, model: str = "github_copilot/gpt-4o-mini", **defaults) -> None:
        self._model = model
        self._defaults = defaults

    def call(self, prompt: str, stop: list[str] | None = None, **kwargs) -> str:
        params = {**self._defaults, **kwargs}
        if stop:
            params["stop"] = stop
        response = litellm.completion(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            **params,
        )
        return response.choices[0].message.content.strip()
