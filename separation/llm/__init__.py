"""LLM configuration and structured role calls, mirroring pha/llm."""
from .backend import make_backend
from .structured import AgentContractError, LLMBudgetExceeded, structured_call
__all__ = ["make_backend", "AgentContractError", "LLMBudgetExceeded", "structured_call"]
