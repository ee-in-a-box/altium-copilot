import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

REGISTRY_PATH = Path(
    os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home())
) / ".ee-in-a-box" / "altium-projects.json"


def read_registry() -> dict:
    try:
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"projects": []}
    except Exception as e:
        logger.error(f"altium-copilot: failed to read registry: {e}")
        return {"projects": []}


def write_registry(registry: dict) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    os.replace(tmp, REGISTRY_PATH)


def upsert_registry_entry(name: str, dir: str) -> None:
    registry = read_registry()
    now = datetime.now(timezone.utc).isoformat()
    for entry in registry["projects"]:
        if entry["name"].lower() == name.lower():
            entry["dir"] = dir
            entry["last_used"] = now
            break
    else:
        registry["projects"].append({"name": name, "dir": dir, "last_used": now})
    write_registry(registry)


def mark_xfn_exported(name: str) -> None:
    registry = read_registry()
    now = datetime.now(timezone.utc).isoformat()
    for entry in registry["projects"]:
        if entry["name"].lower() == name.lower():
            entry["last_exported_xfn"] = now
            break
    write_registry(registry)
