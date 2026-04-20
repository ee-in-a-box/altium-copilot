# tests/test_detect.py
from main import _detect_altium_project_impl


def test_detect_running_with_path():
    info = {"running": True, "project_file": "BMS.PrjPcb",
            "project_path": "C:/Projects/BMS/BMS.PrjPcb"}
    registry = {"projects": []}
    result = _detect_altium_project_impl(info, registry)
    assert result["running"] is True
    assert result["project_path"] == "C:/Projects/BMS/BMS.PrjPcb"
    assert result["project_file"] == "BMS.PrjPcb"


def test_detect_running_path_resolved_from_registry():
    info = {"running": True, "project_file": "BMS.PrjPcb", "project_path": ""}
    registry = {"projects": [{"name": "BMS.PrjPcb", "dir": "C:/Projects/BMS", "last_used": "..."}]}
    result = _detect_altium_project_impl(info, registry)
    assert result["running"] is True
    assert "BMS.PrjPcb" in result["project_path"]
    assert "C:/Projects/BMS" in result["project_path"].replace("\\", "/")


def test_detect_running_registry_lookup_case_insensitive():
    info = {"running": True, "project_file": "bms.prjpcb", "project_path": ""}
    registry = {"projects": [{"name": "BMS.PrjPcb", "dir": "C:/Projects/BMS", "last_used": "..."}]}
    result = _detect_altium_project_impl(info, registry)
    assert result["running"] is True
    assert result["project_path"] != ""


def test_detect_not_running():
    info = {"running": False}
    registry = {"projects": []}
    result = _detect_altium_project_impl(info, registry)
    assert result["running"] is False
    assert "registry" in result


def test_detect_running_no_project_file():
    info = {"running": True, "project_file": "", "project_path": ""}
    registry = {"projects": []}
    result = _detect_altium_project_impl(info, registry)
    assert result["running"] is True
    assert result["warning"] == "no_sheet_open"
    assert "registry" in result
