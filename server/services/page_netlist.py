import re
from collections import defaultdict

_HIGH_FANOUT_THRESHOLD = 25
_PAGE_CHAR_BUDGET = 150_000
MAX_RESULT_SIZE_CHARS = 200_000


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


def _render_component(comp: dict, current_sheet: str) -> str:
    """Render one component as compact text lines.

    Format:
      REFDES|MPN|DESCRIPTION|VALUE [DNP]
        PIN_LABEL:NET→neighbor1,neighbor2,...
        PIN_LABEL:NET[HF:fanout]

    Same-sheet neighbors are shortened to refdes.pin; cross-sheet neighbors
    keep @sheet suffix so the caller knows where to look next.
    """
    refdes = comp["refdes"]
    mpn = comp.get("mpn") or ""
    desc = comp.get("description") or ""
    value = comp.get("value") or ""
    dnp_flag = " [DNP]" if comp.get("dnp") else ""

    lines = [f"{refdes}|{mpn}|{desc}|{value}{dnp_flag}"]

    for pin_num, pin in comp.get("pins", {}).items():
        net = pin.get("net", "")
        name = pin.get("name", "")
        label = f"{pin_num}({name})" if name and name != pin_num else pin_num

        if pin.get("high_fanout"):
            lines.append(f"  {label}:{net}[HF:{pin['fanout']}]")
        else:
            neighbors = []
            for n in pin.get("connected_to", []):
                m = re.match(r"(.+?) \((.+?)\)$", n)
                if m:
                    ref_part, sheet_part = m.group(1), m.group(2)
                    if sheet_part.lower() == current_sheet.lower():
                        neighbors.append(ref_part)
                    else:
                        neighbors.append(f"{ref_part}@{sheet_part}")
                else:
                    neighbors.append(n)
            nbr_str = ",".join(neighbors)
            lines.append(f"  {label}:{net}->{nbr_str}" if nbr_str else f"  {label}:{net}")

    return "\n".join(lines)


def build_sheet_context(netlist: dict, sheet_name: str, variant_state, offset: int = 0) -> str:
    """Return text of components on the given sheet with DNP annotation, pin-to-net map,
    and cross-sheet connected_to neighbors for each non-power net. Results are paginated
    by character budget — pass offset to retrieve subsequent pages."""
    offset = max(0, offset)
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

    total = len(sheet_components)

    if offset >= total and total > 0:
        return f"sheet:{sheet_name} total:{total} offset:{offset} has_more:False\nwarning:offset {offset} >= total {total}"

    # Fill page up to character budget; always include at least one component
    # so offset always advances even if a single component exceeds the budget.
    page_rendered = []
    page_chars = 0
    for comp in sheet_components[offset:]:
        rendered = _render_component(comp, sheet_name)
        if page_rendered and page_chars + len(rendered) > _PAGE_CHAR_BUDGET:
            break
        page_rendered.append(rendered)
        page_chars += len(rendered)

    next_offset = offset + len(page_rendered)
    has_more = next_offset < total

    header = f"sheet:{sheet_name} total:{total} offset:{offset} has_more:{has_more}"

    if has_more:
        remaining = total - next_offset
        header += (
            f"\nnext:get_sheet_context(sheet_name='{sheet_name}', offset={next_offset})"
            f" [{remaining} remaining]"
        )

    if page_chars > _PAGE_CHAR_BUDGET and page_rendered:
        first_refdes = page_rendered[0].split("|")[0]
        header += f"\nwarning:{first_refdes} exceeds page budget — use get_component instead"

    return header + "\n\n" + "\n\n".join(page_rendered)
