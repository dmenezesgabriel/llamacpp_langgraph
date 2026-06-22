from abc import ABC, abstractmethod


class BaseLLM(ABC):
    @abstractmethod
    def call(self, prompt: str, stop: list[str] | None = None, **kwargs) -> str: ...
