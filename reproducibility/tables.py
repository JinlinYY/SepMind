"""Derive manuscript tables from the packaged numerical records."""

from collections import Counter
import csv
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path


EVIDENCE_FILE = Path(__file__).with_name("evidence.json")
CASES = ("D01", "D02", "D03", "D04")
DESIGN_SETTINGS = {"I": "Prescribed flowsheet design", "II": "Autonomous flowsheet design"}
ARMS = ("A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4")
STREAMS = {
    "H01": ("F03", "S03-S", "P03-MCH", "P03-TOL", "R03-S", "R03-W"),
    "H02": ("F05", "S05-S", "P05-MCH", "S05-B1", "P05-TOL", "R05-S"),
}
STREAM_NAMES = {
    "F03": "Fresh hydrocarbon feed", "S03-S": "Extraction solvent inlet",
    "P03-MCH": "MCH product", "P03-TOL": "Toluene product",
    "R03-S": "Recovered sulfolane", "R03-W": "Recovered wash water",
    "F05": "Fresh hydrocarbon feed", "S05-S": "Solvent inlet", "P05-MCH": "MCH distillate",
    "S05-B1": "First-column bottoms", "P05-TOL": "Toluene distillate", "R05-S": "Recovered phenol",
}


def load_evidence(path=EVIDENCE_FILE):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data["schema_version"] != 1 or set(data["binary"]) != set(CASES):
        raise ValueError("Unexpected publication evidence schema or case set")
    return data


def light_mass_percent(stream, molecular_weights):
    component_mass = [x * mw for x, mw in zip(stream["mole_fractions"], molecular_weights, strict=True)]
    return 100 * component_mass[0] / sum(component_mass)


def light_recovery_percent(outputs):
    feed, top = outputs["feed"], outputs["distillate"]
    return 100 * top["flow_mol_s"] * top["mole_fractions"][0] / (feed["flow_mol_s"] * feed["mole_fractions"][0])


def binary_residuals(record):
    o = record["outputs"]
    f, d, b = (o[k] for k in ("feed", "distillate", "bottoms"))
    def flow(stream, i):
        return stream["flow_mol_s"] * stream["mole_fractions"][i]
    def heat(stream):
        return stream["mass_flow_kg_s"] * stream["specific_enthalpy_kJ_kg"]
    component = max(abs(flow(f, i) - flow(d, i) - flow(b, i)) for i in range(2)) / f["flow_mol_s"]
    qc, qr = o["condenser_duty_kW"], o["reboiler_duty_kW"]
    energy = abs((heat(f) + qr) - (heat(d) + heat(b) + qc)) / max(qc, qr, 1)
    return component, energy


def binary_tables(cases):
    products, feeds, columns, equipment, closure = [], [], [], [], []
    for name, row in cases.items():
        req = row["requirements"]
        human, agent = row["human"], row["sepmind"]
        inputs = agent["request"]
        fixed = ("components", "property_package", "pressure_pa", "feed_molar_flow_mol_s",
                 "feed_light_fraction", "distillate_flow_mol_s", "bottom_pressure_pa")
        for key in fixed:
            if human["request"].get(key) != inputs.get(key):
                raise ValueError(f"{name}: the design pair differs in {key}")
        for record in (human, agent):
            checks = record["checks"]
            if ("DWSIM version 9.0.5" not in record["version"]
                    or record["status"] != "ok" or not checks["flowsheet_solved"]
                    or checks["product_compositions_imposed"]):
                raise ValueError(f"{name}: invalid strict-column record")
        for metric, target, operator, stream in (
            ("distillate_light_wt_percent", req["wd"], ">=", "distillate"),
            ("bottoms_light_wt_percent", req.get("wb"), "<=", "bottoms"),
            ("light_recovery_percent", req.get("recovery"), ">=", None),
        ):
            if target is None:
                continue
            def value(record):
                data = record["outputs"]
                return light_mass_percent(data[stream], req["mw"]) if stream else light_recovery_percent(data)
            measured = value(agent)
            meets_target = measured >= 100 * target if operator == ">=" else measured <= 100 * target
            if not meets_target:
                raise ValueError(f"{name}: accepted result misses {metric}")
            products.append(dict(case=name, metric=metric, operator=operator, requirement=100 * target,
                                 human=value(human), sepmind=measured))
        feeds.append(dict(case=name, feed_light_wt_percent=100 * req["wf"],
                          annual_capacity_t=req["throughput_t_y"], capacity_basis=req["throughput_basis"],
                          operating_hours=req["hours_y"], feed_kmol_h=3.6 * inputs["feed_molar_flow_mol_s"],
                          distillate_kmol_h=3.6 * inputs["distillate_flow_mol_s"],
                          pressure_kPa=inputs["pressure_pa"] / 1000, property_model=inputs["property_package"]))
        for label, record in (("human", human), ("sepmind", agent)):
            r = record["request"]
            columns.append(dict(case=name, design=label, R=r["reflux_ratio"],
                                N=r["equilibrium_stages"], NF=r["feed_stage"]))
        o = agent["outputs"]
        equipment.append(dict(case=name, condenser_duty_kW=o["condenser_duty_kW"],
                              reboiler_duty_kW=o["reboiler_duty_kW"], **row["equipment"]))
        c, e = binary_residuals(agent)
        if max(c, e) > 1e-4:
            raise ValueError(f"{name}: accepted column does not close")
        closure.append(dict(case=name, component_relative=c, energy_relative=e, recycle_tolerance=""))
    return {
        "table_01_products": products, "table_S04_simulation_basis": feeds,
        "table_S05_column_specifications": columns, "table_S06_duties_and_equipment": equipment,
    }, closure


def average(total, n, digits):
    return str((Decimal(total) / n).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def architecture_table(batches):
    expected = Counter((arm, case, r) for arm in ARMS for case in CASES for r in range(1, 11))
    batch_ids = {(b["policy"], b["revisions"]) for b in batches}
    if len(batches) != 4 or batch_ids != {("I", 3), ("II", 3), ("I", 5), ("II", 5)}:
        raise ValueError("Unexpected architecture benchmark conditions")
    results = []
    for batch in batches:
        rows = batch["runs"]
        if Counter((r["arm"], r["case"], r["repeat"]) for r in rows) != expected:
            raise ValueError("Incomplete architecture benchmark matrix")
        revisions = batch["revisions"]
        cap = batch["budgets"]["columns"]
        if cap != revisions + 1 or any(r["strict_calls"] > cap for r in rows):
            raise ValueError("Strict-column budget violation")
        for arm in ARMS:
            group = [r for r in rows if r["arm"] == arm]
            wins = sum(r["verified_success"] for r in group)
            calls = sum(r["llm_requests"] for r in group)
            tokens = [r["tokens"] for r in group if r["tokens"] is not None]
            results.append(dict(
                configuration=arm, historical_policy_label=batch["policy"],
                controller_policy=batch["controller_policy"], flowsheet_setting="I", revised_attempts_cap=revisions,
                strict_starts_cap=cap, target_early_stop=batch["stop_at_first_target"],
                verified=wins, runs=len(group), success_percent=average(100 * wins, len(group), 1),
                llm_calls_per_run=average(calls, len(group), 2), llm_total_calls=calls,
                strict_starts_per_run=average(sum(r["strict_calls"] for r in group), len(group), 2),
                tokens_per_run=average(sum(tokens), len(tokens), 0), complete_token_runs=len(tokens),
            ))
    return sorted(results, key=lambda row: (
        row["configuration"], row["historical_policy_label"], row["revised_attempts_cap"],
    ))


def paper_architecture_table(architecture):
    completed = [r for r in architecture if r["configuration"] in ARMS[:4] and r["controller_policy"] == "legacy"]
    metrics = ("verified", "runs", "success_percent", "llm_calls_per_run", "llm_total_calls",
               "strict_starts_per_run", "tokens_per_run", "complete_token_runs")
    rows = []
    for result in completed:
        conditions = {k: result[k] for k in ("configuration", "revised_attempts_cap", "strict_starts_cap")}
        rows.append(dict(**conditions, setting="I", design_setting=DESIGN_SETTINGS["I"],
                         evidence_status="recorded",
                         **{metric: result[metric] for metric in metrics}))
        rows.append(dict(**conditions, setting="II", design_setting=DESIGN_SETTINGS["II"],
                         evidence_status="formal_matrix_unavailable",
                         **dict.fromkeys(metrics, "")))
    return rows


def prescribed_protocol_table(architecture):
    protocols = {
        "legacy": "Original numerical review and revision",
        "evidence_v2": "Numerical review with explicit initialization evidence",
    }
    rows = []
    for result in architecture:
        metrics = {key: value for key, value in result.items()
                   if key not in {"configuration", "controller_policy", "historical_policy_label", "flowsheet_setting"}}
        rows.append(dict(configuration=result["configuration"], setting="I", design_setting=DESIGN_SETTINGS["I"],
                         numerical_protocol=protocols[result["controller_policy"]], **metrics))
    return rows


def autonomous_case_table(examples):
    if set(examples) != set(CASES) or any(not row["verified"] for row in examples.values()):
        raise ValueError("Unexpected autonomous case records")
    rows = []
    for case, row in examples.items():
        columns = row["columns"]
        outlets = "; ".join(f"{p['product_id']}={p['input_stream']}" for p in row["products"])
        for column in columns:
            rows.append(dict(case=case, design_setting=DESIGN_SETTINGS["II"],
                             run_id=row["run_id"], candidate_id=row["candidate_id"],
                             property_package=row["property_package"], column_count=len(columns),
                             column_id=column["column_id"], feed_stream=column["input_stream"],
                             equilibrium_stages=column["equilibrium_stages"], feed_stage=column["feed_stage"],
                             reflux_ratio=column["reflux_ratio"], product_routing=outlets,
                             prior_failure_record_count=row["prior_failure_record_count"], verified=row["verified"]))
    return rows


def hybrid_tables(hybrid):
    h01, h02 = hybrid["H01"], hybrid["H02"]
    products = [
        dict(case="H01", metric=f"{key}_product_mass_percent", operator=">=",
             requirement=100 * h01["original_targets"][f"{key}_mass_fraction_minimum"],
             calculated=100 * h01[f"{key}_mass_fraction"])
        for key in ("MCH", "TOL")
    ]
    products.extend(dict(case="H02", metric=row["id"], operator="<=",
                         requirement=row["maximum"], calculated=row["value"])
                    for row in h02["original_source_constraints"])
    if any(r["calculated"] < r["requirement"] if r["operator"] == ">="
           else r["calculated"] > r["requirement"] for r in products):
        raise ValueError("A recorded integrated product constraint failed")
    tables = {"table_03_integrated_products": products}
    closure = []
    for case, components, table, tolerance in (
        ("H01", ("MCH", "TOL", "sulfolane", "water"), "table_S09_sulfolane_streams", 1e-8),
        ("H02", ("MCH", "TOL", "phenol"), "table_S10_phenol_streams", 1e-9),
    ):
        record = hybrid[case]
        if not record["full_numerical_flowsheet_passed"]:
            raise ValueError(f"{case}: archived flowsheet failed")
        by_id = {s["id"]: s for s in record["streams"]}
        values = []
        for key in STREAMS[case]:
            stream = by_id[key]
            values.append(dict(stream=STREAM_NAMES[key], flow_mol_s=stream["flow_mol_s"],
                               temperature_K=stream["temperature_K"], pressure_kPa=stream["pressure_kPa"],
                               **dict(zip(components, stream["x"], strict=True))))
        tables[table] = values
        closure.append(dict(case=case, component_relative=record["component_closure_relative"],
                            energy_relative=record["energy_closure_relative"], recycle_tolerance=tolerance))
    return tables, closure


def manuscript_tables(evidence):
    binary, binary_closure = binary_tables(evidence["binary"])
    architecture = architecture_table(evidence["benchmark_batches"])
    hybrid, hybrid_closure = hybrid_tables(evidence["hybrid"])
    trace = evidence["ethanol_water_trace"]
    return {
        **binary, **hybrid,
        "table_02_architectures": paper_architecture_table(architecture),
        "architecture_and_ablation": prescribed_protocol_table(architecture),
        "autonomous_flowsheet_examples": autonomous_case_table(evidence["autonomous_examples"]),
        "table_S07_ethanol_reflux_candidates": trace["reflux_candidates"],
        "table_S08_cooling_water_revision": trace["condenser"],
        "table_S11_numerical_closure": binary_closure + hybrid_closure,
        "figure_03_ethanol_column_attempts": trace["attempts"],
    }


def export_tables(tables, destination):
    destination.mkdir(parents=True, exist_ok=False)
    for name, rows in tables.items():
        with (destination / f"{name}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
