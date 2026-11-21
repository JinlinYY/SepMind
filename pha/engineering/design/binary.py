"""Analytic binary balance and safeguarded McCabe-Thiele under explicit CMO/q=1."""

import math
import numpy as np
from scipy.optimize import brentq, minimize_scalar


def material_balance(basis):
    feed, target = basis.feed, basis.target
    flow = feed.flow * (3.6 if feed.flow_unit == "mol/s" else 1)
    z, xd = feed.composition[0], target.distillate_mole_fraction
    if target.bottoms_mole_fraction is not None:
        xb = target.bottoms_mole_fraction
        if not 0 < xb < z < xd < 1:
            raise ValueError("INPUT_UNDERDETERMINED: require 0 < xB < zF < xD < 1")
        distillate = flow*(z-xb)/(xd-xb)
    else:
        distillate = flow*z*target.key_component_recovery/xd
        if not 0 < distillate < flow:
            raise ValueError("BALANCE_CLOSURE_FAIL: impossible product split")
        xb = (flow*z-distillate*xd)/(flow-distillate)
        if not 0 < xb < z:
            raise ValueError("BALANCE_CLOSURE_FAIL: invalid bottoms composition")
    bottoms = flow-distillate
    recovery = distillate*xd/(flow*z)
    if target.key_component_recovery is not None and abs(recovery-target.key_component_recovery) > 1e-8:
        raise ValueError("SOURCE_CONFLICT: purity, bottoms and recovery overdetermine inconsistent specifications")
    return {"F_kmol_h": flow, "D_kmol_h": distillate, "B_kmol_h": bottoms,
            "zF": z, "xD": xd, "xB": xb, "key_component_recovery": recovery,
            "streams": [{"id": "F", "flow_kmol_h": flow, "composition": [z,1-z]},
                        {"id": "D", "flow_kmol_h": distillate, "composition": [xd,1-xd]},
                        {"id": "B", "flow_kmol_h": bottoms, "composition": [xb,1-xb]}]}


def minimum_reflux(package, basis, balance):
    if basis.feed.quality_q != 1:
        raise ValueError("UNSUPPORTED: this McCabe-Thiele adapter requires explicit saturated-liquid feed q=1")
    p, z, xd, xb = basis.feed.pressure_kPa*1000, balance["zF"], balance["xD"], balance["xB"]
    equilibrium = lambda x: package.point(float(x), p)["y"][0]

    def required(x):
        x = float(x)
        y = equilibrium(x)
        if y-x <= 1e-12:
            raise ValueError("FEAS_AZEOTROPE: sampled pinch or nominated component not enriched")
        if x >= z:
            return max(0.0, (xd-y)/(y-x))
        limit = xb + (y-xb)*(z-xb)/(x-xb)
        if limit <= z:
            raise ValueError("STAGE_PINCH: stripping-side feed intersection infeasible")
        return max(0.0, (xd-limit)/(limit-z))

    xs = np.linspace(xb+1e-7, xd-1e-7, 401)
    values = [required(x) for x in xs]
    candidates = [(values[i], float(xs[i])) for i in range(len(xs))]
    candidates.append((required(z), z))
    for i in range(1, len(xs)-1):
        if values[i] >= values[i-1] and values[i] >= values[i+1]:
            fit = minimize_scalar(lambda x: -required(x), bounds=(xs[i-1],xs[i+1]), method="bounded")
            candidates.append((-float(fit.fun), float(fit.x)))
    rmin, pinch = max(candidates)
    return {"minimum_reflux_ratio": float(rmin), "pinch_liquid_fraction": float(pinch),
            "method": "q=1 operating-line envelope, 401-point search plus bounded local refinement",
            "global_optimality_proven": False}


def stages(package, basis, balance, minimum):
    if "constant_molar_overflow" not in basis.assumptions:
        raise ValueError("REQUIRES_REVIEW: constant_molar_overflow must be explicitly accepted")
    reflux = basis.column.reflux_ratio
    if reflux is None:
        raise ValueError("INPUT_UNDERDETERMINED: specify operating reflux ratio")
    if reflux <= minimum["minimum_reflux_ratio"]*(1+1e-8):
        raise ValueError("STAGE_PINCH: reflux must exceed the calculated minimum")
    z, xd, xb = balance["zF"], balance["xD"], balance["xB"]
    p = basis.feed.pressure_kPa*1000
    equilibrium = lambda x: package.point(x, p)["y"][0]
    yf = (reflux*z+xd)/(reflux+1)
    strip_slope = (yf-xb)/(z-xb)
    y, previous_x = xd, xd
    steps, feed_stage = [], None
    for number in range(1,basis.column.max_stages+1):
        x = brentq(lambda v: equilibrium(v)-y, 0, 1, xtol=1e-11)
        if x >= previous_x-1e-11:
            raise ValueError("STAGE_PINCH: no monotonic stage progress")
        section = "rectifying" if x >= z else "stripping"
        if section == "stripping" and feed_stage is None:
            feed_stage = number
        next_y = (reflux*x+xd)/(reflux+1) if section == "rectifying" else xb+strip_slope*(x-xb)
        steps.append({"stage": number, "x": x, "y": y, "operating_y": next_y,
                      "equilibrium_residual": abs(equilibrium(x)-y), "section": section})
        if x <= xb:
            fraction = min(1.0,max(0.0,(previous_x-xb)/(previous_x-x)))
            return {"theoretical_stages_fractional": number-1+fraction,
                    "theoretical_stages_rounded_up": number, "feed_stage_from_top": feed_stage,
                    "reflux_ratio": reflux, "minimum_reflux_ratio": minimum["minimum_reflux_ratio"],
                    "steps": steps, "target_bottoms_fraction": xb,
                    "stage_convention": "equilibrium stages including partial reboiler, excluding total condenser; "
                                        "last fractional stage from linear composition interpolation",
                    "method": "binary McCabe-Thiele, constant molar overflow, saturated-liquid feed",
                    "actual_trays": None, "energy_balance_verified": False}
        if not 0 < next_y < y:
            raise ValueError("STAGE_PINCH: operating line does not permit physical monotonic stepping")
        y, previous_x = next_y, x
    raise ValueError("STAGE_PINCH: stage limit exhausted without reaching specified bottoms")
