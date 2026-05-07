# tests/test_query_net.py
import json
from main import _query_net_impl


def test_exact_match(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "MCU_UART_TX"))
    assert result["net"] == "MCU_UART_TX"
    pins = {(p["refdes"], p["pin"]) for p in result["pins"]}
    assert pins == {("U1", "PA9"), ("R45", "1")}


def test_exact_match_case_insensitive(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "mcu_uart_tx"))
    assert result["net"] == "MCU_UART_TX"


def test_regex_match_multiple(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "UART"))
    assert result["match_count"] == 2
    names = [n["net"] for n in result["nets"]]
    assert "MCU_UART_TX" in names
    assert "USB_UART_RX" in names


def test_regex_match_single_unwrapped(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "MCU"))
    assert result["net"] == "MCU_UART_TX"
    assert "pins" in result


def test_regex_pipe_pattern(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "3V3|GND"))
    names = {n["net"] for n in result["nets"]}
    assert names == {"3V3", "GND"}


def test_regex_case_insensitive(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "uart"))
    assert result["match_count"] == 2


def test_pins_inline(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "MCU_UART_TX"))
    assert result["pin_count"] == 2
    pins = {(p["refdes"], p["pin"]) for p in result["pins"]}
    assert pins == {("U1", "PA9"), ("R45", "1")}


def test_no_neighbors_in_result(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "MCU_UART_TX"))
    assert "neighbors" not in result


def test_not_found(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "DOES_NOT_EXIST"))
    assert result["error"] == "net_not_found"


def test_no_regex_match(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "SPI"))
    assert result["error"] == "net_not_found"


def test_invalid_regex_no_exact_match(sample_netlist):
    # Bad regex with no matching net name → net_not_found (exact-match fallback also fails)
    result = json.loads(_query_net_impl(sample_netlist, "[invalid"))
    assert result["error"] == "net_not_found"


def test_invalid_regex_with_exact_match():
    # Bad regex but there IS a net with that exact name — should return the net
    nl = {
        "nets": {"+5V": [("U1", "VCC")], "GND": [("U1", "GND")]},
        "pin_to_net": {},
        "components": {},
    }
    result = json.loads(_query_net_impl(nl, "+5V"))
    assert result["net"] == "+5V"
    assert result["pins"] == [{"refdes": "U1", "pin": "VCC"}]


def test_metacharacter_net_names():
    # Common PCB power rail names that are invalid regex but should resolve via exact match
    nl = {
        "nets": {
            "+3V3": [("U1", "VIN")],
            "+12V": [("J1", "1")],
            "VIN[0]": [("IC1", "A")],
        },
        "pin_to_net": {},
        "components": {},
    }
    for name in ["+3V3", "+12V", "VIN[0]"]:
        result = json.loads(_query_net_impl(nl, name))
        assert result.get("net") == name, f"Expected exact match for '{name}', got {result}"


def test_regex_discovery_not_blocked_by_exact_match(sample_netlist):
    # 'GND' as regex should still match all GND-related nets even if one is named 'GND'
    # (discovery use case — regex path is tried first)
    result = json.loads(_query_net_impl(sample_netlist, "GND"))
    # sample_netlist has a net named exactly 'GND'; regex 'GND' also matches 'GND'
    assert result["net"] == "GND"  # single regex match, unwrapped


def test_too_many_matches(sample_netlist):
    big_netlist = {
        "nets": {f"NET_{i}": [(f"R{i}", "1")] for i in range(51)},
        "pin_to_net": {},
        "components": {},
    }
    result = json.loads(_query_net_impl(big_netlist, "."))
    assert result["error"] == "too_many_matches"


def test_empty_net(sample_netlist):
    sample_netlist["nets"]["ORPHAN"] = []
    result = json.loads(_query_net_impl(sample_netlist, "ORPHAN"))
    assert result["pins"] == []
    assert "neighbors" not in result


def _make_high_fanout_netlist():
    connections = [(f"R{i}", "1") for i in range(30)]
    return {
        "nets": {
            "POWER_RAIL": connections,
            "SIG": [("R0", "2")],
        },
        "pin_to_net": {},
        "components": {},
    }


def test_high_fanout_warning(sample_netlist):
    nl = _make_high_fanout_netlist()
    result = json.loads(_query_net_impl(nl, "POWER_RAIL"))
    assert result["warning"] == "high_fanout"
    assert result["pin_count"] == 30
    assert "pins_sample" in result
    assert len(result["pins_sample"]) <= 10
    assert "neighbors_sample" not in result


def test_high_fanout_message(sample_netlist):
    nl = _make_high_fanout_netlist()
    result = json.loads(_query_net_impl(nl, "POWER_RAIL"))
    assert "30 connections" in result["message"]


def test_at_threshold_returns_full():
    connections = [(f"R{i}", "1") for i in range(25)]
    nl = {
        "nets": {"BORDERLINE": connections},
        "pin_to_net": {},
        "components": {},
    }
    result = json.loads(_query_net_impl(nl, "BORDERLINE"))
    assert "warning" not in result
    assert result["net"] == "BORDERLINE"
    assert len(result["pins"]) == 25
