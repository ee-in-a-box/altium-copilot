import json
import pytest
from unittest.mock import patch, MagicMock


def test_refresh_netlist_no_project():
    """_project is None → returns no_project error."""
    with patch("main._project", None), \
         patch("main._altium") as mock_altium, \
         patch("main._variant_state", MagicMock()):
        mock_altium._netlist = {"nets": {}, "pin_to_net": {}, "components": {}}
        from main import refresh_netlist
        result = json.loads(refresh_netlist())
    assert result["error"] == "no_project"


def test_refresh_netlist_cache_hit():
    """generate_netlist returns False → returns 'save first' message string."""
    with patch("main._project", {"prj_pcb_path": "/fake/proj.PrjPcb"}), \
         patch("main._altium") as mock_altium, \
         patch("main._variant_state", MagicMock()):
        mock_altium._netlist = {"nets": {}, "pin_to_net": {}, "components": {}}
        mock_altium.generate_netlist.return_value = False
        from main import refresh_netlist
        result = refresh_netlist()
    assert isinstance(result, str)
    assert "up to date" in result
    assert "expected changes" in result
    # Cache-hit returns a plain string, not JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(result)


def test_refresh_netlist_regenerated():
    """generate_netlist returns True → returns JSON with refreshed=true and timestamp."""
    with patch("main._project", {"prj_pcb_path": "/fake/proj.PrjPcb"}), \
         patch("main._altium") as mock_altium, \
         patch("main._variant_state", MagicMock()):
        mock_altium._netlist = {"nets": {}, "pin_to_net": {}, "components": {}}
        mock_altium.generate_netlist.return_value = True
        from main import refresh_netlist
        result = json.loads(refresh_netlist())
    assert result["refreshed"] is True
    assert "netlist_updated_utc" in result
    # Timestamp is a valid ISO string
    from datetime import datetime
    datetime.fromisoformat(result["netlist_updated_utc"])  # raises ValueError if malformed


def test_refresh_netlist_generate_failed():
    """generate_netlist raises → returns generate_failed error."""
    with patch("main._project", {"prj_pcb_path": "/fake/proj.PrjPcb"}), \
         patch("main._altium") as mock_altium, \
         patch("main._variant_state", MagicMock()):
        mock_altium._netlist = {"nets": {}, "pin_to_net": {}, "components": {}}
        mock_altium.generate_netlist.side_effect = RuntimeError("Altium not responding")
        from main import refresh_netlist
        result = json.loads(refresh_netlist())
    assert result["error"] == "generate_failed"
    assert "Altium not responding" in result["message"]
