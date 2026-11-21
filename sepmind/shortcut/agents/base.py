"""Common configuration and bounded exemplar use for specialist roles."""

from ..llm import make_backend, structured_call
from ..utils.few_shots import FewShotLibrary


class SpecialistAgent:
    role = None

    def __init__(self, backend=None, use_few_shots=True, example_library=None):
        self.backend = backend
        self.use_few_shots = use_few_shots
        self.example_library = example_library if example_library is not None else FewShotLibrary()

    def configure(self, api_key=None, provider="deepseek", model_name=None):
        self.backend = make_backend(provider=provider, model_name=model_name, api_key=api_key)
        return self

    def _request(self, instructions, schema, context, state, phase):
        entries = self.example_library.select(self.role, phase) if self.use_few_shots else []
        state.event(self.role, "few_shot_context", enabled=self.use_few_shots, phase=phase,
                    examples=[{"example_id": e["example"]["example_id"], "file": e["file"],
                               "sha256": e["sha256"]} for e in entries])
        return structured_call(self.backend, instructions, schema, context, state,
                               examples=[entry["example"] for entry in entries])
