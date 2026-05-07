from parsers.prj_pcb import VariantDefinition, VariantState
from services.page_netlist import build_sheet_context


def _refdes_list(output: str) -> list[str]:
    """Extract refdes values in output order (component header lines only)."""
    return [
        line.split("|")[0]
        for line in output.split("\n")
        if "|" in line and not line.startswith(" ")
    ]


def _component_block(output: str, refdes: str) -> str:
    """Extract the text block for a specific component."""
    lines = output.split("\n")
    block, in_comp = [], False
    for line in lines:
        if line.startswith(f"{refdes}|"):
            in_comp = True
        elif in_comp and line and not line.startswith(" "):
            break
        if in_comp:
            block.append(line)
    return "\n".join(block)


def test_filters_components_by_sheet(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result = build_sheet_context(sample_netlist, "Comms", vs)
    assert set(_refdes_list(result)) == {"R45", "U2"}
    assert "sheet:Comms" in result
    assert "total:2" in result


def test_filters_components_powersupply_sheet(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result = build_sheet_context(sample_netlist, "PowerSupply", vs)
    assert _refdes_list(result) == ["C1"]


def test_sheet_match_is_case_insensitive(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result = build_sheet_context(sample_netlist, "comms", vs)
    assert "total:2" in result


def test_dnp_annotation(sample_netlist):
    vs = VariantState([VariantDefinition(name="Prod", dnp_refdes=["R45"])])
    result = build_sheet_context(sample_netlist, "Comms", vs)
    assert "[DNP]" in _component_block(result, "R45")
    assert "[DNP]" not in _component_block(result, "U2")


def test_pins_included_in_output(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result = build_sheet_context(sample_netlist, "Comms", vs)
    r45 = _component_block(result, "R45")
    u2 = _component_block(result, "U2")
    assert "MCU_UART_TX" in r45
    assert "USB_UART_RX" in u2


def test_components_sorted_by_refdes(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result = build_sheet_context(sample_netlist, "Comms", vs)
    refs = _refdes_list(result)
    assert refs == sorted(refs)


def test_pagination_offset_zero_default(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result_default = build_sheet_context(sample_netlist, "Comms", vs)
    result_explicit = build_sheet_context(sample_netlist, "Comms", vs, offset=0)
    assert result_default == result_explicit


def test_pagination_has_more_and_second_page(monkeypatch):
    import services.page_netlist as pn
    monkeypatch.setattr(pn, "_PAGE_CHAR_BUDGET", 1)  # force every component onto its own page
    vs = VariantState([VariantDefinition(name="Default")])
    # Comms sheet has R45, U2 — budget of 1 forces has_more=True on first call
    page1 = build_sheet_context({"nets": {}, "pin_to_net": {}, "components": {
        "R45": {"mpn": "", "description": "", "value": "", "sheet": "Comms", "pins": {}},
        "U2":  {"mpn": "", "description": "", "value": "", "sheet": "Comms", "pins": {}},
    }}, "Comms", vs, offset=0)
    assert "has_more:True" in page1
    assert "total:2" in page1
    refs1 = _refdes_list(page1)
    assert len(refs1) == 1  # only one component fits per page

    page2 = build_sheet_context({"nets": {}, "pin_to_net": {}, "components": {
        "R45": {"mpn": "", "description": "", "value": "", "sheet": "Comms", "pins": {}},
        "U2":  {"mpn": "", "description": "", "value": "", "sheet": "Comms", "pins": {}},
    }}, "Comms", vs, offset=1)
    assert "has_more:False" in page2
    refs2 = _refdes_list(page2)
    assert len(refs2) == 1
    assert refs1[0] != refs2[0]  # different component on each page
    assert set(refs1 + refs2) == {"R45", "U2"}


def test_pagination_offset_out_of_bounds(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result = build_sheet_context(sample_netlist, "Comms", vs, offset=100)
    assert "has_more:False" in result
    assert "warning" in result
    assert "100" in result


def test_pagination_negative_offset_clamped(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result_neg = build_sheet_context(sample_netlist, "Comms", vs, offset=-5)
    result_zero = build_sheet_context(sample_netlist, "Comms", vs, offset=0)
    assert result_neg == result_zero
