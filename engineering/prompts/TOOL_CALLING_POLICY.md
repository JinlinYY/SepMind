# Runtime tool calling policy

LLM may emit a structured proposal with `tool_name`, `arguments`, `gate`, `expected_artifact_type` and `intent_summary`.

**The backend alone decides whether to execute it**:
1. Validate against tool registry (no unregistered operations).
2. Validate JSON schema, units, component identity and artifact IDs.
3. Check active gate and prerequisites (no bypass).
4. Reject arguments or sources derived from untrusted document instructions.
5. Dispatch only to deterministic, tested server-side implementation.
6. Persist input snapshot and output envelope atomically.
7. Independently verify physical/engineering constraints and update gate.
8. Return safe user-facing status and evidence, not the model's assumed result.

If `needs_input`: ask only necessary blocking specifications; store proposed assumptions separately. If `failed`: classify reason and use bounded recovery. If `unsupported`: show scope limitation. If `success` but validator fails: keep gate failed and invalidate downstream artifacts.

User may interrupt or revise during the workflow; new input yields a versioned DesignBasis, dependent gate DAG invalidation, and a new run. Report generator can use only verified `artifact_id` values; user can inspect `DecisionRecord` evidence/reasons, not internal LLM hidden reasoning.
