"""Conservative explicit extraction; never silently supplies a design basis."""

import re

ALIASES = {
    "n-heptane": ("n-heptane", "heptane", "正庚烷"),
    "n-nonane": ("n-nonane", "nonane", "正壬烷"),
    "ethanol": ("ethanol", "乙醇"), "water": ("water", "水"),
}
CAS = {"n-heptane": "142-82-5", "n-nonane": "111-84-2", "ethanol": "64-17-5", "water": "7732-18-5"}


def route(message, has_state=False):
    text = message.lower()
    if any(word in text for word in ("电解质", "反应精馏", "固液", "vlle", "施工", "制造图")):
        return "UNSUPPORTED"
    if has_state and any(word in text for word in ("改为", "改成", "调整", "修改", "change", "update")):
        return "DESIGN_REVISION"
    if has_state and any(word in text for word in ("解释本次", "解释结果", "计算结果", "这个结果", "上次结果", "explain the result")):
        return "RESULT_EXPLANATION"
    if any(word in text for word in ("为什么", "是什么", "解释", "原理", "what is")):
        return "KNOWLEDGE_QA"
    if any(word in text for word in ("泡点", "vle", "相平衡曲线", "txy")) and "设计" not in text:
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
    pressure = re.search(r"(?:压力|pressure)[^\d]{0,10}(\d+(?:\.\d+)?)\s*(kpa|mpa|pa|bar)", text)
    if pressure is None and previous is not None:
        pressure = re.fullmatch(r"\s*(?:改为|改成|调整为|change to)\s*(\d+(?:\.\d+)?)\s*(kpa|mpa|pa|bar)[。.!]?\s*",text)
    if pressure:
        value, unit = float(pressure[1]), pressure[2]
        feed["pressure_kPa"] = value * {"kpa": 1, "mpa": 1000, "pa": .001, "bar": 100}[unit]
    elif "常压" in text or "atmospheric" in text:
        feed["pressure_kPa"] = 101.325  # explicitly named standard atmosphere
    flow = re.search(r"(?:进料(?:量)?|feed)[^\d]{0,10}(\d+(?:\.\d+)?)\s*(kmol/h|mol/s)", text)
    if flow:
        feed.update(flow=float(flow[1]), flow_unit=flow[2])
    z = re.search(r"(?:zf|摩尔分数|摩分)\s*[=:：为]?\s*(0?\.\d+)", text)
    if z:
        value = float(z[1]);feed.update(composition=[value, 1-value], composition_basis="mole_fraction")
    if "饱和液" in text or "泡点进料" in text or "saturated liquid" in text:
        feed["quality_q"] = 1
    if feed:
        patch["feed"] = feed
    target = {}
    for key, pattern in (("distillate_mole_fraction", r"(?:xd|塔顶(?:纯度)?|产品纯度)[^\d]{0,10}(0?\.\d+)"),
                         ("bottoms_mole_fraction", r"(?:xb|塔底)[^\d]{0,10}(0?\.\d+)"),
                         ("key_component_recovery", r"(?:回收率|recovery)[^\d]{0,10}(0?\.\d+)")):
        found = re.search(pattern, text)
        if found:
            target[key] = float(found[1])
    if target:
        patch["target"] = target
    reflux = re.search(r"(?:回流比|reflux ratio)[^\d]{0,10}(\d+(?:\.\d+)?)", text)
    if reflux:
        patch["column"] = {"reflux_ratio": float(reflux[1])}
    if "raoult" in text:
        patch["thermodynamic_model"] = "Raoult"
    elif 'nrtl' in text:
        patch['thermodynamic_model'] = 'NRTL'
    if '自主' in text or 'autonomous' in text:
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
