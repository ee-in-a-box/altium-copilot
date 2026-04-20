from server.altium import enrich_netlist
from server.parsers.sch_doc import ComponentMeta


def make_netlist():
    return {
        "nets": {
            "BUZZER_1": [("Q18", "3"), ("R208", "1")],
            "GND": [("Q18", "4"), ("R208", "2")],
        },
        "pin_to_net": {
            "Q18":  {"3": "BUZZER_1", "4": "GND"},
            "R208": {"1": "BUZZER_1", "2": "GND"},
        },
    }


def test_enriched_component_has_mpn():
    netlist = make_netlist()
    components = {
        "Q18":  ComponentMeta(refdes="Q18",  mpn="BUK6D77-60EX", description="N-FET"),
        "R208": ComponentMeta(refdes="R208", mpn="ERJ-2RKF1002X", description="10k Resistor"),
    }
    result = enrich_netlist(netlist, components)
    assert result["components"]["Q18"]["mpn"] == "BUK6D77-60EX"
    assert result["components"]["R208"]["mpn"] == "ERJ-2RKF1002X"


def test_enriched_pins_have_net():
    netlist = make_netlist()
    components = {
        "Q18": ComponentMeta(refdes="Q18", pins={"3": "GATE", "4": "GND_PIN"}),
    }
    result = enrich_netlist(netlist, components)
    pins = result["components"]["Q18"]["pins"]
    assert pins["3"]["net"] == "BUZZER_1"
    assert pins["3"]["name"] == "GATE"
    assert pins["4"]["net"] == "GND"
    assert pins["4"]["name"] == "GND_PIN"


def test_pin_without_name_gets_empty_string():
    netlist = make_netlist()
    # R208 has no named pins (passive)
    components = {
        "R208": ComponentMeta(refdes="R208", pins={}),
    }
    result = enrich_netlist(netlist, components)
    pins = result["components"]["R208"]["pins"]
    assert pins["1"]["name"] == ""
    assert pins["2"]["name"] == ""


def test_refdes_in_net_but_not_schdoc_excluded():
    netlist = make_netlist()
    components = {}  # no SchDoc data — .NET-only components get no entry
    result = enrich_netlist(netlist, components)
    assert "Q18" not in result.get("components", {})


def test_refdes_in_schdoc_but_not_net_included_with_empty_pins():
    # Components with no net connections (chassis fuses, mounting holes, etc.)
    # are still included so Claude can answer BOM questions about them.
    netlist = make_netlist()
    components = {
        "Q18":  ComponentMeta(refdes="Q18",  mpn="BUK6D77-60EX"),
        "F1":   ComponentMeta(refdes="F1",   mpn="8020.5021.G", description="Fuse 10A"),
    }
    result = enrich_netlist(netlist, components)
    assert "F1" in result["components"]
    assert result["components"]["F1"]["mpn"] == "8020.5021.G"
    assert result["components"]["F1"]["pins"] == {}


def test_existing_netlist_keys_preserved():
    netlist = make_netlist()
    components = {"Q18": ComponentMeta(refdes="Q18")}
    result = enrich_netlist(netlist, components)
    assert "nets" in result
    assert "pin_to_net" in result


def test_subsheet_fanout_creates_entry_per_suffix():
    # C1 appears as C1A and C1B in the .NET (two subsheet instances).
    # The SchDoc has only the bare refdes C1.
    netlist = {
        "nets": {"VCC": [("C1A", "1"), ("C1B", "1")]},
        "pin_to_net": {
            "C1A": {"1": "VCC", "2": "GND"},
            "C1B": {"1": "VCC", "2": "GND"},
        },
    }
    components = {
        "C1": ComponentMeta(refdes="C1", mpn="GRM188R71H104KA93D", description="CAP 100NF"),
    }
    result = enrich_netlist(netlist, components)
    assert "C1A" in result["components"]
    assert "C1B" in result["components"]
    assert "C1" not in result["components"]
    assert result["components"]["C1A"]["mpn"] == "GRM188R71H104KA93D"
    assert result["components"]["C1B"]["mpn"] == "GRM188R71H104KA93D"
    assert result["components"]["C1A"]["pins"]["1"] == {"name": "", "net": "VCC"}


def test_subsheet_fanout_no_false_positives():
    # C1 suffix search must not match C10, C11 — only exact single-letter suffix.
    # C1 itself has no .NET entry so it appears as an unconnected component.
    netlist = {
        "nets": {},
        "pin_to_net": {
            "C10": {"1": "VCC", "2": "GND"},
            "C11": {"1": "VCC", "2": "GND"},
        },
    }
    components = {
        "C1": ComponentMeta(refdes="C1", mpn="GRM188R71H104KA93D"),
    }
    result = enrich_netlist(netlist, components)
    # C1 appears as unconnected (no .NET match, no suffix match)
    assert result["components"]["C1"]["pins"] == {}
    # C10/C11 are in .NET but not in SchDoc — they must not appear
    assert "C10" not in result["components"]
    assert "C11" not in result["components"]
