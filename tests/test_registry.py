from unittest.mock import patch

from services.registry import read_registry, upsert_registry_entry


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
