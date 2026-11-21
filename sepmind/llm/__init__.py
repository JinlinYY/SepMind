"""DeepSeek provider and shared PHA configuration API."""
from .config import LLMConfig, config, get_config, configure_global
from .backend_multimodel import LLMBackend, DeepSeekBackend, get_llm_backend
