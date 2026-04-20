# tests/test_search_components.py
import json
from main import _search_components_impl


def test_search_by_description(sample_netlist):
    result = json.loads(_search_components_impl(sample_netlist, "10K", "description"))
    refdes_all = [r for g in result["results"] for r in g["refdes"]]
    assert "R45" in refdes_all


def test_search_by_mpn(sample_netlist):
    result = json.loads(_search_components_impl(sample_netlist, "CH340", "mpn"))
    refdes_all = [r for g in result["results"] for r in g["refdes"]]
    assert "U2" in refdes_all


def test_search_by_refdes(sample_netlist):
    result = json.loads(_search_components_impl(sample_netlist, "^U", "refdes"))
    refdes_all = [r for g in result["results"] for r in g["refdes"]]
    assert "U1" in refdes_all
    assert "U2" in refdes_all
    assert "R45" not in refdes_all


def test_search_invalid_regex(sample_netlist):
    result = json.loads(_search_components_impl(sample_netlist, "[invalid", "description"))
    assert result["error"] == "invalid_pattern"


def test_search_invalid_search_by(sample_netlist):
    result = json.loads(_search_components_impl(sample_netlist, "10K", "unknown_field"))
    assert result["error"] == "invalid_search_by"


def test_search_matches_all_returns_error(sample_netlist):
    result = json.loads(_search_components_impl(sample_netlist, ".", "description"))
    assert result["error"] == "too_many_matches"


def test_search_groups_same_mpn(sample_netlist):
    # Add a second component with the same MPN as R45
    sample_netlist["components"]["R46"] = {
        "mpn": "RC0402FR-0710KL", "description": "RES 10K OHM",
        "value": "10K", "sheet": "Comms", "pins": {}
    }
    result = json.loads(_search_components_impl(sample_netlist, "10K", "description"))
    group = next(g for g in result["results"] if g["mpn"] == "RC0402FR-0710KL")
    assert group["count"] == 2
    assert set(group["refdes"]) == {"R45", "R46"}


def test_search_mixed_values_null(sample_netlist):
    sample_netlist["components"]["R46"] = {
        "mpn": "RC0402FR-0710KL", "description": "RES 10K OHM",
        "value": "4K7", "sheet": "Comms", "pins": {}
    }
    result = json.loads(_search_components_impl(sample_netlist, "RES 10K OHM", "description"))
    group = next(g for g in result["results"] if g["mpn"] == "RC0402FR-0710KL")
    assert group["value"] is None
