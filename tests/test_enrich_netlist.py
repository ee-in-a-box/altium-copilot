from server.altium import enrich_netlist
from server.parsers.sch_doc import ComponentMeta


def _meta(refdes: str) -> ComponentMeta:
    return ComponentMeta(refdes=refdes, mpn="MPN", description="desc")


def _netlist(*refdes_list: str) -> dict:
    """Build a minimal netlist where each refdes has pin 1 on net NET."""
    pin_to_net = {r: {"1": "NET"} for r in refdes_list}
    return {"nets": {"NET": [(r, "1") for r in refdes_list]}, "pin_to_net": pin_to_net}


# ---------- basic ----------

def test_direct_match():
    netlist = _netlist("C1", "U1")
    enrich_netlist(netlist, {"C1": _meta("C1"), "U1": _meta("U1")})
    assert "C1" in netlist["components"]
    assert "U1" in netlist["components"]
    assert netlist["components"]["C1"]["pins"]["1"]["net"] == "NET"


def test_sheet_field_added_from_map():
    netlist = _netlist("C1", "U1")
    enrich_netlist(netlist, {"C1": _meta("C1"), "U1": _meta("U1")},
                   {"C1": "PowerSupply", "U1": "MCU"})
    assert netlist["components"]["C1"]["sheet"] == "PowerSupply"
    assert netlist["components"]["U1"]["sheet"] == "MCU"


def test_sheet_field_empty_when_no_map():
    netlist = _netlist("C1")
    enrich_netlist(netlist, {"C1": _meta("C1")})
    assert netlist["components"]["C1"]["sheet"] == ""


def test_unconnected_component_included():
    netlist = {"nets": {}, "pin_to_net": {}}
    enrich_netlist(netlist, {"F1": _meta("F1")}, {"F1": "PowerSupply"})
    assert netlist["components"]["F1"]["sheet"] == "PowerSupply"
    assert netlist["components"]["F1"]["pins"] == {}


# ---------- subsheet fan-out suffix styles ----------

def test_suffix_single_letter():
    """C1 in SchDoc → C1A, C1B in netlist (direct letter suffix)."""
    netlist = _netlist("C1A", "C1B")
    enrich_netlist(netlist, {"C1": _meta("C1")})
    assert "C1A" in netlist["components"]
    assert "C1B" in netlist["components"]
    assert "C1" not in netlist["components"]


def test_suffix_underscore_letter():
    """C1 in SchDoc → C1_A, C1_B in netlist."""
    netlist = _netlist("C1_A", "C1_B")
    enrich_netlist(netlist, {"C1": _meta("C1")})
    assert "C1_A" in netlist["components"]
    assert "C1_B" in netlist["components"]


def test_suffix_underscore_letter_digit():
    """C1 in SchDoc → C1_A1, C1_B2 in netlist."""
    netlist = _netlist("C1_A1", "C1_B2")
    enrich_netlist(netlist, {"C1": _meta("C1")})
    assert "C1_A1" in netlist["components"]
    assert "C1_B2" in netlist["components"]


def test_suffix_dot_letter():
    """C1 in SchDoc → C1.A, C1.B in netlist."""
    netlist = _netlist("C1.A", "C1.B")
    enrich_netlist(netlist, {"C1": _meta("C1")})
    assert "C1.A" in netlist["components"]
    assert "C1.B" in netlist["components"]


def test_suffix_letter_multi_digits():
    """C1 in SchDoc → C1A12 (letter + multiple digits)."""
    netlist = _netlist("C1A12", "C1B3")
    enrich_netlist(netlist, {"C1": _meta("C1")})
    assert "C1A12" in netlist["components"]
    assert "C1B3" in netlist["components"]


# ---------- disambiguation: C1 must not absorb C10 ----------

def test_c10_not_matched_as_c1_suffix():
    """C10 in netlist is NOT a suffixed variant of C1."""
    netlist = _netlist("C10")
    enrich_netlist(netlist, {"C1": _meta("C1"), "C10": _meta("C10")})
    # C1 has no connections → falls through to unconnected path
    assert "C1" in netlist["components"]
    assert netlist["components"]["C1"]["pins"] == {}
    # C10 matches directly
    assert "C10" in netlist["components"]
    assert netlist["components"]["C10"]["pins"]["1"]["net"] == "NET"


def test_c10_suffix_not_confused_with_c1():
    """C10_A should only be picked up by C10, not by C1."""
    netlist = _netlist("C10_A")
    enrich_netlist(netlist, {"C1": _meta("C1"), "C10": _meta("C10")})
    assert "C10_A" in netlist["components"]
    # C1 should NOT have absorbed C10_A
    assert "C1" in netlist["components"]
    assert netlist["components"]["C1"]["pins"] == {}


def test_numeric_only_suffix_not_matched():
    """C11 in netlist is not a suffix of C1 — purely numeric."""
    netlist = _netlist("C11")
    enrich_netlist(netlist, {"C1": _meta("C1"), "C11": _meta("C11")})
    assert "C1" in netlist["components"]
    assert netlist["components"]["C1"]["pins"] == {}
    assert "C11" in netlist["components"]
    assert netlist["components"]["C11"]["pins"]["1"]["net"] == "NET"


# ---------- sheet propagated to all suffixed variants ----------

def test_sheet_propagated_to_suffixed_variants():
    netlist = _netlist("C1_A", "C1_B")
    enrich_netlist(netlist, {"C1": _meta("C1")}, {"C1": "SubPage"})
    assert netlist["components"]["C1_A"]["sheet"] == "SubPage"
    assert netlist["components"]["C1_B"]["sheet"] == "SubPage"


# ---------- large refdes numbers ----------

def test_high_refdes_number_suffix():
    """R100_A should be matched as R100 suffix, not confused with anything."""
    netlist = _netlist("R100_A", "R100_B")
    enrich_netlist(netlist, {"R100": _meta("R100")})
    assert "R100_A" in netlist["components"]
    assert "R100_B" in netlist["components"]


# ---------- >26 instances: multi-letter suffix ----------

def test_suffix_multi_letter_aa():
    """C1_AA, C1_AB for >26 subsheet instances."""
    netlist = _netlist("C1_AA", "C1_AB")
    enrich_netlist(netlist, {"C1": _meta("C1")})
    assert "C1_AA" in netlist["components"]
    assert "C1_AB" in netlist["components"]


# ---------- lowercase suffix ----------

def test_suffix_lowercase_letter():
    """C1_a — lowercase suffix treated the same as uppercase."""
    netlist = _netlist("C1_a", "C1_b")
    enrich_netlist(netlist, {"C1": _meta("C1")})
    assert "C1_a" in netlist["components"]
    assert "C1_b" in netlist["components"]


# ---------- hyphen separator ----------

def test_suffix_hyphen_letter():
    """C1-A — hyphen as separator."""
    netlist = _netlist("C1-A", "C1-B")
    enrich_netlist(netlist, {"C1": _meta("C1")})
    assert "C1-A" in netlist["components"]
    assert "C1-B" in netlist["components"]
