from server.altium import enrich_netlist
from server.parsers.sch_doc import ComponentMeta


def _base_netlist():
    return {
        "nets": {"3V3": [("C1", "1")]},
        "pin_to_net": {"C1": {"1": "3V3"}, "U1": {"VCC": "3V3"}},
    }


def test_sheet_field_added_from_map():
    netlist = _base_netlist()
    components = {
        "C1": ComponentMeta(refdes="C1", mpn="CAP001", description="100nF cap"),
        "U1": ComponentMeta(refdes="U1", mpn="STM32", description="MCU"),
    }
    refdes_to_sheet = {"C1": "PowerSupply", "U1": "MCU"}
    enrich_netlist(netlist, components, refdes_to_sheet)
    assert netlist["components"]["C1"]["sheet"] == "PowerSupply"
    assert netlist["components"]["U1"]["sheet"] == "MCU"


def test_sheet_field_empty_when_no_map():
    netlist = _base_netlist()
    components = {"C1": ComponentMeta(refdes="C1", mpn="CAP001", description="100nF cap")}
    enrich_netlist(netlist, components)
    assert netlist["components"]["C1"]["sheet"] == ""


def test_sheet_field_on_unconnected_component():
    netlist = {"nets": {}, "pin_to_net": {}}
    components = {"F1": ComponentMeta(refdes="F1", mpn="FUSE1A", description="Fuse 1A")}
    refdes_to_sheet = {"F1": "PowerSupply"}
    enrich_netlist(netlist, components, refdes_to_sheet)
    assert netlist["components"]["F1"]["sheet"] == "PowerSupply"
