import json
import sqlite3
from pathlib import Path

import pytest
from export import SCHEMA_VERSION, _create_schema, export_project


def test_schema_version_is_1():
    assert SCHEMA_VERSION == 1


def test_create_schema_tables(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    _create_schema(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()
    assert tables == {"project", "sheets", "variants", "components", "nets", "pins"}


def test_create_schema_indices(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    _create_schema(conn)
    indices = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    conn.close()
    assert "idx_pins_net_name" in indices
    assert "idx_pins_component_id" in indices
    assert "idx_components_sheet_id" in indices


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _FakeVariant:
    def __init__(self, name, dnp_refdes=None):
        self.name = name
        self.dnp_refdes = dnp_refdes or []


class _FakeVariantState:
    def __init__(self, variants):
        self._variants = variants


def _minimal_project(tmp_path):
    return {
        "name": "TestBoard",
        "root_dir": str(tmp_path),
        "sheets": [
            {"name": "MCU", "path": "MCU.SchDoc"},
            {"name": "Comms", "path": "Comms.SchDoc"},
        ],
    }


def _minimal_netlist():
    return {
        "nets": {
            "MCU_TX": [("U1", "PA9"), ("R1", "1")],
            "GND": [("U1", "GND"), ("R1", "2")],
        },
        "pin_to_net": {
            "U1": {"PA9": "MCU_TX", "GND": "GND"},
            "R1": {"1": "MCU_TX", "2": "GND"},
        },
        "components": {
            "U1": {
                "mpn": "STM32G474",
                "description": "MCU",
                "value": None,
                "sheet": "MCU",
                "pins": {
                    "PA9": {"name": "PA9", "net": "MCU_TX"},
                    "GND": {"name": "GND", "net": "GND"},
                },
            },
            "R1": {
                "mpn": "RC0402",
                "description": "RES 10K",
                "value": "10K",
                "sheet": "Comms",
                "pins": {
                    "1": {"name": "~", "net": "MCU_TX"},
                    "2": {"name": "~", "net": "GND"},
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# project / sheets / variants / nets rows
# ---------------------------------------------------------------------------

def test_export_creates_db_file(tmp_path):
    vs = _FakeVariantState([_FakeVariant("Default")])
    db_path = export_project(_minimal_project(tmp_path), _minimal_netlist(), vs, "0.1.10")
    assert db_path == str(tmp_path / "TestBoard-pcb-copilot.db")
    assert Path(db_path).exists()


def test_export_project_row(tmp_path):
    vs = _FakeVariantState([_FakeVariant("Default"), _FakeVariant("Lite", ["R1"])])
    export_project(_minimal_project(tmp_path), _minimal_netlist(), vs, "0.1.10")
    conn = sqlite3.connect(str(tmp_path / "TestBoard-pcb-copilot.db"))
    row = dict(zip(
        ["id", "name", "root_dir", "exported_at", "exported_by", "schema_version",
         "sheet_count", "component_count", "net_count"],
        conn.execute("SELECT * FROM project LIMIT 1").fetchone(),
    ))
    conn.close()
    assert row["name"] == "TestBoard"
    assert row["schema_version"] == 1
    assert row["exported_by"] == "altium-copilot v0.1.10"
    assert row["sheet_count"] == 2
    assert row["component_count"] == 2
    assert row["net_count"] == 2


def test_export_sheets_rows(tmp_path):
    vs = _FakeVariantState([_FakeVariant("Default")])
    export_project(_minimal_project(tmp_path), _minimal_netlist(), vs, "0.1.0")
    conn = sqlite3.connect(str(tmp_path / "TestBoard-pcb-copilot.db"))
    names = [r[0] for r in conn.execute("SELECT name FROM sheets ORDER BY id").fetchall()]
    conn.close()
    assert names == ["MCU", "Comms"]


def test_export_variants_rows(tmp_path):
    vs = _FakeVariantState([_FakeVariant("Default"), _FakeVariant("Lite", ["R1"])])
    export_project(_minimal_project(tmp_path), _minimal_netlist(), vs, "0.1.0")
    conn = sqlite3.connect(str(tmp_path / "TestBoard-pcb-copilot.db"))
    rows = conn.execute("SELECT name, dnp_refdes FROM variants ORDER BY id").fetchall()
    conn.close()
    assert rows[0][0] == "Default"
    assert json.loads(rows[0][1]) == []
    assert rows[1][0] == "Lite"
    assert json.loads(rows[1][1]) == ["R1"]


def test_export_nets_rows(tmp_path):
    vs = _FakeVariantState([_FakeVariant("Default")])
    export_project(_minimal_project(tmp_path), _minimal_netlist(), vs, "0.1.0")
    conn = sqlite3.connect(str(tmp_path / "TestBoard-pcb-copilot.db"))
    nets = {r[0]: r[1] for r in conn.execute("SELECT name, pin_count FROM nets").fetchall()}
    conn.close()
    assert nets["MCU_TX"] == 2
    assert nets["GND"] == 2


# ---------------------------------------------------------------------------
# components and pins rows
# ---------------------------------------------------------------------------

def test_export_components_rows(tmp_path):
    vs = _FakeVariantState([_FakeVariant("Default")])
    export_project(_minimal_project(tmp_path), _minimal_netlist(), vs, "0.1.0")
    conn = sqlite3.connect(str(tmp_path / "TestBoard-pcb-copilot.db"))
    comps = {
        r[0]: {"mpn": r[1], "description": r[2], "value": r[3], "sheet_id": r[4]}
        for r in conn.execute(
            "SELECT refdes, mpn, description, value, sheet_id FROM components"
        ).fetchall()
    }
    sheets = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM sheets").fetchall()}
    conn.close()
    assert "U1" in comps
    assert comps["U1"]["mpn"] == "STM32G474"
    assert sheets[comps["U1"]["sheet_id"]] == "MCU"
    assert "R1" in comps
    assert comps["R1"]["value"] == "10K"
    assert sheets[comps["R1"]["sheet_id"]] == "Comms"


def test_export_pins_rows(tmp_path):
    vs = _FakeVariantState([_FakeVariant("Default")])
    export_project(_minimal_project(tmp_path), _minimal_netlist(), vs, "0.1.0")
    conn = sqlite3.connect(str(tmp_path / "TestBoard-pcb-copilot.db"))
    comp_id = conn.execute("SELECT id FROM components WHERE refdes='U1'").fetchone()[0]
    pins = {
        r[0]: {"pin_name": r[1], "net_name": r[2]}
        for r in conn.execute(
            "SELECT pin_number, pin_name, net_name FROM pins WHERE component_id=?", (comp_id,)
        ).fetchall()
    }
    conn.close()
    assert "PA9" in pins
    assert pins["PA9"]["pin_name"] == "PA9"
    assert pins["PA9"]["net_name"] == "MCU_TX"
    assert "GND" in pins
    assert pins["GND"]["net_name"] == "GND"


def test_export_unconnected_pin_has_null_net(tmp_path):
    netlist = _minimal_netlist()
    netlist["components"]["R1"]["pins"]["NC"] = {"name": "NC", "net": None}
    vs = _FakeVariantState([_FakeVariant("Default")])
    export_project(_minimal_project(tmp_path), netlist, vs, "0.1.0")
    conn = sqlite3.connect(str(tmp_path / "TestBoard-pcb-copilot.db"))
    comp_id = conn.execute("SELECT id FROM components WHERE refdes='R1'").fetchone()[0]
    net_name = conn.execute(
        "SELECT net_name FROM pins WHERE component_id=? AND pin_number='NC'", (comp_id,)
    ).fetchone()[0]
    conn.close()
    assert net_name is None


def test_export_overwrites_existing_db(tmp_path):
    vs = _FakeVariantState([_FakeVariant("Default")])
    db_path = export_project(_minimal_project(tmp_path), _minimal_netlist(), vs, "0.1.0")
    db_path2 = export_project(_minimal_project(tmp_path), _minimal_netlist(), vs, "0.1.1")
    assert db_path == db_path2
    conn = sqlite3.connect(db_path2)
    exported_by = conn.execute("SELECT exported_by FROM project").fetchone()[0]
    conn.close()
    assert exported_by == "altium-copilot v0.1.1"


# ---------------------------------------------------------------------------
# duplicate refdes detection
# ---------------------------------------------------------------------------

def test_duplicate_refdes_raises_value_error(tmp_path):
    """A UNIQUE violation on components.refdes must surface as ValueError and leave no DB file."""

    class _DuplicateDict(dict):
        """Yields the same refdes twice to force an IntegrityError on the second INSERT."""
        def items(self):
            comp = {"mpn": None, "description": None, "value": None, "sheet": "MCU", "pins": {}}
            yield "R1", comp
            yield "R1", comp

    netlist = {"nets": {}, "pin_to_net": {}, "components": _DuplicateDict()}
    project = {
        "name": "TestBoard",
        "root_dir": str(tmp_path),
        "sheets": [{"name": "MCU", "path": ""}],
    }
    vs = _FakeVariantState([_FakeVariant("Default")])

    with pytest.raises(ValueError, match="R1"):
        export_project(project, netlist, vs, "0.1.0")

    assert not (tmp_path / "TestBoard-pcb-copilot.db").exists()
