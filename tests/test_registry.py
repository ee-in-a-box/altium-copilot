from unittest.mock import patch

from services.registry import read_registry, upsert_registry_entry, mark_xfn_exported


def test_read_registry_missing_file(tmp_path):
    fake_path = tmp_path / "nonexistent.json"
    with patch("services.registry.REGISTRY_PATH", fake_path):
        result = read_registry()
    assert result == {"projects": []}


def test_upsert_new_entry(tmp_path):
    fake_path = tmp_path / ".ee-in-a-box" / "altium-projects.json"
    with patch("services.registry.REGISTRY_PATH", fake_path):
        upsert_registry_entry("BMS.PrjPcb", "C:/Projects/BMS")
        registry = read_registry()
    assert len(registry["projects"]) == 1
    assert registry["projects"][0]["name"] == "BMS.PrjPcb"
    assert registry["projects"][0]["dir"] == "C:/Projects/BMS"
    assert "last_used" in registry["projects"][0]


def test_upsert_existing_entry_updates_dir_and_time(tmp_path):
    fake_path = tmp_path / ".ee-in-a-box" / "altium-projects.json"
    with patch("services.registry.REGISTRY_PATH", fake_path):
        upsert_registry_entry("BMS.PrjPcb", "C:/Projects/BMS")
        upsert_registry_entry("BMS.PrjPcb", "D:/NewLocation/BMS")
        registry = read_registry()
    assert len(registry["projects"]) == 1
    assert registry["projects"][0]["dir"] == "D:/NewLocation/BMS"


def test_upsert_case_insensitive_match(tmp_path):
    fake_path = tmp_path / ".ee-in-a-box" / "altium-projects.json"
    with patch("services.registry.REGISTRY_PATH", fake_path):
        upsert_registry_entry("bms.prjpcb", "C:/Projects/BMS")
        upsert_registry_entry("BMS.PrjPcb", "D:/NewLocation/BMS")
        registry = read_registry()
    assert len(registry["projects"]) == 1


def test_mark_xfn_exported_stamps_timestamp(tmp_path):
    fake_path = tmp_path / ".ee-in-a-box" / "altium-projects.json"
    with patch("services.registry.REGISTRY_PATH", fake_path):
        upsert_registry_entry("BMS.PrjPcb", "C:/Projects/BMS")
        mark_xfn_exported("BMS.PrjPcb")
        registry = read_registry()
    assert "last_exported_xfn" in registry["projects"][0]


def test_mark_xfn_exported_case_insensitive(tmp_path):
    fake_path = tmp_path / ".ee-in-a-box" / "altium-projects.json"
    with patch("services.registry.REGISTRY_PATH", fake_path):
        upsert_registry_entry("BMS.PrjPcb", "C:/Projects/BMS")
        mark_xfn_exported("bms.prjpcb")
        registry = read_registry()
    assert "last_exported_xfn" in registry["projects"][0]


def test_mark_xfn_exported_unknown_project_is_noop(tmp_path):
    fake_path = tmp_path / ".ee-in-a-box" / "altium-projects.json"
    with patch("services.registry.REGISTRY_PATH", fake_path):
        upsert_registry_entry("BMS.PrjPcb", "C:/Projects/BMS")
        mark_xfn_exported("Other.PrjPcb")
        registry = read_registry()
    assert "last_exported_xfn" not in registry["projects"][0]
