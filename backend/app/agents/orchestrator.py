from typing import Type

from app.agents.base import BaseAgent, AgentContext, OutputT
from app.config import Settings
from app.core.registry import agent_registry


def register_agent(agent_cls: Type[BaseAgent]) -> Type[BaseAgent]:
    """Decorator to register agents at import time."""

    def factory() -> BaseAgent:
        from app.config import get_settings

        return agent_cls(get_settings())

    agent_registry.register(agent_cls.name, factory())
    return agent_cls


class AgentOrchestrator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def run(self, agent_name: str, context: AgentContext) -> OutputT:
        if not self._settings.ai_agents_enabled:
            raise RuntimeError("AI agents are disabled")
        agent: BaseAgent = agent_registry.get(agent_name)
        return await agent.run(context)

    def available_agents(self) -> list[str]:
        return agent_registry.keys()
