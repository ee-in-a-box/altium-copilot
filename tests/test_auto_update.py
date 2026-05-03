# tests/test_auto_update.py
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock


def test_read_version_from_manifest(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"version": "1.2.3"}))
    with patch("main._manifest_path", return_value=manifest):
        from main import _read_version
        assert _read_version() == "1.2.3"


def test_read_version_missing_file(tmp_path):
    missing = tmp_path / "manifest.json"
    with patch("main._manifest_path", return_value=missing):
        from main import _read_version
        assert _read_version() == "0.0.0"


def test_read_version_malformed_json(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("not json")
    with patch("main._manifest_path", return_value=manifest):
        from main import _read_version
        assert _read_version() == "0.0.0"


def test_is_newer_returns_true_when_latest_is_higher():
    from main import _is_newer
    assert _is_newer("0.2.0", "0.1.0") is True


def test_is_newer_returns_false_when_same():
    from main import _is_newer
    assert _is_newer("0.1.0", "0.1.0") is False


def test_is_newer_returns_false_when_older():
    from main import _is_newer
    assert _is_newer("0.1.0", "0.2.0") is False


def test_is_newer_handles_minor_version():
    from main import _is_newer
    assert _is_newer("0.1.10", "0.1.9") is True


def test_read_state_missing_file(tmp_path):
    fake = tmp_path / "altium-copilot-state.json"
    with patch("main.STATE_PATH", fake):
        from main import _read_state
        assert _read_state() == {}


def test_read_state_malformed(tmp_path):
    fake = tmp_path / "altium-copilot-state.json"
    fake.write_text("not json")
    with patch("main.STATE_PATH", fake):
        from main import _read_state
        assert _read_state() == {}


def test_write_and_read_state(tmp_path):
    fake = tmp_path / "altium-copilot-state.json"
    with patch("main.STATE_PATH", fake):
        from main import _read_state, _write_state
        _write_state({"installed_version": "0.1.0", "update_available": "0.2.0"})
        assert _read_state() == {"installed_version": "0.1.0", "update_available": "0.2.0"}


def test_write_state_creates_parent_dir(tmp_path):
    fake = tmp_path / "nested" / "dir" / "state.json"
    with patch("main.STATE_PATH", fake):
        from main import _write_state
        _write_state({"installed_version": "0.1.0"})
        assert fake.exists()



def test_check_for_update_skips_if_checked_recently(tmp_path):
    fake = tmp_path / "state.json"
    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    fake.write_text(json.dumps({"update_checked_at": recent}))
    with patch("main.STATE_PATH", fake):
        with patch("main.httpx") as mock_httpx:
            from main import _check_for_update
            _check_for_update("0.1.0")
            mock_httpx.get.assert_not_called()


def test_check_for_update_writes_update_available(tmp_path):
    fake = tmp_path / "state.json"
    fake.write_text(json.dumps({}))
    mock_response = MagicMock()
    mock_response.json.return_value = {"tag_name": "v0.2.0"}
    with patch("main.STATE_PATH", fake):
        with patch("main.httpx.get", return_value=mock_response):
            from main import _check_for_update, _read_state
            _check_for_update("0.1.0")
            state = _read_state()
            assert state["update_available"] == "0.2.0"
            assert "update_checked_at" in state


def test_check_for_update_clears_update_available_when_up_to_date(tmp_path):
    fake = tmp_path / "state.json"
    fake.write_text(json.dumps({"update_available": "0.2.0"}))
    mock_response = MagicMock()
    mock_response.json.return_value = {"tag_name": "v0.1.0"}
    with patch("main.STATE_PATH", fake):
        with patch("main.httpx.get", return_value=mock_response):
            from main import _check_for_update, _read_state
            _check_for_update("0.1.0")
            assert "update_available" not in _read_state()


def test_check_for_update_silently_handles_network_error(tmp_path):
    fake = tmp_path / "state.json"
    fake.write_text(json.dumps({}))
    with patch("main.STATE_PATH", fake):
        with patch("main.httpx.get", side_effect=Exception("no internet")):
            from main import _check_for_update
            _check_for_update("0.1.0")  # must not raise



