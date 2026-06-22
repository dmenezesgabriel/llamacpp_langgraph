from langchain_litellm import ChatLiteLLM
from langchain_core.messages import HumanMessage

from .base import BaseLLM


class LiteLLMBackend(BaseLLM):
    def __init__(self, model: str = "github_copilot/gpt-4o-mini", **defaults) -> None:
        self._model = ChatLiteLLM(model=model, **defaults)

    def call(self, prompt: str, stop: list[str] | None = None, **kwargs) -> str:
        bind_kwargs = {**kwargs}
        if stop is not None:
            bind_kwargs["stop"] = stop
        model = self._model.bind(**bind_kwargs) if bind_kwargs else self._model
        return model.invoke([HumanMessage(content=prompt)]).content.strip()
