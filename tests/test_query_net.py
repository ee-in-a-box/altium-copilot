# tests/test_query_net.py
import json
from main import _query_net_impl


def test_query_net_found(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "MCU_UART_TX"))
    assert result["net"] == "MCU_UART_TX"
    pins = {(p["refdes"], p["pin"]) for p in result["pins"]}
    assert pins == {("U1", "PA9"), ("R45", "1")}


def test_query_net_not_found(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "DOES_NOT_EXIST"))
    assert result["error"] == "net_not_found"


def test_query_net_case_insensitive(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "mcu_uart_tx"))
    assert result["net"] == "MCU_UART_TX"


def test_query_net_neighbors(sample_netlist):
    result = json.loads(_query_net_impl(sample_netlist, "MCU_UART_TX"))
    # R45 pin 1 is on MCU_UART_TX, R45 pin 2 is on USB_UART_RX → neighbor
    neighbor_nets = {n["connects_to_net"] for n in result["neighbors"]}
    assert "USB_UART_RX" in neighbor_nets


def test_query_net_returns_no_pins_when_empty(sample_netlist):
    sample_netlist["nets"]["ORPHAN"] = []
    sample_netlist["pin_to_net"] = {}
    result = json.loads(_query_net_impl(sample_netlist, "ORPHAN"))
    assert result["pins"] == []
    assert result["neighbors"] == []


def _make_high_fanout_netlist():
    """30-pin POWER_RAIL net + one small signal net SIG."""
    connections = [(f"R{i}", "1") for i in range(30)]
    return {
        "nets": {
            "POWER_RAIL": connections,
            "SIG": [("R0", "2")],
        },
        "pin_to_net": {
            **{f"R{i}": {"1": "POWER_RAIL"} for i in range(1, 30)},
            "R0": {"1": "POWER_RAIL", "2": "SIG"},
        },
        "components": {},
    }


def test_query_net_high_fanout_returns_warning():
    nl = _make_high_fanout_netlist()
    result = json.loads(_query_net_impl(nl, "POWER_RAIL"))
    assert result["warning"] == "high_fanout"
    assert result["pin_count"] == 30
    assert "pins_sample" in result
    assert len(result["pins_sample"]) <= 10
    assert "neighbors_sample" in result


def test_query_net_high_fanout_has_message():
    nl = _make_high_fanout_netlist()
    result = json.loads(_query_net_impl(nl, "POWER_RAIL"))
    assert "30 connections" in result["message"]


def test_query_net_at_threshold_returns_full():
    """Exactly 25 pins — should NOT trigger the guard."""
    connections = [(f"R{i}", "1") for i in range(25)]
    nl = {
        "nets": {"BORDERLINE": connections},
        "pin_to_net": {f"R{i}": {"1": "BORDERLINE"} for i in range(25)},
        "components": {},
    }
    result = json.loads(_query_net_impl(nl, "BORDERLINE"))
    assert "warning" not in result
    assert result["net"] == "BORDERLINE"
    assert len(result["pins"]) == 25
