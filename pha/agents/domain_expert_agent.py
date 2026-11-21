# Derived from Google Health PHA, Apache-2.0; see LICENSE.txt and docs/engineering/UPSTREAM_BASE.md.
# Only shared behavior used by the separation-design extension remains active.
class DomainExpertAgent:
    """PHA expert-context base; thermodynamic skills supply the domain policy."""
    def __init__(self, preamble=None, context_memory=""):
        self.system_prompt=preamble
        self.context_memory=context_memory
        self._backend=None
        self._is_configured=False
