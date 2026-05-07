import json
import pytest
from parsers.prj_pcb import VariantDefinition, VariantState
from main import _get_sheet_context_impl


@pytest.fixture
def project():
    return {
        "name": "TestBoard",
        "root_dir": "C:/Projects/TestBoard",
        "prj_pcb_path": "C:/Projects/TestBoard/TestBoard.PrjPcb",
        "sheets": [
            {"name": "MCU", "path": "C:/Projects/TestBoard/MCU.SchDoc"},
            {"name": "Comms", "path": "C:/Projects/TestBoard/Comms.SchDoc"},
            {"name": "PowerSupply", "path": "C:/Projects/TestBoard/PowerSupply.SchDoc"},
        ],
    }


@pytest.fixture
def default_vs():
    return VariantState([VariantDefinition(name="Default")])


def test_get_sheet_by_name(sample_netlist, project, default_vs):
    result = _get_sheet_context_impl(project, sample_netlist, default_vs, "Comms", {})
    assert result.startswith("sheet:Comms ")
    component_lines = [ln for ln in result.splitlines() if ln and not ln.startswith(" ") and "|" in ln]
    refdes_list = [ln.split("|")[0] for ln in component_lines]
    assert set(refdes_list) == {"R45", "U2"}


def test_get_sheet_from_active_tab(sample_netlist, project, default_vs):
    altium_status = {"running": True, "active_tab": "Comms.SchDoc"}
    result = _get_sheet_context_impl(project, sample_netlist, default_vs, None, altium_status)
    assert result.startswith("sheet:Comms ")


def test_get_sheet_altium_not_running(sample_netlist, project, default_vs):
    altium_status = {"running": False}
    result = json.loads(_get_sheet_context_impl(project, sample_netlist, default_vs, None, altium_status))
    assert result["warning"] == "altium_not_running"


def test_get_sheet_active_tab_outside_project(sample_netlist, project, default_vs):
    altium_status = {"running": True, "active_tab": "OtherProject.SchDoc"}
    result = json.loads(_get_sheet_context_impl(project, sample_netlist, default_vs, None, altium_status))
    assert result["warning"] == "active_document_outside_project"
    assert result["active_filename"] == "OtherProject.SchDoc"


def test_get_sheet_by_name_not_found(sample_netlist, project, default_vs):
    result = json.loads(_get_sheet_context_impl(project, sample_netlist, default_vs, "Nonexistent", {}))
    assert result["error"] == "sheet_not_found"


def test_get_sheet_case_insensitive_name(sample_netlist, project, default_vs):
    result = _get_sheet_context_impl(project, sample_netlist, default_vs, "comms", {})
    assert result.startswith("sheet:Comms ")
