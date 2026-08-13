from app.agents.orchestrator import AgentOrchestrator
from app.config import get_settings


def get_orchestrator() -> AgentOrchestrator:
    return AgentOrchestrator(get_settings())
