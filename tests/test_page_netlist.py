import json
from parsers.prj_pcb import VariantDefinition, VariantState
from services.page_netlist import build_sheet_context


def test_filters_components_by_sheet(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result = json.loads(build_sheet_context(sample_netlist, "Comms", vs))
    refdes_list = [c["refdes"] for c in result["components"]]
    assert set(refdes_list) == {"R45", "U2"}
    assert result["sheet"] == "Comms"
    assert result["component_count"] == 2


def test_filters_components_powersupply_sheet(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result = json.loads(build_sheet_context(sample_netlist, "PowerSupply", vs))
    refdes_list = [c["refdes"] for c in result["components"]]
    assert refdes_list == ["C1"]


def test_sheet_match_is_case_insensitive(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result = json.loads(build_sheet_context(sample_netlist, "comms", vs))
    assert result["component_count"] == 2


def test_dnp_annotation(sample_netlist):
    vs = VariantState([VariantDefinition(name="Prod", dnp_refdes=["R45"])])
    result = json.loads(build_sheet_context(sample_netlist, "Comms", vs))
    by_refdes = {c["refdes"]: c for c in result["components"]}
    assert by_refdes["R45"]["dnp"] is True
    assert by_refdes["U2"]["dnp"] is False


def test_pins_included_in_output(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result = json.loads(build_sheet_context(sample_netlist, "Comms", vs))
    by_refdes = {c["refdes"]: c for c in result["components"]}
    assert "pins" in by_refdes["R45"]
    assert by_refdes["R45"]["pins"]["1"]["net"] == "MCU_UART_TX"
    assert by_refdes["U2"]["pins"]["RX"]["net"] == "USB_UART_RX"


def test_components_sorted_by_refdes(sample_netlist):
    vs = VariantState([VariantDefinition(name="Default")])
    result = json.loads(build_sheet_context(sample_netlist, "Comms", vs))
    refdes_list = [c["refdes"] for c in result["components"]]
    assert refdes_list == sorted(refdes_list)
