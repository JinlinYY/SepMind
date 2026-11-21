"""Numerical screening of computed binary VLE evidence."""


def review_binary_vle(record, tolerance=1e-5):
    if record.get("status") != "ok" or not record.get("checks", {}).get("all_points_solved"):
        raise ValueError("Successful numerical evidence is required before review.")
    points = record["points"]
    differences = [point["y"][0] - point["x"][0] for point in points]
    crossings = [[a["x"][0], b["x"][0]] for a, b, da, db in
                 zip(points, points[1:], differences, differences[1:]) if da * db < 0]
    near_diagonal = [point["x"][0] for point, delta in zip(points, differences)
                     if abs(delta) <= tolerance]
    unresolved = bool(crossings or near_diagonal)
    return {
        "stage": "phase_behavior_screening",
        "evidence_id": record["evidence_id"],
        "observation": {"sampled_y_minus_x_range": [min(differences), max(differences)],
                        "crossing_intervals": crossings, "near_diagonal_samples": near_diagonal},
        "decision": "investigate_separation_boundary" if unresolved else "continue_feasibility_analysis",
        "reason": ("A crossing or near-diagonal sample requires checking a possible azeotrope or low volatility contrast."
                   if unresolved else "No crossing was detected on the sampled grid; feasibility is not yet established."),
        "next_action": ("Refine VLE sampling and validate the property model before selecting a route."
                        if unresolved else "Validate property parameters and evaluate the requested feed and product compositions."),
        "design_status": "not_designed",
        "limitations": record["limitations"],
    }
