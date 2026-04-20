import json
from collections import defaultdict

_HIGH_FANOUT_THRESHOLD = 25


def _build_net_index(netlist: dict) -> dict[str, list[dict]]:
    """Build reverse map: net_name -> [{refdes, pin, sheet}, ...]."""
    index: dict[str, list[dict]] = defaultdict(list)
    for refdes, comp in netlist.get("components", {}).items():
        sheet = comp.get("sheet", "")
        for pin_num, pin_obj in comp.get("pins", {}).items():
            net = pin_obj.get("net") if isinstance(pin_obj, dict) else pin_obj
            if net:
                index[net].append({"refdes": refdes, "pin": pin_num, "sheet": sheet})
    return index


def build_sheet_context(netlist: dict, sheet_name: str, variant_state) -> str:
    """Return JSON of components on the given sheet with DNP annotation, pin-to-net map,
    and cross-sheet connected_to neighbors for each non-power net."""
    components = netlist.get("components", {})
    net_index = _build_net_index(netlist)

    sheet_components = []

    for refdes, comp in components.items():
        if comp.get("sheet", "").lower() != sheet_name.lower():
            continue

        pins = {}
        for pin_num, pin_obj in comp.get("pins", {}).items():
            net = pin_obj.get("net") if isinstance(pin_obj, dict) else pin_obj
            base: dict = {"net": net}
            if isinstance(pin_obj, dict) and "name" in pin_obj:
                base["name"] = pin_obj["name"]

            all_pins = net_index.get(net, [])
            if len(all_pins) >= _HIGH_FANOUT_THRESHOLD:
                pins[pin_num] = {**base, "high_fanout": True, "fanout": len(all_pins)}
            else:
                neighbors = [
                    f"{p['refdes']}.{p['pin']} ({p['sheet']})"
                    for p in all_pins
                    if p["refdes"] != refdes
                ]
                pins[pin_num] = {**base, "connected_to": neighbors}

        sheet_components.append({
            "refdes": refdes,
            "mpn": comp.get("mpn"),
            "description": comp.get("description"),
            "value": comp.get("value"),
            "dnp": variant_state.is_dnp(refdes),
            "pins": pins,
        })

    sheet_components.sort(key=lambda c: c["refdes"])

    return json.dumps({
        "sheet": sheet_name,
        "component_count": len(sheet_components),
        "components": sheet_components,
    }, indent=2)
