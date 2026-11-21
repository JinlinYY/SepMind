"""Necessary condensed-phase handling checks, separate from VLE convergence."""
import math


def near_pure_freezing_screen(temperature_K,composition,component_order,reference):
    if not math.isfinite(temperature_K) or len(composition)!=len(component_order) or any(not math.isfinite(v) or v<0 for v in composition) or abs(sum(composition)-1)>1e-8:
        raise ValueError('Invalid temperature/composition for condensed-phase review')
    cas=reference['CAS']
    if cas not in component_order:return dict(status='not_applicable',passed=None,scope='Referenced pure component absent')
    x=composition[component_order.index(cas)]
    if x<reference['engineering_near_pure_mole_fraction_threshold']:
        return dict(status='needs_input',passed=None,scope='Mixture liquidus is not established by a pure-solvent screen',mole_fraction=x)
    limit=reference['pure_reference_temperature_K']+reference['engineering_temperature_margin_K']
    return dict(status='passed' if temperature_K>=limit else 'failed',passed=temperature_K>=limit,
        temperature_K=temperature_K,minimum_handling_temperature_K=limit,mole_fraction=x,
        margin_to_pure_reference_K=temperature_K-reference['pure_reference_temperature_K'],
        source_url=reference['source_url'],scope='Near-pure liquid handling only; no full multicomponent SLE qualification')
