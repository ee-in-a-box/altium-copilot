# tests/test_search_nets.py
import json
from main import _search_nets_impl


def test_search_nets_basic_match(sample_netlist):
    result = json.loads(_search_nets_impl(sample_netlist, "UART"))
    assert result["match_count"] == 2
    names = [n["net"] for n in result["nets"]]
    assert "MCU_UART_TX" in names
    assert "USB_UART_RX" in names


def test_search_nets_single_match(sample_netlist):
    result = json.loads(_search_nets_impl(sample_netlist, "MCU"))
    assert result["match_count"] == 1
    assert result["nets"][0]["net"] == "MCU_UART_TX"


def test_search_nets_returns_pins_inline(sample_netlist):
    result = json.loads(_search_nets_impl(sample_netlist, "MCU_UART_TX"))
    net = result["nets"][0]
    assert net["pin_count"] == 2
    pins = {(p["refdes"], p["pin"]) for p in net["pins"]}
    assert pins == {("U1", "PA9"), ("R45", "1")}


def test_search_nets_case_insensitive(sample_netlist):
    result = json.loads(_search_nets_impl(sample_netlist, "uart"))
    assert result["match_count"] == 2


def test_search_nets_no_match(sample_netlist):
    result = json.loads(_search_nets_impl(sample_netlist, "SPI"))
    assert result["match_count"] == 0
    assert result["nets"] == []


def test_search_nets_invalid_regex(sample_netlist):
    result = json.loads(_search_nets_impl(sample_netlist, "[invalid"))
    assert result["error"] == "invalid_pattern"


def test_search_nets_too_many_matches(sample_netlist):
    # "." matches all 4 nets — but threshold is 50, so we need to fabricate a large netlist
    big_netlist = {
        "nets": {f"NET_{i}": [(f"R{i}", "1")] for i in range(51)},
        "pin_to_net": {},
        "components": {},
    }
    result = json.loads(_search_nets_impl(big_netlist, "."))
    assert result["error"] == "too_many_matches"


def test_search_nets_pipe_pattern(sample_netlist):
    result = json.loads(_search_nets_impl(sample_netlist, "3V3|GND"))
    names = {n["net"] for n in result["nets"]}
    assert names == {"3V3", "GND"}
