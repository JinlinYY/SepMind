"""Conservative explicit extraction; never silently supplies a design basis."""

import re

ALIASES = {
    "n-heptane": ("n-heptane", "heptane", "\u6b63\u5e9a\u70f7"),
    "n-nonane": ("n-nonane", "nonane", "\u6b63\u58ec\u70f7"),
    "ethanol": ("ethanol", "\u4e59\u9187"), "water": ("water", "\u6c34"),
}
CAS = {"n-heptane": "142-82-5", "n-nonane": "111-84-2", "ethanol": "64-17-5", "water": "7732-18-5"}


def route(message, has_state=False):
    text = message.lower()
    if any(word in text for word in ("\u7535\u89e3\u8d28", "\u53cd\u5e94\u7cbe\u998f", "\u56fa\u6db2", "vlle", "electrolyte", "reactive distillation", "solid-liquid", "construction drawing", "\u65bd\u5de5", "\u5236\u9020\u56fe")):
        return "UNSUPPORTED"
    if has_state and any(word in text for word in ("\u6539\u4e3a", "\u6539\u6210", "\u8c03\u6574", "\u4fee\u6539", "change", "update")):
        return "DESIGN_REVISION"
    if has_state and any(word in text for word in ("\u89e3\u91ca\u672c\u6b21", "\u89e3\u91ca\u7ed3\u679c", "\u8ba1\u7b97\u7ed3\u679c", "\u8fd9\u4e2a\u7ed3\u679c", "\u4e0a\u6b21\u7ed3\u679c", "explain the result", "explain the results", "explain this result")):
        return "RESULT_EXPLANATION"
    if any(word in text for word in ("\u4e3a\u4ec0\u4e48", "\u662f\u4ec0\u4e48", "\u89e3\u91ca", "\u539f\u7406", "what is", "what are", "why ", "explain ")):
        return "KNOWLEDGE_QA"
    if any(word in text for word in ("\u6ce1\u70b9", "vle", "\u76f8\u5e73\u8861\u66f2\u7ebf", "txy")) and "\u8bbe\u8ba1" not in text and "design" not in text:
        return "THERMODYNAMIC_CALCULATION"
    return "PROCESS_DESIGN"


def extract_patch(message, previous=None):
    """Small documented grammar; unknown/ambiguous expressions remain missing."""
    text = message.lower()
    patch = {}
    if previous is None or not previous.components:
        components = []
        for name, aliases in ALIASES.items():
            if any(alias in text for alias in aliases):
                components.append({"canonical_id": CAS[name], "name": name, "cas": CAS[name]})
        if components:
            patch["components"] = components
    feed = {}
    pressure = re.search(r"(?:\u538b\u529b|pressure)[^\d]{0,10}(\d+(?:\.\d+)?)\s*(kpa|mpa|pa|bar)", text)
    if pressure is None and previous is not None:
        pressure = re.fullmatch(r"\s*(?:\u6539\u4e3a|\u6539\u6210|\u8c03\u6574\u4e3a|change to)\s*(\d+(?:\.\d+)?)\s*(kpa|mpa|pa|bar)[\u3002.!]?\s*",text)
    if pressure:
        value, unit = float(pressure[1]), pressure[2]
        feed["pressure_kPa"] = value * {"kpa": 1, "mpa": 1000, "pa": .001, "bar": 100}[unit]
    elif "\u5e38\u538b" in text or "atmospheric" in text:
        feed["pressure_kPa"] = 101.325  # explicitly named standard atmosphere
    flow = re.search(r"(?:\u8fdb\u6599(?:\u91cf)?|feed(?: flow(?: rate)?)?)[^\d]{0,10}(\d+(?:\.\d+)?)\s*(kmol/h|mol/s)", text)
    if flow:
        feed.update(flow=float(flow[1]), flow_unit=flow[2])
    z = re.search(r"(?:zf|feed mole fraction|mole fraction|\u6469\u5c14\u5206\u6570|\u6469\u5206)\s*[=:\uFF1A\u4e3a]?\s*(0?\.\d+)", text)
    if z:
        value = float(z[1]);feed.update(composition=[value, 1-value], composition_basis="mole_fraction")
    if "\u9971\u548c\u6db2" in text or "\u6ce1\u70b9\u8fdb\u6599" in text or "saturated liquid" in text:
        feed["quality_q"] = 1
    if feed:
        patch["feed"] = feed
    target = {}
    for key, pattern in (("distillate_mole_fraction", r"(?:xd|distillate(?: purity)?|\u5854\u9876(?:\u7eaf\u5ea6)?|\u4ea7\u54c1\u7eaf\u5ea6)[^\d]{0,10}(0?\.\d+)"),
                         ("bottoms_mole_fraction", r"(?:xb|bottoms|\u5854\u5e95)[^\d]{0,10}(0?\.\d+)"),
                         ("key_component_recovery", r"(?:\u56de\u6536\u7387|recovery)[^\d]{0,10}(0?\.\d+)")):
        found = re.search(pattern, text)
        if found:
            target[key] = float(found[1])
    if target:
        patch["target"] = target
    reflux = re.search(r"(?:\u56de\u6d41\u6bd4|reflux ratio)[^\d]{0,10}(\d+(?:\.\d+)?)", text)
    if reflux:
        patch["column"] = {"reflux_ratio": float(reflux[1])}
    if "raoult" in text:
        patch["thermodynamic_model"] = "Raoult"
    elif 'nrtl' in text:
        patch['thermodynamic_model'] = 'NRTL'
    if '\u81ea\u4e3b' in text or 'autonomous' in text:
        patch['design_mode'] = 'autonomous'
    return patch


def merge_basis(basis, patch):
    from ..schemas import DesignBasis
    data = basis.model_dump()
    for key, value in patch.items():
        if key in ("feed", "target", "column", "origin_tags"):
            data[key] = data[key] | value
        else:
            data[key] = value
    for key, value in patch.items():
        if key not in ("origin_tags", "design_id"):
            if isinstance(value, dict):
                for sub in value:
                    data["origin_tags"][f"{key}.{sub}"] = "provided"
            else:
                data["origin_tags"][key] = "provided"
    return DesignBasis.model_validate(data)
