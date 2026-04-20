import json
from unittest.mock import patch


def test_set_project_dir_altium_not_running(tmp_path):
    with patch("main._altium") as mock_altium:
        mock_altium.get_status.return_value = {"running": False}
        from main import set_project_dir
        result = json.loads(set_project_dir(str(tmp_path)))
    assert result["error"] == "altium_not_running"


def test_set_project_dir_no_sheet_open(tmp_path):
    with patch("main._altium") as mock_altium:
        mock_altium.get_status.return_value = {"running": True, "warning": "no_sheet_open"}
        from main import set_project_dir
        result = json.loads(set_project_dir(str(tmp_path)))
    assert result["error"] == "no_sheet_open"


def test_set_project_dir_project_mismatch(tmp_path):
    prj = tmp_path / "myproject.PrjPcb"
    prj.write_text("", encoding="utf-8")
    with patch("main._altium") as mock_altium:
        mock_altium.get_status.return_value = {"running": True, "project_file": "OtherProject.PrjPcb"}
        from main import set_project_dir
        result = json.loads(set_project_dir(str(tmp_path)))
    assert result["error"] == "project_mismatch"
    assert result["altium_open"] == "OtherProject.PrjPcb"
    assert result["requested"] == "myproject.PrjPcb"


def test_set_project_dir_no_prjpcb(tmp_path):
    with patch("main._altium") as mock_altium:
        mock_altium.get_status.return_value = {"running": True, "project_file": "Test.PrjPcb"}
        from main import set_project_dir
        result = json.loads(set_project_dir(str(tmp_path)))
    assert result["error"] == "no_prjpcb"


def test_set_project_dir_success(tmp_path):
    # Create a minimal .PrjPcb file
    prj = tmp_path / "Test.PrjPcb"
    prj.write_text("[Design]\n[Document1]\nDocumentPath=Sheet1.SchDoc\n", encoding="utf-8")
    (tmp_path / "Sheet1.SchDoc").write_bytes(b"")  # placeholder

    with patch("main._altium") as mock_altium, \
         patch("main.parse_prj_pcb") as mock_parse, \
         patch("main.upsert_registry_entry") as mock_upsert:

        from parsers.prj_pcb import VariantDefinition, PrjPcbData
        mock_parse.return_value = PrjPcbData(
            sheet_paths=[str(tmp_path / "Sheet1.SchDoc")],
            variants=[VariantDefinition(name="Default")]
        )
        mock_altium.get_status.return_value = {"running": True, "project_file": "Test.PrjPcb"}
        mock_altium._netlist = {"nets": {}, "pin_to_net": {}, "components": {}}
        mock_altium.generate_netlist.return_value = True

        from main import set_project_dir
        result = json.loads(set_project_dir(str(tmp_path)))

    assert result["loaded"] is True
    assert result["project"] == "Test"
    assert result["sheet_count"] == 1
    mock_upsert.assert_called_once_with("Test.PrjPcb", str(tmp_path))
