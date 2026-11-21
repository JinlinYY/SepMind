"""Structured role calls using the existing PHA provider abstraction."""

import json
import re


class AgentContractError(RuntimeError):
    pass


class LLMBudgetExceeded(RuntimeError):
    pass


def structured_call(backend, instructions, schema, context, state, examples=None):
    demonstration = ""
    if examples:
        demonstration = ("\nFEW_SHOT_EXAMPLES_DATA:\n"
                         "These are authored synthetic illustrations, not measurements or current-task evidence. "
                         "Learn the response structure and engineering checks. Example evidence IDs are not valid "
                         "citations for the current task; bind all citations to CONTEXT_DATA.available_evidence_ids.\n"
                         + json.dumps(examples, ensure_ascii=False, allow_nan=False))
    prompt = (instructions + demonstration + "\nOUTPUT_SCHEMA:\n" + json.dumps(schema.model_json_schema())
              + "\nCONTEXT_DATA:\n" + json.dumps(context, ensure_ascii=False, allow_nan=False))
    last_error = None
    for attempt in range(2):
        if state.llm_calls >= state.limits.max_llm_calls:
            raise LLMBudgetExceeded("LLM call budget exhausted.")
        state.llm_calls += 1
        raw = backend.generate(prompt)
        metadata = getattr(backend, "last_response_info", None)
        if metadata:
            role = {"DesignProposal": "design", "ExecutionPlan": "simulation",
                    "ReviewRecommendation": "review", "VerificationChoice": "design",
                    "VerificationAssessment": "review"}[schema.__name__]
            state.event(role, "llm_response", **metadata)
        try:
            if not isinstance(raw, str):
                raise ValueError("Expected a JSON string response.")
            raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            raw = re.sub(r"\s*```$", "", raw)
            value = schema.model_validate_json(raw)
            allowed = set(context["available_evidence_ids"])
            if not set(value.evidence_ids).issubset(allowed):
                raise ValueError("Unknown evidence ID.")
            return value
        except (ValueError, TypeError) as exc:
            last_error = exc
            if attempt == 0:
                prompt += "\nYour response failed the JSON/evidence contract. Return a corrected object only."
    raise AgentContractError(f"Invalid {schema.__name__} after two attempts: {last_error}")
