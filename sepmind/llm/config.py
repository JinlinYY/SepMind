"""Global configuration for SepMind LLM backends.

This module provides a singleton configuration object to manage
the active LLM provider, API keys, and model settings globally.
"""

import os
from typing import Optional, Dict, Any, Literal

# Provider types
ProviderType = Literal["deepseek","qwen"]
PROVIDERS = ("deepseek","qwen")
DEFAULT_MODELS = {"deepseek":"deepseek-flash","qwen":"qwen-plus"}


class LLMConfig:
    """Singleton configuration for LLM settings."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LLMConfig, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._provider: ProviderType = "deepseek"
        self._api_key: Optional[str] = None
        self._model_name: Optional[str] = None
        self._temperature: float = 0.0
        self._initialized = True
        
        # Load defaults from environment variables
        self._load_from_env()

    def _load_from_env(self):
        """Load configuration from environment variables."""
        # Check for provider override
        env_provider = os.environ.get("SEPMIND_LLM_PROVIDER") or os.environ.get("PHA_LLM_PROVIDER")
        if env_provider and env_provider.lower() in PROVIDERS:
            self._provider = env_provider.lower()
            
        # Try to find API key for the current provider
        self._api_key = self._get_env_api_key(self._provider)

    def _get_env_api_key(self, provider: str) -> Optional[str]:
        """Get API key from environment for a specific provider."""
        env_vars = {"deepseek":"DEEPSEEK_API_KEY","qwen":"DASHSCOPE_API_KEY"}
        return os.environ.get(env_vars.get(provider, ""))

    def configure(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: float = 0.0,
    ):
        """Update global configuration.
        
        Args:
            provider: "gemini", "openai", "anthropic", or "deepseek".
            api_key: API key. If None, tries to load from env ONLY if provider differs.
            model_name: Model name. If None, uses default for provider.
            temperature: Sampling temperature.
        """
        if provider:
            provider = provider.lower()
            if provider not in PROVIDERS:
                raise ValueError(f"Unknown provider: {provider}")
            
            # If switching providers, we should re-fetch API key from env unless provided
            if provider != self._provider:
                # Never retain a different provider's model or credentials.
                self._api_key = api_key or self._get_env_api_key(provider)
                self._model_name = None
            
            self._provider = provider
            
        if api_key:
            self._api_key = api_key
            
        if model_name:
            self._model_name = model_name
            
        if temperature is not None:
             self._temperature = temperature

    @property
    def provider(self) -> str:
        return self._provider
    
    @property
    def api_key(self) -> Optional[str]:
        return self._api_key
    
    @property
    def model_name(self) -> str:
        env_model = os.environ.get("DEEPSEEK_MODEL" if self._provider=='deepseek' else 'QWEN_MODEL')
        if self._provider=='qwen' and not env_model:
            from .local_credentials import qwen_settings
            env_model=qwen_settings().get('model')
        return self._model_name or env_model or DEFAULT_MODELS[self._provider]
    
    @property
    def temperature(self) -> float:
        return self._temperature


# Global instance
config = LLMConfig()


def get_config() -> LLMConfig:
    """Get the global configuration instance."""
    return config


def configure_global(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    temperature: float = 0.0,
):
    """Convenience function to update global configuration."""
    config.configure(
        provider=provider,
        api_key=api_key,
        model_name=model_name,
        temperature=temperature
    )
