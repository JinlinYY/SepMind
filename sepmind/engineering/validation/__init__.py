"""Independent numerical checks; no LLM can replace these acceptance tests."""

import math


def balance_checks(data, tolerance=1e-9):
    f,d,b = data["F_kmol_h"],data["D_kmol_h"],data["B_kmol_h"]
    residuals = [abs(f-d-b)/f]
    for z,xd,xb in ((data["zF"],data["xD"],data["xB"]),
                    (1-data["zF"],1-data["xD"],1-data["xB"])):
        residuals.append(abs(f*z-d*xd-b*xb)/f)
    values_valid = all(math.isfinite(v) and v > 0 for v in (f,d,b))
    recovery_residual = abs(d*data["xD"]/(f*data["zF"])-data["key_component_recovery"])
    return {"passed": values_valid and max(residuals+[recovery_residual]) < tolerance,
            "total_relative_residual": residuals[0], "component_relative_residuals": residuals[1:],
            "recovery_residual": recovery_residual, "tolerance": tolerance}


def vle_checks(data, tolerance=1e-7, package=None):
    p = data["pressure_Pa"]
    residual, sums = [], []
    valid = True
    for row in data["points"]:
        valid &= all(math.isfinite(v) and 0 <= v <= 1+tolerance for v in row["x"]+row["y"])
        valid &= math.isfinite(row["temperature_K"]) and row["temperature_K"] > 0
        # Recompute raw phase residual, rather than accepting the tool's boolean.
        psat = package.psats(row["temperature_K"]) if package is not None else row["psat_Pa"]
        gamma = (package.gammas(row['x'],row['temperature_K']) if package is not None and hasattr(package,'gammas')
                 else row.get('activity_coefficients',[1.,1.]) if package is None else [1.,1.])
        residual += [abs(row["y"][i]*p-row["x"][i]*gamma[i]*psat[i])/p for i in range(2)]
        if package is not None:
            residual += [abs(psat[i]-row["psat_Pa"][i])/p for i in range(2)]
            residual += [abs(gamma[i]-row.get('activity_coefficients',[1.,1.])[i]) for i in range(2)]
        sums += [abs(sum(row["x"])-1),abs(sum(row["y"])-1)]
    return {"passed": bool(valid and max(residual+sums) < tolerance),
            "maximum_fugacity_relative_residual": max(residual), "maximum_fraction_sum_residual": max(sums),
            "tolerance": tolerance, "model_applicability_experimentally_verified": False}


def stage_checks(data, balance, tolerance=1e-7, equilibrium=None):
    steps = data["steps"]
    monotonic = all(a["x"] > b["x"] for a,b in zip(steps,steps[1:]))
    residual = max(abs(equilibrium(row["x"])-row["y"]) if equilibrium else row["equilibrium_residual"] for row in steps)
    r,z,xd,xb = data["reflux_ratio"],balance["zF"],balance["xD"],balance["xB"]
    yf = (r*z+xd)/(r+1)
    operating_residual = max(abs(row["operating_y"]-((r*row["x"]+xd)/(r+1) if row["x"] >= z
                                else xb+(yf-xb)*(row["x"]-xb)/(z-xb))) for row in steps)
    passed = (monotonic and residual < tolerance and operating_residual < tolerance and steps[-1]["x"] <= balance["xB"]
              and data["reflux_ratio"] > data["minimum_reflux_ratio"]
              and data["feed_stage_from_top"] is not None)
    return {"passed": passed, "monotonic_stages": monotonic, "maximum_equilibrium_residual": residual,
            "maximum_operating_line_residual": operating_residual,
            "bottoms_target_reached": steps[-1]["x"] <= balance["xB"],
            "stage_convention": data["stage_convention"], "rigorous_MESH_verified": False}
