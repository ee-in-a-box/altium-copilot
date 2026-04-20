import json
import pytest
from parsers.prj_pcb import VariantDefinition, VariantState
from main import _get_component_impl


@pytest.fixture
def default_vs():
    return VariantState([VariantDefinition(name="Default")])


@pytest.fixture
def dnp_vs():
    return VariantState([VariantDefinition(name="Prod", dnp_refdes=["R45"])])


def test_get_component_found(sample_netlist, default_vs):
    result = json.loads(_get_component_impl(sample_netlist, default_vs, "R45"))
    assert result["refdes"] == "R45"
    assert result["mpn"] == "RC0402FR-0710KL"
    assert result["value"] == "10K"
    assert result["dnp"] is False
    assert "1" in result["pins"]
    assert result["pins"]["1"]["net"] == "MCU_UART_TX"


def test_get_component_not_found(sample_netlist, default_vs):
    result = json.loads(_get_component_impl(sample_netlist, default_vs, "Z99"))
    assert result["error"] == "component_not_found"


def test_get_component_case_insensitive(sample_netlist, default_vs):
    result = json.loads(_get_component_impl(sample_netlist, default_vs, "r45"))
    assert result["refdes"] == "R45"


def test_get_component_dnp_annotated(sample_netlist, dnp_vs):
    result = json.loads(_get_component_impl(sample_netlist, dnp_vs, "R45"))
    assert result["dnp"] is True


def test_get_component_not_dnp(sample_netlist, dnp_vs):
    result = json.loads(_get_component_impl(sample_netlist, dnp_vs, "U1"))
    assert result["dnp"] is False


def test_get_component_includes_sheet(sample_netlist, default_vs):
    result = json.loads(_get_component_impl(sample_netlist, default_vs, "R45"))
    assert "sheet" in result
    assert result["sheet"] == "Comms"


def test_get_component_sheet_u1(sample_netlist, default_vs):
    result = json.loads(_get_component_impl(sample_netlist, default_vs, "U1"))
    assert result["sheet"] == "MCU"
