import json  # noqa: F401
import os
import time  # noqa: F401
import pytest
from pathlib import Path  # noqa: F401
from unittest.mock import patch, MagicMock
from server.altium import AltiumClient


def test_generate_netlist_derives_path_correctly(tmp_path):
    # Project structure: tmp_path/myproj/myproj.PrjPcb
    # Expected netlist:  tmp_path/myproj/Project Outputs for myproj/myproj.NET
    proj_dir = tmp_path / "myproj"
    proj_dir.mkdir()
    outputs_dir = proj_dir / "Project Outputs for myproj"
    outputs_dir.mkdir()
    net_file = outputs_dir / "myproj.NET"

    project_path = str(proj_dir / "myproj.PrjPcb")
    client = AltiumClient()

    def fake_run_ps(script, **kwargs):
        # Simulate Altium writing the .NET file
        net_file.write_text("(\nNET1\nR1-1\n)\n", encoding="utf-8")
        return '{"success":true}'

    with patch("server.altium._run_ps", side_effect=fake_run_ps):
        result = client.generate_netlist(project_path)

    assert client._netlist is not None
    assert "NET1" in client._netlist["nets"]
    # The enriched netlist always has a "components" key (may be empty if no .SchDoc present)
    assert "components" in client._netlist
    assert result is True  # NEW


def test_generate_netlist_raises_on_ps_failure(tmp_path):
    proj_dir = tmp_path / "myproj"
    proj_dir.mkdir()
    project_path = str(proj_dir / "myproj.PrjPcb")
    client = AltiumClient()

    with patch("server.altium._run_ps", side_effect=RuntimeError("script failed")):
        with pytest.raises(RuntimeError, match="script failed"):
            client.generate_netlist(project_path)


def test_generate_netlist_raises_on_timeout(tmp_path):
    proj_dir = tmp_path / "myproj"
    proj_dir.mkdir()
    project_path = str(proj_dir / "myproj.PrjPcb")
    client = AltiumClient()

    # PS runs fine but .NET file never appears across all 3 attempts
    with patch("server.altium._run_ps", return_value='{"success":true}'):
        with patch("server.altium.time") as mock_time:
            # Simulate time advancing past 15s immediately for each of the 3 attempts
            mock_time.time.side_effect = [0, 16, 0, 16, 0, 16]
            mock_time.sleep = MagicMock()
            with pytest.raises(RuntimeError, match="Netlist not generated after 3 attempts"):
                client.generate_netlist(project_path)


def test_netlist_is_none_before_first_generate():
    client = AltiumClient()
    assert client._netlist is None


def test_generate_netlist_uses_cache_when_net_is_fresh(tmp_path):
    """When the .NET file is newer than all source files, skip PowerShell."""
    proj_dir = tmp_path / "myproj"
    proj_dir.mkdir()
    outputs_dir = proj_dir / "Project Outputs for myproj"
    outputs_dir.mkdir()

    # Create a .SchDoc and .PrjPcb that are "old"
    sch = proj_dir / "top.SchDoc"
    sch.write_text("", encoding="utf-8")
    prj = proj_dir / "myproj.PrjPcb"
    prj.write_text("", encoding="utf-8")

    # Create a .NET that is newer (mtime 100s in the future)
    net_file = outputs_dir / "myproj.NET"
    net_file.write_text("(\nNET1\nR1-1\n)\n", encoding="utf-8")
    future = sch.stat().st_mtime + 100
    os.utime(net_file, (future, future))

    project_path = str(proj_dir / "myproj.PrjPcb")
    client = AltiumClient()

    with patch("server.altium._run_ps") as mock_ps:
        result = client.generate_netlist(project_path)
        mock_ps.assert_not_called()  # PowerShell must NOT run

    assert client._netlist is not None
    assert "NET1" in client._netlist["nets"]
    assert result is False  # NEW


def test_generate_netlist_regenerates_when_schdoc_is_newer(tmp_path):
    """When a .SchDoc is newer than the .NET, regenerate — don't use cache."""
    proj_dir = tmp_path / "myproj"
    proj_dir.mkdir()
    outputs_dir = proj_dir / "Project Outputs for myproj"
    outputs_dir.mkdir()

    net_file = outputs_dir / "myproj.NET"
    net_file.write_text("(\nOLD_NET\nR1-1\n)\n", encoding="utf-8")

    # .SchDoc is newer than the .NET
    sch = proj_dir / "top.SchDoc"
    sch.write_text("", encoding="utf-8")
    future = net_file.stat().st_mtime + 100
    os.utime(sch, (future, future))

    proj_dir / "myproj.PrjPcb"  # doesn't exist, that's fine

    project_path = str(proj_dir / "myproj.PrjPcb")
    client = AltiumClient()

    def fake_run_ps(script, **kwargs):
        net_file.write_text("(\nNEW_NET\nR1-1\n)\n", encoding="utf-8")
        return '{"success":true}'

    with patch("server.altium._run_ps", side_effect=fake_run_ps) as mock_ps:
        result = client.generate_netlist(project_path)
        mock_ps.assert_called_once_with("generate_protel_netlist.ps1", Delay="50")  # PowerShell MUST run

    assert "NEW_NET" in client._netlist["nets"]
    assert result is True  # NEW
