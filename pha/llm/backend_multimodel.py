# Derived from Google Health PHA, Apache-2.0; see LICENSE.txt and docs/engineering/UPSTREAM_BASE.md.
# Only shared behavior used by the separation-design extension remains active.
import os
from abc import ABC, abstractmethod
from pha.llm.config import get_config, DEFAULT_MODELS

class LLMBackend(ABC):
    """Abstract base class for LLM backends."""
    
    @property
    @abstractmethod
    def provider(self) -> str:
        """Return the provider name (gemini, openai, anthropic)."""
        pass
    
    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate a response from the LLM."""
        pass
    
    def register(self) -> None:
        """Register this backend (no-op for most backends)."""
        pass

class DeepSeekBackend(LLMBackend):
    """Official DeepSeek chat API via requests; no OpenAI SDK/key required.

    JSON mode is intended for the separation team's structured handoffs. Normal
    text callers can leave json_mode=False. No prompts or credentials are logged.
    """

    endpoint = "https://api.deepseek.com/chat/completions"

    def __init__(self, api_key=None, model_name=None, temperature=0.0, max_tokens=4096,
                 json_mode=False, timeout_s=120, thinking=False):
        import requests
        self._requests = requests
        config = get_config()
        configured_key = config.api_key if config.provider == "deepseek" else None
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY") or configured_key
        if not self.api_key or not self.api_key.strip():
            raise ValueError("Set DEEPSEEK_API_KEY to use the DeepSeek API.")
        self.model_name = model_name or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODELS["deepseek"]
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_mode = json_mode
        self.timeout_s = timeout_s
        self.thinking = thinking
        self.last_response_info = None

    @property
    def provider(self):
        return "deepseek"

    def generate(self, prompt):
        self.last_response_info = None
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("DeepSeek prompt must be a nonempty string.")
        messages = []
        if self.json_mode:
            messages.append({"role": "system", "content":
                             "Return exactly one JSON object matching the user's output schema. No Markdown fences."})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": self.model_name, "messages": messages, "stream": False,
                   "max_tokens": self.max_tokens,
                   "thinking": {"type": "enabled" if self.thinking else "disabled"}}
        if not self.thinking:
            payload["temperature"] = self.temperature
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return self._complete(payload)

    def _complete(self,payload):
        label='DeepSeek' if self.provider=='deepseek' else 'Qwen'
        try:
            response = self._requests.post(
                self.endpoint, headers={"Authorization": f"Bearer {self.api_key}",
                                        "Content-Type": "application/json"},
                json=payload, timeout=(10, self.timeout_s), allow_redirects=False)
        except self._requests.Timeout:
            raise RuntimeError(f"{label} request timed out; no response accepted.") from None
        except self._requests.RequestException:
            raise RuntimeError(f"{label} connection failed; check network access.") from None
        if response.status_code != 200:
            reasons = {401: "authentication failed", 402: "insufficient balance",
                       429: "rate limit exceeded", 500: "server error", 503: "service unavailable"}
            reason = reasons.get(response.status_code, "request rejected")
            # Do not include upstream bodies, headers, or exception objects: they
            # may contain echoed request data or credentials.
            raise RuntimeError(f"{label} HTTP {response.status_code}: {reason}.")
        try:
            data = response.json()
            choice = data["choices"][0]
            reason = choice["finish_reason"]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise RuntimeError(f"{label} returned a malformed chat completion.") from None
        usage = data.get("usage") or {}
        self.last_response_info = {
            "provider": self.provider, "requested_model": self.model_name,
            "served_model": data.get("model"), "request_id": data.get("id"),
            "usage": {name: usage[name] for name in
                      ("prompt_tokens", "completion_tokens", "total_tokens")
                      if isinstance(usage.get(name), int) and usage[name] >= 0},
        }
        if reason != "stop":
            raise RuntimeError(f"{label} completion did not finish normally ({reason}); no partial response accepted.")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"{label} returned empty content; no response accepted.")
        return content


class QwenBackend(DeepSeekBackend):
    """Alibaba Qwen via its official compatible API; shared PHA HTTP semantics."""
    def __init__(self,api_key=None,model_name=None,temperature=0.,max_tokens=4096,
                 json_mode=False,timeout_s=120,base_url=None):
        import requests,re
        from urllib.parse import urlsplit
        from .local_credentials import qwen_key,qwen_settings
        self._requests=requests;settings=qwen_settings()
        self.api_key=api_key or os.environ.get('DASHSCOPE_API_KEY') or os.environ.get('QWEN_API_KEY') or qwen_key()
        if not self.api_key or not self.api_key.strip():
            raise ValueError('Set DASHSCOPE_API_KEY or use scripts/configure_qwen.ps1')
        self.model_name=model_name or os.environ.get('QWEN_MODEL') or settings.get('model') or 'qwen-plus'
        if not re.fullmatch(r'qwen[a-zA-Z0-9._-]*',self.model_name):raise ValueError('Use a Qwen model identifier')
        url=(base_url or os.environ.get('QWEN_BASE_URL') or settings.get('base_url') or 'https://dashscope.aliyuncs.com/compatible-mode/v1').rstrip('/')
        p=urlsplit(url)
        allowed=p.hostname in {'dashscope.aliyuncs.com','dashscope-intl.aliyuncs.com','dashscope-us.aliyuncs.com'} or re.fullmatch(r'llm-[a-zA-Z0-9-]+\.(cn-beijing|ap-southeast-1|us-east-1)\.maas\.aliyuncs\.com',p.hostname or '')
        if p.scheme!='https' or not allowed or p.path!='/compatible-mode/v1' or p.query or p.fragment or p.username or p.password or p.port not in (None,443):
            raise ValueError('Qwen requires an official Alibaba HTTPS compatible-mode/v1 endpoint')
        self.endpoint=url+'/chat/completions'
        self.temperature=temperature;self.max_tokens=max_tokens;self.json_mode=json_mode
        self.timeout_s=timeout_s;self.thinking=False;self.last_response_info=None

    @property
    def provider(self):return 'qwen'

    def generate(self,prompt):
        self.last_response_info=None
        if not isinstance(prompt,str) or not prompt.strip():raise ValueError('Qwen prompt must be a nonempty string')
        messages=[]
        if self.json_mode:messages.append({'role':'system','content':"Return exactly one JSON object matching the user's output schema. No Markdown fences."})
        messages.append({'role':'user','content':prompt})
        payload={'model':self.model_name,'messages':messages,'stream':False,
                 'temperature':self.temperature,'max_tokens':self.max_tokens,'enable_thinking':False}
        if self.json_mode:payload['response_format']={'type':'json_object'}
        return self._complete(payload)

def get_llm_backend(backend_type=None, api_key=None, model_name=None, temperature=0.0, max_tokens=8192):
    config=get_config()
    provider=(backend_type or config.provider).lower()
    if provider not in ('deepseek','qwen'):
        raise ValueError("Engineering LLM provider must be DeepSeek or Qwen")
    cls=DeepSeekBackend if provider=='deepseek' else QwenBackend
    selected=model_name or (config.model_name if config.provider==provider else None)
    return cls(api_key=api_key,model_name=selected,temperature=temperature,max_tokens=max_tokens)

