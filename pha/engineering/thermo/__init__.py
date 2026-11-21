"""Qualified, deterministic thermodynamic adapters."""

from .raoult import RaoultPackage


def selected_model(basis):
    from ..knowledge import choose_model
    return choose_model(basis)


def package_for(basis):
    model = selected_model(basis)
    pair={c.cas or c.canonical_id for c in basis.components}
    if pair in ({'71-43-2','108-88-3'}, {'67-56-1','7732-18-5'}):
        from .case_packages import CaseVLEPackage
        return CaseVLEPackage(basis)
    if model == 'NRTL':
        from .nrtl import EthanolWaterNRTL
        return EthanolWaterNRTL(basis)
    if model == 'Raoult':
        return RaoultPackage(basis)
    raise ValueError('DATA_PARAMETER_MISSING: selected package lacks a qualified adapter')
