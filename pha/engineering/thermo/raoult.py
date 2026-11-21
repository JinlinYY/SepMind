"""Ideal liquid/ideal vapor binary VLE with sourced pure vapor pressures.

No fitted binary parameters. Pure correlations are loaded from thermo's shipped
McGarry dataset; each call checks the declared temperature interval, with no
extrapolation. Ideal-mixture applicability remains an explicit user assumption.
"""

import hashlib
import json
import math
from scipy.optimize import brentq
from ..schemas import EvidenceRecord, ParameterSet


class RaoultPackage:
    MODEL = "Raoult"

    def __init__(self, basis):
        import thermo
        from thermo import VaporPressure
        if basis.thermodynamic_model != "Raoult":
            raise ValueError("DATA_PARAMETER_MISSING: only the qualified Raoult adapter is implemented")
        if "ideal_liquid_and_vapor" not in basis.assumptions:
            raise ValueError("REQUIRES_REVIEW: explicitly accept ideal_liquid_and_vapor for this calculation")
        if len(basis.components) != 2:
            raise ValueError("UNSUPPORTED: only two-component molecular VLE")
        allowed = {"142-82-5", "111-84-2"}
        if {c.cas or c.canonical_id for c in basis.components} != allowed:
            raise ValueError("DATA_PARAMETER_MISSING: this qualified ideal-mixture slice is n-heptane/n-nonane only")
        self.pressures = []
        cards = []
        sources = []
        for component in basis.components:
            cas = component.cas or component.canonical_id
            vapor = VaporPressure(CASRN=cas, extrapolation=None)
            method = "WAGNER_MCGARRY"
            if method not in vapor.all_methods:
                raise ValueError("DATA_PARAMETER_MISSING: no qualified vapor-pressure correlation for " + cas)
            vapor.method = method
            low, high = vapor.T_limits[method]
            coefficients = vapor.correlations[method][1]
            card = {"cas": cas, "method": method, "coefficients": coefficients,
                    "Tmin_K": low, "Tmax_K": high, "pressure_unit": "Pa"}
            digest = hashlib.sha256(json.dumps(card, sort_keys=True).encode()).hexdigest()
            sources.append(EvidenceRecord(
                evidence_id=f"thermo-{thermo.__version__}-{cas}-{digest[:12]}", type="property_database",
                source=f"thermo {thermo.__version__}, VaporPressure.WAGNER_MCGARRY; McGarry pure-fluid vapor-pressure dataset; "
                       "https://thermo.readthedocs.io/thermo.vapor_pressure.html", sha256=digest,
                valid_temperature_K=[low, high]))
            self.pressures.append(vapor);cards.append(card)
        self.low = max(c["Tmin_K"] for c in cards)
        self.high = min(c["Tmax_K"] for c in cards)
        self.parameters = ParameterSet(
            parameter_set_id=hashlib.sha256(json.dumps(cards, sort_keys=True).encode()).hexdigest(),
            model=self.MODEL, component_order=[c.cas or c.canonical_id for c in basis.components],
            sources=sources, correlations=cards, valid_temperature_K=[self.low, self.high],
            convention="y_i P = x_i P_i_sat(T), ideal liquid and ideal vapor; pressure in Pa; mole fractions")

    def psats(self, temperature):
        if not self.low <= temperature <= self.high:
            raise ValueError("MODEL_OUT_OF_RANGE: temperature outside joint correlation interval")
        values = [v(temperature) for v in self.pressures]
        if any(v is None or not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("MODEL_OUT_OF_RANGE: invalid pure saturation pressure")
        return values

    def point(self, x, pressure_pa):
        if not 0 <= x <= 1 or not math.isfinite(pressure_pa) or pressure_pa <= 0:
            raise ValueError("Invalid VLE composition or pressure")
        def residual(t):
            a, b = self.psats(t)
            return x*a + (1-x)*b - pressure_pa
        temperature = brentq(residual, self.low, self.high, xtol=1e-9)
        psat = self.psats(temperature)
        xs = [x, 1-x]
        ys = [xs[i]*psat[i]/pressure_pa for i in range(2)]
        fugacity = [ys[i]*pressure_pa - xs[i]*psat[i] for i in range(2)]
        return {"x": xs, "y": ys, "temperature_K": temperature, "psat_Pa": psat,
                "bubble_residual_relative": abs(residual(temperature))/pressure_pa,
                "fugacity_residual_Pa": fugacity, "vapor_sum_residual": abs(sum(ys)-1)}

    def grid(self, pressure_pa, points=81):
        data = [self.point(i/(points-1), pressure_pa) for i in range(points)]
        return {"points": data, "model": self.MODEL, "pressure_Pa": pressure_pa,
                "parameter_set": self.parameters.model_dump(),
                "scope": "finite-grid ideal-mixture screening, not an experimental property validation or global phase-stability proof"}
