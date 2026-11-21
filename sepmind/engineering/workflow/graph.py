"""Canonical gates from the migration prompt (v2), not legacy overlay numbering.

G2 data qualification precedes physical G1 feasibility: a model-free feasibility
assertion is not permitted. G4 reuses the G1 equilibrium artifact after G3 balance.
G8 audits partial designs; absent G5-G7 are reported as blockers, never passed.
"""

DEPENDENCIES = {
    "G0": (), "G2": ("G0",), "G1": ("G0", "G2"), "G3": ("G1",),
    "G4": ("G2", "G3"), "G5": ("G4",), "G6": ("G4", "G5"),
    "G7": ("G5", "G6"), "G8": ("G0",), "G9": ("G8",),
}


def descendants(gates):
    result = set(gates)
    while True:
        updated = result | {g for g, parents in DEPENDENCIES.items() if result.intersection(parents)}
        if updated == result:
            return result | ({"G8", "G9"} if result else set())
        result = updated


def changed_gates(old, new):
    if old == new:
        return set()
    roots = {"G0"}
    if (old.components != new.components or old.thermodynamic_model != new.thermodynamic_model
            or old.design_mode != new.design_mode
            or old.assumptions != new.assumptions or old.source_ids != new.source_ids):
        roots |= {"G2", "G1"}
    if old.feed.pressure_kPa != new.feed.pressure_kPa or old.feed.temperature_K != new.feed.temperature_K:
        roots |= {"G2", "G1"}
    if old.feed.composition != new.feed.composition or old.target != new.target:
        roots |= {"G1", "G3"}
    if old.feed.flow != new.feed.flow or old.feed.flow_unit != new.feed.flow_unit:
        roots |= {"G3"}
    if old.feed.quality_q != new.feed.quality_q or old.feed.composition_basis != new.feed.composition_basis:
        roots |= {"G3", "G4"}
    if old.column != new.column:
        roots |= {"G4"}
    if old.design_level != new.design_level:
        roots |= {"G4"}
    if old.equipment != new.equipment:
        roots |= {"G6","G7"}
    # G0 is revalidated on every revision, but its generic graph edge must not
    # invalidate unrelated property/phase artifacts on a reflux-only change.
    return {"G0"} | descendants(roots - {"G0"})


def require_gate(state, gate):
    missing = [p for p in DEPENDENCIES[gate] if state.gates[p].status != "passed"]
    if missing:
        raise ValueError(f"GATE_PRECONDITION: {gate} requires {missing}")
