"""Reuse the original framework's provider abstraction; default to DeepSeek."""


def make_backend(provider="deepseek", model_name=None, api_key=None):
    from pha.llm.backend_multimodel import get_llm_backend
    backend = get_llm_backend(backend_type=provider, api_key=api_key,
                              model_name=model_name, temperature=0.0, max_tokens=4096)
    if backend.provider == "deepseek":
        backend.json_mode = True
    return backend
