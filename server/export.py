import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# IMPORTANT: Bump this — and SUPPORTED_SCHEMA_VERSION in pcb-copilot — whenever the DB
# schema changes. See CONTRIBUTING.md.
SCHEMA_VERSION = 1

HIGH_FANOUT_THRESHOLD = 25


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE project (
          id               INTEGER PRIMARY KEY,
          name             TEXT NOT NULL,
          root_dir         TEXT,
          exported_at      TEXT NOT NULL,
          exported_by      TEXT NOT NULL,
          schema_version   INTEGER NOT NULL,
          sheet_count      INTEGER NOT NULL,
          component_count  INTEGER NOT NULL,
          net_count        INTEGER NOT NULL
        );
        CREATE TABLE sheets (
          id   INTEGER PRIMARY KEY,
          name TEXT NOT NULL
        );
        CREATE TABLE variants (
          id         INTEGER PRIMARY KEY,
          name       TEXT NOT NULL,
          dnp_refdes TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE components (
          id          INTEGER PRIMARY KEY,
          refdes      TEXT NOT NULL UNIQUE,
          mpn         TEXT,
          description TEXT,
          value       TEXT,
          sheet_id    INTEGER REFERENCES sheets(id)
        );
        CREATE TABLE nets (
          id        INTEGER PRIMARY KEY,
          name      TEXT NOT NULL UNIQUE,
          pin_count INTEGER NOT NULL
        );
        CREATE TABLE pins (
          id           INTEGER PRIMARY KEY,
          component_id INTEGER NOT NULL REFERENCES components(id),
          pin_number   TEXT NOT NULL,
          pin_name     TEXT NOT NULL,
          net_name     TEXT REFERENCES nets(name)
        );
        CREATE INDEX idx_pins_net_name       ON pins(net_name);
        CREATE INDEX idx_pins_component_id   ON pins(component_id);
        CREATE INDEX idx_components_sheet_id ON components(sheet_id);
    """)


def export_project(
    project: dict,
    netlist: dict,
    variant_state,
    version: str,
) -> str:
    """Write in-memory project to a pcb-copilot .db file next to the .PrjPcb.

    Returns the absolute path to the written file.
    Raises ValueError if a duplicate refdes is detected during INSERT.
    Always overwrites any existing file at the same path.
    """
    db_path = str(Path(project["root_dir"]) / f"{project['name']}-pcb-copilot.db")
    components = netlist.get("components", {})
    nets_raw = netlist.get("nets", {})

    if Path(db_path).exists():
        Path(db_path).unlink()

    conn = sqlite3.connect(db_path)
    _committed = False
    try:
        _create_schema(conn)

        exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO project"
            " (name, root_dir, exported_at, exported_by, schema_version,"
            " sheet_count, component_count, net_count)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                project["name"],
                project["root_dir"],
                exported_at,
                f"altium-copilot v{version}",
                SCHEMA_VERSION,
                len(project["sheets"]),
                len(components),
                len(nets_raw),
            ),
        )

        sheet_id_map: dict[str, int] = {}
        for sheet in project["sheets"]:
            cur = conn.execute("INSERT INTO sheets (name) VALUES (?)", (sheet["name"],))
            sheet_id_map[sheet["name"].lower()] = cur.lastrowid

        for variant in variant_state._variants:
            conn.execute(
                "INSERT INTO variants (name, dnp_refdes) VALUES (?,?)",
                (variant.name, json.dumps(variant.dnp_refdes)),
            )

        for net_name, connections in nets_raw.items():
            pin_count = len(connections)
            conn.execute(
                "INSERT INTO nets (name, pin_count) VALUES (?,?)",
                (net_name, pin_count),
            )

        for refdes, comp in components.items():
            sheet_name = comp.get("sheet", "")
            sheet_id = sheet_id_map.get(sheet_name.lower())
            try:
                cur = conn.execute(
                    "INSERT INTO components (refdes, mpn, description, value, sheet_id)"
                    " VALUES (?,?,?,?,?)",
                    (
                        refdes,
                        comp.get("mpn"),
                        comp.get("description"),
                        comp.get("value"),
                        sheet_id,
                    ),
                )
            except sqlite3.IntegrityError:
                raise ValueError(f"Duplicate refdes detected: {refdes}")
            comp_id = cur.lastrowid
            for pin_num, pin_obj in comp.get("pins", {}).items():
                if isinstance(pin_obj, dict):
                    pin_name = pin_obj.get("name", pin_num)
                    net_name = pin_obj.get("net") or None
                else:
                    pin_name = pin_num
                    net_name = pin_obj or None
                conn.execute(
                    "INSERT INTO pins (component_id, pin_number, pin_name, net_name)"
                    " VALUES (?,?,?,?)",
                    (comp_id, pin_num, pin_name, net_name),
                )

        conn.commit()
        _committed = True
    finally:
        conn.close()
        if not _committed:
            Path(db_path).unlink(missing_ok=True)
    return db_path
