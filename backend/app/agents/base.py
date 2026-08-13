from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.config import Settings

OutputT = TypeVar("OutputT", bound=BaseModel)


class AgentContext(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    payload: dict[str, Any] = {}


class BaseAgent(ABC, Generic[OutputT]):
    """Extend and register — orchestrator dispatches by name."""

    name: str = "base"
    prompt_file: str = ""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load_prompt(self) -> str:
        path = self._settings.prompts_dir / self.prompt_file
        if path.exists():
            return path.read_text(encoding="utf-8")
        return f"You are the {self.name} agent for Deplot AI."

    @abstractmethod
    async def run(self, context: AgentContext) -> OutputT:
        ...
