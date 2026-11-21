"""Applicability hashes and a dependency DAG; hashes are not physical validation."""

import hashlib
import json


def basis_fingerprint(task, tool=None):
    names = ["components", "property_package", "property_basis_note", "pressure_pa"]
    if tool != "binary_vle":
        names += ["feed_molar_flow_mol_s", "feed_light_fraction", "feed_state",
                  "distillate_light_purity", "light_recovery"]
    payload = {name: getattr(task, name) for name in names}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def request_fingerprint(evidence):
    payload = {"tool": evidence.tool, "request": evidence.record.get("request")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def eligible_evidence(state):
    """Reject stale, missing-parent and cyclic evidence, including their descendants."""
    lookup = {e.evidence_id: e for e in state.evidence}
    memo = {}

    def valid(identifier, visiting):
        if identifier in memo:
            return memo[identifier]
        evidence = lookup.get(identifier)
        if evidence is None or identifier in visiting:
            return False
        result = (evidence.task_revision == state.task_revision
                  and (evidence.basis_fingerprint is None
                       or evidence.basis_fingerprint == basis_fingerprint(state.task, evidence.tool)))
        result = result and all(valid(parent, visiting | {identifier}) for parent in evidence.depends_on)
        memo[identifier] = result
        return result

    return [e for e in state.evidence if valid(e.evidence_id, set())]
