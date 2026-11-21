"""Route numerical counterevidence to bounded design actions, not prose fixes."""
from typing import Literal
from pydantic import Field
from ..schemas import Contract


class ColumnDiagnosis(Contract):
    cause: Literal['phase_instability_inside_column','condensate_phase_instability',
                   'stage_equilibrium_residual','closure_failure','product_off_spec','conditional_unit_pass']
    evidence_ids: list[str]=Field(min_length=1)
    invalidated_gates: list[str]
    permitted_actions: list[str]
    explanation: str
    whole_process_completed: Literal[False]=False


def diagnose_column(goal_review, stage_review, evidence_ids):
    """Find where the evidence fails before choosing what to change.

    A homogeneous stage solution can satisfy fugacity equality on a metastable
    branch. Such a solution must not be repaired by blindly increasing R/N.
    """
    bad=[s['stage'] for s in stage_review['stages'] if s['liquid_stability_screen']['minimum_tpd'] < -1e-6]
    common={'evidence_ids':evidence_ids,'invalidated_gates':['G1','G4','G5','G6','G7','G8']}
    if any(i>0 for i in bad):
        return ColumnDiagnosis(**common,cause='phase_instability_inside_column',
            permitted_actions=['compare_unit_sequences','qualify_vlle_column_model'],
            explanation=f'Candidate homogeneous column has unstable liquid at stages {bad}; retain rejection and compare sequence or multiphase equations.')
    if bad:
        return ColumnDiagnosis(**common,cause='condensate_phase_instability',
            permitted_actions=['solve_multiphase_condenser_and_reflux','compare_unit_sequences'],
            explanation='Only the total condenser fails the liquid-stability screen. Solve phase split, enthalpy and reflux connections before approving the column.')
    if not goal_review['numerical_passed']:
        return ColumnDiagnosis(**common,cause='closure_failure',permitted_actions=['repair_numerics_and_recompute'],
            explanation='Independent component, mass conversion or energy closure fails; no product claim accepted.')
    if stage_review['maximum_log_fugacity_residual']>1e-3:
        return ColumnDiagnosis(**common,cause='stage_equilibrium_residual',permitted_actions=['repair_numerics_and_recompute'],
            explanation='Stagewise fugacity equations fail independently of the native convergence flag.')
    if not goal_review['conditional_unit_goals_passed']:
        return ColumnDiagnosis(**common,cause='product_off_spec',permitted_actions=['compare_reflux_and_stages','adjust_product_cut_within_inventory'],
            explanation='Numerically checked unit misses unchanged purity/recovery goals; compare bounded design choices with duty penalties.')
    return ColumnDiagnosis(cause='conditional_unit_pass',evidence_ids=evidence_ids,invalidated_gates=[],
        permitted_actions=['connect_next_unit_and_review_whole_process'],
        explanation='This unit meets the declared goals under the candidate model; parameter qualification and complete recycle remain separate.')
