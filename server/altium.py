import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from netlist_parser import parse_protel_netlist
except ImportError:
    from server.netlist_parser import parse_protel_netlist

try:
    from parsers.sch_doc import ComponentMeta, parse_sch_doc
except ImportError:
    from server.parsers.sch_doc import ComponentMeta, parse_sch_doc

# When bundled with PyInstaller (--onefile), data files are extracted to sys._MEIPASS.
# In normal Python execution, scripts live next to this file.
if getattr(sys, "frozen", False):
    SCRIPTS_DIR = Path(sys._MEIPASS) / "scripts"
else:
    SCRIPTS_DIR = Path(__file__).parent / "scripts"


def enrich_netlist(netlist: dict, components: dict[str, "ComponentMeta"],
                   refdes_to_sheet: dict[str, str] | None = None) -> dict:
    """Merge SchDoc component metadata into the .NET-derived netlist dict.

    Adds netlist["components"] = {refdes: {mpn, description, value, sheet, pins: {pin: {name, net}}}}.

    Handles subsheet fan-out: when Altium instantiates the same schematic sheet
    multiple times, the netlist compiler appends a letter suffix to each refdes
    (C1 → C1A, C1B, C1C). The SchDoc contains the bare refdes (C1); this function
    detects those suffixed variants and creates enriched entries for each one.
    """
    pin_to_net = netlist["pin_to_net"]
    sheet_map = refdes_to_sheet or {}
    result: dict = {}
    for refdes, meta in components.items():
        sheet = sheet_map.get(refdes, "")
        # Direct match (most components, and already-suffixed subsheet refs)
        if refdes in pin_to_net:
            entry = _make_enriched(meta, pin_to_net[refdes])
            entry["sheet"] = sheet
            result[refdes] = entry
            continue

        # Subsheet fan-out: look for refdesA, refdesB, ... in pin_to_net
        suffixed = [r for r in pin_to_net if re.fullmatch(rf"{re.escape(refdes)}[A-Z]", r)]
        if suffixed:
            for suffixed_ref in suffixed:
                entry = _make_enriched(meta, pin_to_net[suffixed_ref])
                entry["sheet"] = sheet
                result[suffixed_ref] = entry
            continue

        # No net connections (chassis fuses, heatsinks, mounting holes, etc.)
        # Still include so Claude can answer BOM questions about them.
        entry = _make_enriched(meta, {})
        entry["sheet"] = sheet
        result[refdes] = entry

    netlist["components"] = result
    return netlist


def _make_enriched(meta: "ComponentMeta", comp_pins: dict) -> dict:
    enriched_pins = {
        pin_num: {"name": meta.pins.get(pin_num, ""), "net": net}
        for pin_num, net in comp_pins.items()
    }
    return {
        "mpn": meta.mpn,
        "description": meta.description,
        "value": meta.value,
        "pins": enriched_pins,
    }


def _run_ps(script: str, **params: str) -> str:
    """Run a PowerShell script and return stdout. Raises on non-zero exit.

    All scripts in server/scripts/ must implement Win32 calls via C# inline
    with Add-Type — never use PowerShell scriptblock delegates for Win32 work.
    Scriptblock delegates break on PS 7+ but C# Add-Type works on all versions.
    See get_altium_status.ps1 as the reference pattern.
    """
    args = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(SCRIPTS_DIR / script)]
    for key, value in params.items():
        args += [f"-{key}", value]

    result = subprocess.run(args, capture_output=True, text=True, timeout=10)  # noqa: S603
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"{script} failed")
    return result.stdout.strip()


def _classify_tab(tab: str) -> str:
    lower = tab.lower()
    if lower.endswith(".schdoc"):
        return "schematic"
    if lower.endswith(".pcbdoc"):
        return "pcb"
    return "other"


def validate_active_document(
    status: dict,
    project_root: str,
    prj_pcb_path: str,
    sheet_paths: list[str],
) -> str | dict:
    """Pure function — validate the active Altium tab against the loaded project.

    Returns the active tab filename (str) if valid, or a warning dict if not.
    """
    if not status.get("running"):
        return {
            "warning": "altium_not_running",
            "message": "Altium Designer is not running. Open Altium and try again.",
        }

    if status.get("warning") == "no_sheet_open":
        return {
            "warning": "no_sheet_open",
            "message": (
                "Altium is running but no active schematic sheet was detected. "
                "Open a schematic sheet in Altium, then try again."
            ),
        }

    # Check project matches
    if status.get("project_file"):
        loaded = os.path.basename(prj_pcb_path).lower()
        active = status["project_file"].lower()
        if active != loaded:
            return {
                "warning": "active_document_outside_project",
                "active_filename": status.get("active_tab", ""),
                "scoped_project": os.path.basename(project_root),
                "message": (
                    f"Altium has \"{status['project_file']}\" open, but the loaded project is "
                    f"\"{os.path.basename(prj_pcb_path)}\". Switch projects or call set_project_dir."
                ),
            }

    # Check tab belongs to this project's sheets
    active_tab = status.get("active_tab", "")
    sheet_names = [os.path.basename(p).lower() for p in sheet_paths]
    if active_tab.lower() not in sheet_names:
        return {
            "warning": "active_document_outside_project",
            "active_filename": active_tab,
            "scoped_project": os.path.basename(project_root),
            "message": (
                f"\"{active_tab}\" does not belong to project \"{os.path.basename(project_root)}\". "
                "Switch to a sheet in this project."
            ),
        }

    return active_tab


class AltiumClient:
    def __init__(self):
        self._netlist: dict | None = None

    def _enrich_from_schdocs(self, project_dir: Path, netlist: dict) -> None:
        components: dict = {}
        refdes_to_sheet: dict[str, str] = {}
        for sch_path in project_dir.glob("*.SchDoc"):
            sheet_name = Path(sch_path).stem
            sheet_comps = parse_sch_doc(str(sch_path))
            for r in sheet_comps:
                refdes_to_sheet[r] = sheet_name
            components.update(sheet_comps)
        enrich_netlist(netlist, components, refdes_to_sheet)
        netlist["components"] = netlist.get("components", {})

    def get_status(self) -> dict:
        result = json.loads(_run_ps("get_altium_status.ps1"))
        if not result.get("running"):
            return result
        result["tab_type"] = _classify_tab(result.get("active_tab", ""))
        if not result.get("project_file"):
            # Can't tell from the title bar whether no project is loaded or a project
            # is loaded but no sheet is active (Altium title just shows "Altium Designer"
            # in both cases). Treat as no_sheet_open — the fix is the same either way.
            result["warning"] = "no_sheet_open"
        return result

    def generate_netlist(self, project_path: str) -> bool:
        project_dir = Path(project_path).parent
        project_name = Path(project_path).stem

        def _find_net_file() -> Path | None:
            matches = list(project_dir.rglob(f"{project_name}.NET"))
            if not matches:
                matches = list(project_dir.rglob(f"{project_name}.net"))
            return matches[0] if matches else None

        netlist_path = _find_net_file()

        # Cache check — skip GUI automation if .NET is newer than all source files.
        if netlist_path is not None and netlist_path.exists():
            try:
                net_mtime = netlist_path.stat().st_mtime
                source_files = list(project_dir.glob("*.SchDoc"))
                prj_pcb = Path(project_path)
                if prj_pcb.exists():
                    source_files.append(prj_pcb)
                if source_files:
                    max_src_mtime = max(f.stat().st_mtime for f in source_files)
                    if net_mtime >= max_src_mtime:
                        logging.info("Netlist cache is fresh — skipping generation")
                        netlist = parse_protel_netlist(str(netlist_path))
                        try:
                            self._enrich_from_schdocs(project_dir, netlist)
                        except Exception as e:
                            logging.warning("SchDoc enrichment failed: %s", e)
                        self._netlist = netlist
                        return False  # cache hit — nothing regenerated
            except Exception as e:
                logging.warning("Cache check failed, regenerating: %s", e)

        # Remove stale netlist so we can detect when Altium writes a fresh one
        if netlist_path is not None and netlist_path.exists():
            netlist_path.unlink()

        max_attempts = 3
        per_attempt_timeout = 15  # seconds per attempt

        for attempt in range(1, max_attempts + 1):
            logging.info("Generating netlist (attempt %d/%d)", attempt, max_attempts)
            _run_ps("generate_protel_netlist.ps1", Delay="1")

            start_time = time.time()
            while time.time() - start_time < per_attempt_timeout:
                found = _find_net_file()
                if found is not None and found.exists():
                    netlist = parse_protel_netlist(str(found))
                    try:
                        self._enrich_from_schdocs(project_dir, netlist)
                    except Exception as e:
                        logging.warning("SchDoc enrichment failed: %s", e)
                    self._netlist = netlist
                    return True  # PowerShell ran, netlist regenerated
                time.sleep(1)

            if attempt < max_attempts:
                logging.warning("Netlist not generated within %ds, retrying...", per_attempt_timeout)

        raise RuntimeError(
            f"Netlist not generated after {max_attempts} attempts — check Altium is responsive "
            f"and the project output directory exists."
        )
