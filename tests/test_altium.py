import json
import pytest
from unittest.mock import patch
from server.altium import AltiumClient


def test_get_status_returns_not_running_when_script_says_so():
    client = AltiumClient()
    with patch("server.altium._run_ps", return_value='{"running": false}'):
        result = client.get_status()
    assert result == {"running": False}


def test_get_status_returns_project_and_tab_when_altium_is_running():
    payload = {"running": True, "project_file": "MyProject.PrjPcb", "project_path": "C:/Projects/MyProject.PrjPcb", "active_tab": "PowerSupply.SchDoc"}
    client = AltiumClient()
    with patch("server.altium._run_ps", return_value=json.dumps(payload)):
        result = client.get_status()
    assert result["running"] is True
    assert result["project_file"] == "MyProject.PrjPcb"
    assert result["active_tab"] == "PowerSupply.SchDoc"


def test_get_status_raises_when_script_fails():
    client = AltiumClient()
    with patch("server.altium._run_ps", side_effect=RuntimeError("get_altium_status.ps1 failed")):
        with pytest.raises(RuntimeError):
            client.get_status()


# --- tab_type classification ---

def test_schematic_tab_classified_correctly():
    payload = {"running": True, "project_file": "MyProject.PrjPcb", "project_path": "", "active_tab": "PowerSupply.SchDoc"}
    client = AltiumClient()
    with patch("server.altium._run_ps", return_value=json.dumps(payload)):
        result = client.get_status()
    assert result["tab_type"] == "schematic"


def test_pcb_tab_classified_correctly():
    payload = {"running": True, "project_file": "MyProject.PrjPcb", "project_path": "", "active_tab": "MyProject.PcbDoc"}
    client = AltiumClient()
    with patch("server.altium._run_ps", return_value=json.dumps(payload)):
        result = client.get_status()
    assert result["tab_type"] == "pcb"


def test_other_tab_classified_correctly():
    payload = {"running": True, "project_file": "MyProject.PrjPcb", "project_path": "", "active_tab": "Home Page"}
    client = AltiumClient()
    with patch("server.altium._run_ps", return_value=json.dumps(payload)):
        result = client.get_status()
    assert result["tab_type"] == "other"


# --- empty project_file warning ---

def test_warning_added_when_project_file_is_empty():
    payload = {"running": True, "project_file": "", "project_path": "", "active_tab": "PowerSupply.SchDoc"}
    client = AltiumClient()
    with patch("server.altium._run_ps", return_value=json.dumps(payload)):
        result = client.get_status()
    assert result["warning"] == "no_sheet_open"


def test_no_warning_when_project_file_is_present():
    payload = {"running": True, "project_file": "MyProject.PrjPcb", "project_path": "", "active_tab": "PowerSupply.SchDoc"}
    client = AltiumClient()
    with patch("server.altium._run_ps", return_value=json.dumps(payload)):
        result = client.get_status()
    assert "warning" not in result


# --- validate_active_document ---

from server.altium import validate_active_document

SHEET_PATHS = [
    "C:/Projects/MyProject/PowerSupply.SchDoc",
    "C:/Projects/MyProject/MCU.SchDoc",
]
PRJ_PCB = "C:/Projects/MyProject/MyProject.PrjPcb"
PROJECT_ROOT = "C:/Projects/MyProject"


def test_validate_returns_tab_when_everything_matches():
    status = {"running": True, "project_file": "MyProject.PrjPcb", "active_tab": "PowerSupply.SchDoc", "tab_type": "schematic"}
    result = validate_active_document(status, PROJECT_ROOT, PRJ_PCB, SHEET_PATHS)
    assert result == "PowerSupply.SchDoc"


def test_validate_warns_when_altium_not_running():
    status = {"running": False}
    result = validate_active_document(status, PROJECT_ROOT, PRJ_PCB, SHEET_PATHS)
    assert result["warning"] == "altium_not_running"


def test_validate_warns_when_project_mismatch():
    status = {"running": True, "project_file": "OtherProject.PrjPcb", "active_tab": "PowerSupply.SchDoc", "tab_type": "schematic"}
    result = validate_active_document(status, PROJECT_ROOT, PRJ_PCB, SHEET_PATHS)
    assert result["warning"] == "active_document_outside_project"


def test_validate_warns_when_sheet_not_in_project():
    status = {"running": True, "project_file": "MyProject.PrjPcb", "active_tab": "ForeignSheet.SchDoc", "tab_type": "schematic"}
    result = validate_active_document(status, PROJECT_ROOT, PRJ_PCB, SHEET_PATHS)
    assert result["warning"] == "active_document_outside_project"


def test_validate_warns_when_no_sheet_open():
    status = {"running": True, "project_file": "", "active_tab": "PowerSupply.SchDoc", "tab_type": "schematic", "warning": "no_sheet_open"}
    result = validate_active_document(status, PROJECT_ROOT, PRJ_PCB, SHEET_PATHS)
    assert result["warning"] == "no_sheet_open"
