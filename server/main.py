# server/main.py
import json
import logging
import math
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

vendor_dir = os.path.join(os.path.dirname(__file__), "vendor")
# When bundled with PyInstaller, vendor is embedded — no sys.path injection needed.
# Only inject when running from source and the vendor dir exists.
if os.path.exists(vendor_dir):
    sys.path.insert(0, vendor_dir)

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

try:
    from altium import AltiumClient
    from parsers.prj_pcb import parse_prj_pcb, VariantState
    from services.registry import read_registry, upsert_registry_entry, mark_xfn_exported
    from services.page_netlist import build_sheet_context, MAX_RESULT_SIZE_CHARS
    from parsers.pcb_doc import parse_pcb_doc
    from services.pcb_index import PcbIndex
    from export import export_project, HIGH_FANOUT_THRESHOLD
except ImportError:
    from server.altium import AltiumClient
    from server.parsers.prj_pcb import parse_prj_pcb, VariantState
    from server.parsers.pcb_doc import parse_pcb_doc
    from server.services.registry import read_registry, upsert_registry_entry, mark_xfn_exported
    from server.services.page_netlist import build_sheet_context, MAX_RESULT_SIZE_CHARS
    from server.services.pcb_index import PcbIndex
    from server.export import export_project, HIGH_FANOUT_THRESHOLD

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")


def _manifest_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "manifest.json"
    return Path(__file__).parent.parent / "manifest.json"


def _read_version() -> str:
    try:
        return json.loads(_manifest_path().read_text(encoding="utf-8"))["version"]
    except Exception:
        return "0.0.0"


STATE_PATH = Path(
    os.environ.get("USERPROFILE") or str(Path.home())
) / ".ee-in-a-box" / "altium-copilot-state.json"


def _is_newer(latest: str, current: str) -> bool:
    def _t(v: str) -> tuple:
        return tuple(int(x) for x in v.split("."))
    return _t(latest) > _t(current)


def _read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")



_GITHUB_RELEASES_URL = "https://api.github.com/repos/ee-in-a-box/altium-copilot/releases/latest"
_UPDATE_CHECK_INTERVAL_HOURS = 24


def _check_for_update(current_version: str) -> None:
    try:
        state = _read_state()
        last_checked = state.get("update_checked_at")
        if last_checked:
            delta = datetime.now(timezone.utc) - datetime.fromisoformat(last_checked)
            if delta.total_seconds() < _UPDATE_CHECK_INTERVAL_HOURS * 3600:
                return
        response = httpx.get(_GITHUB_RELEASES_URL, timeout=5)
        tag = response.json().get("tag_name", "").lstrip("v")
        if not tag:
            return
        state["update_checked_at"] = datetime.now(timezone.utc).isoformat()
        if _is_newer(tag, current_version):
            state["update_available"] = tag
        else:
            state.pop("update_available", None)
        _write_state(state)
    except Exception:
        return


QUERY_NET_MAX_RESULTS = 50
QUERY_NET_MAX_RESULT_SIZE_CHARS = 60_000

SERVER_INSTRUCTIONS = """\
You are an Altium Designer copilot. Use these tools to understand and discuss schematic projects.

## Session Start

At the start of every session, run these steps in order:

1. detect_altium_project — check if Altium is running and surface known projects
2. set_project_dir — load the project using the decision table below (required before any other tool)
3. list_variants — ask the user which variant to work in, then call set_active_variant
   (always ask — do not auto-select even if there is only one variant)
4. get_sheet_context — read the active tab, then synthesize a summary for the user:
   project name, sheet count, variant count, and your read of what the board does
   based on component descriptions and sheet names.

### Decision table for set_project_dir

| Situation | Action |
|-----------|--------|
| Altium running + project in registry | Call set_project_dir(registry dir) silently |
| Altium running + not in registry, project_path non-empty | Confirm path with user, then call set_project_dir |
| Altium running + not in registry, project_path empty | Ask user for the folder path, then call set_project_dir |
| Altium not running + registry non-empty | Show projects sorted by last_used desc, let user pick, then call set_project_dir |
| Altium not running + registry empty | Ask user for the folder containing the .PrjPcb file |

## Switching Projects

Call set_project_dir with the new path, then repeat the session-start steps.

## General Rules

- Never answer from memory about component values, nets, or topology — always use the tools.
- Only state conclusions supported by tool results. If uncertain — call more tools,
  search a datasheet, or tell the user you are not sure. Do not shortcut to a guess.
- Always work in the context of the active variant. Components with dnp=true are not populated.
  If the user's question implies a different variant, ask before switching.
- Nets with many connections (>25 pins) are likely power or ground rails. query_net will return
  a sample and a warning — treat these as rails, not signals.
- schematic_review — call when the user explicitly asks to review or verify the schematic (e.g. "review this", "check my schematic", "do a design review", "is this correct?", "does this look right?"). Do not call for general questions about the circuit.
- brainstorm_circuits — call when the user wants to brainstorm, or is asking how to design, improve, or choose an approach for a circuit. Any question about topology, architecture, or how to add/change a sub-circuit should trigger this. Do not call for general questions or reviews.
- package_for_xfn — call when the user explicitly asks to export, package, or share the project with firmware, mechanical, test, or reliability engineers (e.g. "package this for the firmware team", "export for sharing", "create a pcb-copilot snapshot"). Do not call speculatively.
- When the user says they have changed or saved anything in the schematic, call `refresh_netlist`
  before answering questions about the updated design. Do not call it speculatively — only after
  the user confirms they have saved in Altium (Ctrl+S).

## Answering Circuit Questions

When the user asks about a component, net, or sub-circuit on a specific sheet:

1. **Start with get_sheet_context** — one call returns every component on the sheet with
   full pin-to-net data and one-hop cross-sheet neighbors (connected_to). This is almost
   always sufficient to answer the question.
2. **For cross-sheet tracing** — `connected_to` already gives you one hop for free
   (refdes, pin, and sheet name). When you need to follow a signal onto a different
   sheet, call get_sheet_context(sheet_name="SHEET") for that sheet — do NOT call
   get_component for each cross-sheet component one-by-one.
3. **For deeper tracing only** — call query_net or get_component when you need to go two
   hops deep on a specific net, or the net is high-fanout (>25 pins).

Do not call get_component or query_net individually for components already visible in a
sheet context you have already loaded.
Do not call get_sheet_context on the same sheet twice in the same conversation turn.

## PCB / Layout Questions

For questions about the physical board (where nets route, layers, stackup, crosstalk,
component locations, distances):

1. **Call get_board_info first** — it returns the stackup, origin, extents, units, and
   data freshness. State the origin and units when discussing any coordinates.
2. get_net_pcb — "where does net X route": layers, lengths, vias, pad endpoints.
3. get_net_neighbors — crosstalk questions: "what runs near X". Proximity results are
   geometric facts; judging whether coupling matters needs rise times, impedances, and
   termination knowledge — ask the user rather than guessing severity.
4. query_pcb_region — "what is at/near (x, y)".
5. get_component_placement — "where is U12, what's around it".

Net names are shared between schematic and PCB — pivot freely between query_net
(connectivity) and get_net_pcb (physical routing). Component refdes may differ on
multi-channel designs: tools return both `refdes` (PCB) and `sch_refdes` (netlist);
a logical refdes like U3 may return multiple physical instances with channel paths.

PCB data reflects the last SAVE of the .PcbDoc in Altium and refreshes automatically —
if the user made layout changes, ask them to save (Ctrl+S), then call the tool again.
get_board_info reports both PCB and netlist timestamps; if they disagree wildly, warn
the user the schematic and layout may be out of sync.

Before relying on polygon results, ask the user to repour polygons and save the PcbDoc.
The tools model saved nominal polygon outlines, not final region/fill copper; voids,
cutouts, removed islands, and clearances must be verified in Altium.

If the user wants to know where something is visually, give coordinates relative to the
origin and offer to interpret a screenshot or photo they paste for orientation — the
server never renders images.

## Behavioral Guidelines

- **Think Before Proposing:** State your assumptions explicitly. If multiple interpretations of the circuit exist, present them—don't pick silently.
- **Simplicity First:** When suggesting fixes, propose the minimum viable component change. Do not suggest speculative features or over-engineered architectures.
- **Surgical Changes:** Recommend touching only what must be fixed. Do not propose refactoring adjacent, working sub-circuits or nets unless they are directly causing the issue.
- **Goal-Driven Execution:** For complex tracing or multi-step analysis, state a brief plan (e.g., "1. Trace VCC -> verify. 2. Check IC21 inputs -> verify") and loop your tool usage until your success criteria are verified.

## Netlist Freshness

The netlist reflects the last-saved state of the schematic files. If the user has made recent
changes in Altium Designer, ask them to save first (Ctrl+S in Altium) before you answer —
otherwise your data may be stale.

## Error Recovery

- Component not found → call search_components with a regex to locate it
- Net not found → use query_net with a keyword pattern to discover the real name
  (e.g. query_net('MISO') or query_net('CAN')). Never guess net names or
  manually chase anonymous nets one by one.
- no_sheet_open → Altium is running but no active schematic sheet is detected (project may
  or may not be loaded); tell the user to open their project in Altium and open a schematic
  sheet, then try again
- active_document_outside_project → the user has a different project open in Altium;
  ask them to switch or call set_project_dir with the correct path
"""

mcp = FastMCP("altium-copilot", instructions=SERVER_INSTRUCTIONS)
# FastMCP 1.27 reports its framework version unless the low-level server
# version is explicitly set.
mcp._mcp_server.version = _read_version()

# ---------- module-level state ----------
_altium: AltiumClient = AltiumClient()
_project: dict | None = None          # {name, root_dir, prj_pcb_path, sheets: [{name, path}]}
_variant_state: VariantState | None = None
_netlist_last_updated: str | None = None


def _require_project():
    if _project is None or _altium._netlist is None or _variant_state is None:
        raise ValueError("No project loaded. Call set_project_dir first.")
    return _project, _altium._netlist, _variant_state


class PcbSession:
    """Lazy-loading, mtime-cached PCB index for the loaded project."""

    def __init__(self):
        self._index = None
        self._path: str | None = None
        self._file_signature: tuple[int, int] | None = None
        self._netlist_ref: dict | None = None

    def invalidate(self) -> None:
        """Drop parsed PCB state when its schematic mapping input changes."""
        self._index = None
        self._path = None
        self._file_signature = None
        self._netlist_ref = None

    def _load(self, path: str, netlist: dict):
        return PcbIndex(parse_pcb_doc(path), netlist)

    def get(self, project: dict, netlist: dict):
        """Return (index, None) or (None, structured_error)."""
        paths = project.get("pcb_doc_paths") or []
        if not paths:
            return None, {
                "error": "no_pcb_document",
                "message": (
                    f"Project '{project.get('name')}' lists no .PcbDoc. "
                    "PCB tools need a board document in the project."
                ),
            }
        path = paths[0]
        pcb_path = Path(path)
        if not pcb_path.exists():
            return None, {
                "error": "pcb_file_missing",
                "message": f"PCB document not found on disk: {path}",
            }
        stat = pcb_path.stat()
        file_signature = (stat.st_mtime_ns, stat.st_size)
        if (
            self._index is not None
            and self._path == path
            and self._file_signature == file_signature
            and self._netlist_ref is netlist
        ):
            return self._index, None
        try:
            index = self._load(path, netlist)
        except Exception as error:
            return None, {
                "error": "pcb_parse_failed",
                "message": str(error),
            }
        self._index = index
        self._path = path
        self._file_signature = file_signature
        self._netlist_ref = netlist
        return index, None


_pcb_session = PcbSession()


# ---------- detect_altium_project ----------

def _detect_altium_project_impl(info: dict, registry: dict) -> dict:
    if not info.get("running"):
        return {"running": False, "registry": registry}
    if not info.get("project_file"):
        return {
            "running": True,
            "warning": "no_sheet_open",
            "message": (
                "Altium is running but no active schematic sheet was detected. "
                "Open your project in Altium and make sure a schematic sheet is open, then try again."
            ),
            "registry": registry,
        }

    project_path = info.get("project_path", "")
    if not project_path:
        entry = next(
            (e for e in registry["projects"]
             if e["name"].lower() == info["project_file"].lower()),
            None,
        )
        if entry:
            project_path = str(Path(entry["dir"]) / info["project_file"])

    return {
        "running": True,
        "project_file": info["project_file"],
        "project_path": project_path,
        "registry": registry,
    }


@mcp.tool(title="Detect Altium Project", annotations=ToolAnnotations(readOnlyHint=True))
def detect_altium_project() -> str:
    """Detect whether Altium Designer is running, which project is open, and known projects."""
    info = _altium.get_status()
    registry = read_registry()
    result = _detect_altium_project_impl(info, registry)
    current = _read_version()
    result["server_version"] = current
    state = _read_state()
    update_available = state.get("update_available")
    if update_available and _is_newer(update_available, current):
        result["update_available"] = update_available
        result["update_command"] = "irm https://raw.githubusercontent.com/ee-in-a-box/altium-copilot/main/install.ps1 | iex"
    return json.dumps(result, indent=2)


# ---------- set_project_dir ----------

@mcp.tool(title="Load Project", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
def set_project_dir(project_dir: str) -> str:
    """Load an Altium project from disk. Must be called before any other tool.
    If the netlist cache is valid, loads from disk without requiring Altium to be open.
    Otherwise requires Altium Designer to be running with the project open."""
    global _project, _variant_state, _netlist_last_updated

    # Find .PrjPcb upfront — needed by both the cache shortcut and the Altium flow.
    prj_files = list(Path(project_dir).glob("*.PrjPcb")) + list(Path(project_dir).glob("*.prjpcb"))
    if not prj_files:
        return json.dumps({
            "error": "no_prjpcb",
            "message": f"No .PrjPcb file found in {project_dir}. Check the path."
        })
    prj_pcb_path = str(prj_files[0])
    project_name = Path(prj_pcb_path).stem

    # Cache shortcut — if registry has a validated netlist mtime and the .NET file matches,
    # load from disk without requiring Altium to be running or on a schematic sheet.
    _registry = read_registry()
    for _entry in _registry.get("projects", []):
        if Path(_entry.get("dir", "")).resolve() == Path(project_dir).resolve():
            _stored_mtime = _entry.get("netlist_mtime")
            if _stored_mtime is not None:
                _net_matches = (
                    list(Path(project_dir).rglob(f"{project_name}.NET")) or
                    list(Path(project_dir).rglob(f"{project_name}.net"))
                )
                if _net_matches:
                    try:
                        if abs(_net_matches[0].stat().st_mtime - _stored_mtime) < 0.01:
                            prj_data = parse_prj_pcb(prj_pcb_path)
                            if prj_data.sheet_paths:
                                sheets = [{"name": Path(p).stem, "path": p} for p in prj_data.sheet_paths]
                                _project = None
                                _variant_state = None
                                _altium._netlist = None
                                _netlist_last_updated = None
                                _pcb_session.__init__()
                                _altium.load_netlist_from_file(str(_net_matches[0]), project_dir)
                                _project = {
                                    "name": project_name,
                                    "root_dir": project_dir,
                                    "prj_pcb_path": prj_pcb_path,
                                    "sheets": sheets,
                                    "pcb_doc_paths": prj_data.pcb_doc_paths,
                                }
                                _variant_state = VariantState(prj_data.variants)
                                _uid_map = {
                                    comp.get("unique_id"): refdes
                                    for refdes, comp in (_altium._netlist or {}).get("components", {}).items()
                                    if comp.get("unique_id")
                                }
                                _variant_state.resolve_dnp_uid(_uid_map)
                                _netlist_last_updated = datetime.now(timezone.utc).isoformat()
                                upsert_registry_entry(Path(prj_pcb_path).name, project_dir)
                                response = {
                                    "loaded": True,
                                    "project": project_name,
                                    "sheets": [s["name"] for s in sheets],
                                    "sheet_count": len(sheets),
                                    "variants": [v.name for v in prj_data.variants],
                                    "variant_count": len(prj_data.variants),
                                    "netlist_updated_utc": _netlist_last_updated,
                                }
                                _claude_md = (
                                    list(Path(project_dir).glob("CLAUDE.md")) +
                                    list(Path(project_dir).glob("claude.md"))
                                )
                                if _claude_md:
                                    response["project_context"] = _claude_md[0].read_text(encoding="utf-8")
                                return json.dumps(response, indent=2)
                    except Exception as e:
                        logging.warning("Registry cache shortcut failed: %s", e)
            break

    # Full Altium flow — required when cache is absent or stale.
    status = _altium.get_status()
    if not status.get("running"):
        return json.dumps({
            "error": "altium_not_running",
            "message": "Altium Designer is not running. Open Altium with your project before loading.",
        })
    if status.get("warning") == "no_sheet_open":
        return json.dumps({
            "error": "no_sheet_open",
            "message": (
                "Altium is running but no active schematic sheet was detected. "
                "Open a schematic sheet in Altium, then try again."
            ),
        })
    if status.get("tab_type") == "other":
        active_tab = status.get("active_tab") or "unknown"
        return json.dumps({
            "error": "no_schematic_active",
            "message": (
                f"Altium is showing '{active_tab}', not a schematic sheet. "
                "Please click on a schematic sheet tab in Altium and try again."
            ),
        })

    altium_project_file = status.get("project_file", "")
    if altium_project_file.lower() != Path(prj_pcb_path).name.lower():
        return json.dumps({
            "error": "project_mismatch",
            "message": (
                f"Altium has '{altium_project_file}' open, but you asked to load "
                f"'{Path(prj_pcb_path).name}'. Open that project in Altium first, then try again."
            ),
            "altium_open": altium_project_file,
            "requested": Path(prj_pcb_path).name,
        })
    # Clear state before attempting generation — if it fails the server is
    # in a clean "no project loaded" state rather than silently serving stale data.
    _project = None
    _variant_state = None
    _altium._netlist = None
    _netlist_last_updated = None
    _pcb_session.__init__()

    prj_data = parse_prj_pcb(prj_pcb_path)

    if not prj_data.sheet_paths:
        return json.dumps({
            "error": "no_sheets",
            "message": "No .SchDoc sheets found in project. Check the .PrjPcb file."
        })

    sheets = [{"name": Path(p).stem, "path": p} for p in prj_data.sheet_paths]

    try:
        _altium.generate_netlist(prj_pcb_path)
    except RuntimeError as e:
        return json.dumps({
            "error": "netlist_generation_failed",
            "message": str(e),
        })

    _project = {
        "name": Path(prj_pcb_path).stem,
        "root_dir": project_dir,
        "prj_pcb_path": prj_pcb_path,
        "sheets": sheets,
        "pcb_doc_paths": prj_data.pcb_doc_paths,
    }
    _variant_state = VariantState(prj_data.variants)
    _uid_map = {
        comp.get("unique_id"): refdes
        for refdes, comp in (_altium._netlist or {}).get("components", {}).items()
        if comp.get("unique_id")
    }
    _variant_state.resolve_dnp_uid(_uid_map)
    _netlist_last_updated = datetime.now(timezone.utc).isoformat()

    _net_matches = (
        list(Path(project_dir).rglob(f"{project_name}.NET")) or
        list(Path(project_dir).rglob(f"{project_name}.net"))
    )
    _net_mtime = _net_matches[0].stat().st_mtime if _net_matches else None
    upsert_registry_entry(Path(prj_pcb_path).name, project_dir, netlist_mtime=_net_mtime)

    response = {
        "loaded": True,
        "project": _project["name"],
        "sheets": [s["name"] for s in sheets],
        "sheet_count": len(sheets),
        "variants": [v.name for v in prj_data.variants],
        "variant_count": len(prj_data.variants),
        "netlist_updated_utc": _netlist_last_updated,
    }

    claude_md_files = (
        list(Path(project_dir).glob("CLAUDE.md")) +
        list(Path(project_dir).glob("claude.md"))
    )
    if claude_md_files:
        response["project_context"] = claude_md_files[0].read_text(encoding="utf-8")

    return json.dumps(response, indent=2)


# ---------- refresh_netlist ----------

@mcp.tool(title="Refresh Netlist", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
def refresh_netlist() -> str:
    """Refresh the netlist after the user has saved schematic changes in Altium.
    Call this when the user says they changed, added, or saved anything in the schematic.
    Do not call speculatively — only when the user confirms they have saved."""
    global _netlist_last_updated
    try:
        project, _, _ = _require_project()
    except ValueError as e:
        return json.dumps({"error": "no_project", "message": str(e)})
    try:
        regenerated = _altium.generate_netlist(project["prj_pcb_path"])
    except Exception as e:
        return json.dumps({"error": "generate_failed", "message": str(e)})
    if not regenerated:
        return "Netlist is already up to date. If you expected changes, save in Altium and try refresh again."
    _pcb_session.invalidate()
    _netlist_last_updated = datetime.now(timezone.utc).isoformat()
    _rn_name = Path(project["prj_pcb_path"]).stem
    _rn_dir = project["root_dir"]
    _rn_net = (
        list(Path(_rn_dir).rglob(f"{_rn_name}.NET")) or
        list(Path(_rn_dir).rglob(f"{_rn_name}.net"))
    )
    upsert_registry_entry(
        Path(project["prj_pcb_path"]).name,
        _rn_dir,
        netlist_mtime=_rn_net[0].stat().st_mtime if _rn_net else None,
    )
    return json.dumps({"refreshed": True, "netlist_updated_utc": _netlist_last_updated})


# ---------- query_net ----------

def _query_net_impl(netlist: dict, pattern: str) -> str:
    nets = netlist["nets"]

    # Try regex first for discovery (e.g. 'UART' finds MCU_UART_TX and USB_UART_RX).
    # If regex is invalid or finds nothing, fall back to exact case-insensitive match
    # so PCB net names with metacharacters (+5V, VIN[0]) resolve without escaping.
    try:
        regex = re.compile(pattern, re.IGNORECASE)
        matches = [name for name in nets if regex.search(name)]
    except re.error:
        matches = []
    if not matches:
        exact_key = next((k for k in nets if k.lower() == pattern.lower()), None)
        if exact_key is not None:
            matches = [exact_key]

    if not matches:
        return json.dumps({"error": "net_not_found", "pattern": pattern,
                           "message": f"No nets matching '{pattern}'. Use a broader pattern or check the name."})

    if len(matches) > QUERY_NET_MAX_RESULTS:
        return json.dumps({
            "error": "too_many_matches",
            "message": f"Pattern matched {len(matches)} nets (limit: {QUERY_NET_MAX_RESULTS}). Be more specific.",
        })

    results = []
    for net_key in matches:
        all_connections = nets[net_key]
        if len(all_connections) > HIGH_FANOUT_THRESHOLD:
            results.append({
                "net": net_key,
                "pin_count": len(all_connections),
                "warning": "high_fanout",
                "message": (
                    f"Net '{net_key}' has {len(all_connections)} connections — likely a power rail or ground. "
                    "Showing a sample of 10 connections only."
                ),
                "pins_sample": [{"refdes": r, "pin": p} for r, p in all_connections[:10]],
            })
        else:
            results.append({
                "net": net_key,
                "pin_count": len(all_connections),
                "pins": [{"refdes": r, "pin": p} for r, p in all_connections],
            })

    if len(results) == 1:
        return json.dumps(results[0], indent=2)
    return json.dumps({"match_count": len(results), "nets": results}, indent=2)


@mcp.tool(title="Query Net", annotations=ToolAnnotations(readOnlyHint=True),
          meta={"anthropic/maxResultSizeChars": QUERY_NET_MAX_RESULT_SIZE_CHARS})
def query_net(pattern: str) -> str:
    """Find nets by name and return every component pin connected to them.
    Accepts a case-insensitive regex pattern for discovery (e.g. 'UART' finds all
    UART nets, 'SPI_CLK|SPI_CS' finds both, 'GND' finds GND/AGND/DGND).
    If the pattern is not valid regex (e.g. +5V, VIN[0] contain metacharacters),
    it automatically falls back to an exact case-insensitive match — so common
    power rail names like +5V and +3V3 work without escaping.
    High-fanout nets (power rails, ground) are flagged and sampled at 10 pins.
    Use get_sheet_context for full pin-to-net data on a sheet; use this tool to
    discover net names or trace a specific net across sheets."""
    try:
        _, netlist, _ = _require_project()
    except ValueError as e:
        return json.dumps({"error": "no_project", "message": str(e)})
    return _query_net_impl(netlist, pattern)


# ---------- get_component ----------

def _get_component_impl(netlist: dict, variant_state: VariantState, refdes: str) -> str:
    components = netlist.get("components", {})
    matched = next((k for k in components if k.lower() == refdes.lower()), None)
    if matched is None:
        return json.dumps({
            "error": "component_not_found",
            "message": f"Component '{refdes}' not found. Use search_components to find available components.",
        })

    comp = components[matched]
    return json.dumps({
        "refdes": matched,
        "mpn": comp.get("mpn"),
        "description": comp.get("description"),
        "value": comp.get("value"),
        "dnp": variant_state.is_dnp(matched),
        "sheet": comp.get("sheet"),
        "parameters": comp.get("parameters", {}),
        "pins": comp.get("pins", {}),
    }, indent=2)


@mcp.tool(title="Get Component", annotations=ToolAnnotations(readOnlyHint=True))
def get_component(refdes: str) -> str:
    """Get full detail for one component: MPN, value, DNP status, every schematic
    parameter (tolerance, voltage rating, manufacturer, footprint, etc.), and every
    pin with its net. Use this to drill into a specific component and trace its
    connections."""
    try:
        _, netlist, variant_state = _require_project()
    except ValueError as e:
        return json.dumps({"error": "no_project", "message": str(e)})
    return _get_component_impl(netlist, variant_state, refdes)


# ---------- search_components ----------

def _search_components_impl(netlist: dict, pattern: str, search_by: str) -> str:
    if search_by not in ("refdes", "mpn", "description"):
        return json.dumps({
            "error": "invalid_search_by",
            "message": "search_by must be 'refdes', 'mpn', or 'description'",
        })

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return json.dumps({"error": "invalid_pattern", "message": f"Invalid regex: {e}"})

    components = netlist.get("components", {})
    matches: dict = {}
    for refdes, comp in components.items():
        if search_by == "refdes":
            target = refdes
        elif search_by == "mpn":
            target = comp.get("mpn") or ""
        else:
            target = comp.get("description") or ""

        if regex.search(target):
            matches[refdes] = comp

    if len(matches) == len(components):
        return json.dumps({
            "error": "too_many_matches",
            "message": f"Pattern matched all {len(components)} components. Be more specific.",
        })

    # Group by MPN
    groups: dict[str, dict] = {}
    for refdes, comp in matches.items():
        mpn_key = comp.get("mpn") or f"__no_mpn_{refdes}__"
        if mpn_key not in groups:
            groups[mpn_key] = {
                "mpn": comp.get("mpn"),
                "description": comp.get("description"),
                "count": 0,
                "refdes": [],
                "_values": set(),
            }
        groups[mpn_key]["count"] += 1
        groups[mpn_key]["refdes"].append(refdes)
        if comp.get("value"):
            groups[mpn_key]["_values"].add(comp["value"])

    results = []
    for group in groups.values():
        values = group.pop("_values")
        group["value"] = next(iter(values)) if len(values) == 1 else None
        results.append(group)

    return json.dumps({
        "results": results,
        "match_count": sum(g["count"] for g in results),
    }, indent=2)


@mcp.tool(title="Search Components", annotations=ToolAnnotations(readOnlyHint=True))
def search_components(pattern: str, search_by: str = "description") -> str:
    """Search components by regex pattern. search_by: 'refdes', 'mpn', or 'description'.
    Returns components grouped by MPN with counts. Use get_component for full pin detail."""
    try:
        _, netlist, _ = _require_project()
    except ValueError as e:
        return json.dumps({"error": "no_project", "message": str(e)})
    return _search_components_impl(netlist, pattern, search_by)


# ---------- get_sheet_context ----------

def _get_sheet_context_impl(project: dict, netlist: dict, variant_state: VariantState,
                             sheet_name: str | None, altium_status: dict,
                             offset: int = 0) -> str:
    if sheet_name is None:
        if not altium_status.get("running"):
            return json.dumps({
                "warning": "altium_not_running",
                "message": "Altium Designer is not running. Open Altium and try again.",
            })
        active_tab = altium_status.get("active_tab", "")
        # Strip Altium's unsaved-changes marker (" *") from the tab title
        active_tab = active_tab.rstrip(" *").strip()
        tab_to_sheet = {Path(s["path"]).name.lower(): s["name"] for s in project["sheets"]}
        # Altium tab titles may omit the file extension — also index by stem
        tab_to_sheet.update({Path(s["path"]).stem.lower(): s["name"] for s in project["sheets"]})
        matched = tab_to_sheet.get(active_tab.lower())
        if not matched:
            return json.dumps({
                "warning": "active_document_outside_project",
                "active_filename": active_tab,
                "message": (
                    f'"{active_tab}" does not belong to project "{project["name"]}". '
                    "Switch to a sheet in this project."
                ),
            })
        sheet_name = matched
    else:
        matched = next((s["name"] for s in project["sheets"]
                        if s["name"].lower() == sheet_name.lower()), None)
        if matched is None:
            available = [s["name"] for s in project["sheets"]]
            return json.dumps({
                "error": "sheet_not_found",
                "message": f"Sheet '{sheet_name}' not found. Available: {available}",
            })
        sheet_name = matched

    return build_sheet_context(netlist, sheet_name, variant_state, offset)


@mcp.tool(title="Get Sheet Context", annotations=ToolAnnotations(readOnlyHint=True),
          meta={"anthropic/maxResultSizeChars": MAX_RESULT_SIZE_CHARS})
def get_sheet_context(sheet_name: str | None = None, offset: int = 0) -> str:
    """Get all components on a schematic sheet with their pin-to-net connections and
    one-hop cross-sheet neighbors. Pass sheet_name to load any sheet by name — not just
    the active Altium tab. Use this as the FIRST tool for any question about a sheet, and
    again with sheet_name when following cross-sheet signals. Only call query_net or
    get_component afterward for high-fanout nets (>25 pins) or two-hop tracing.

    Results are paginated by character budget. If the response contains has_more:true,
    call this tool again with the offset from the next: line and the same sheet_name,
    and repeat until has_more:false. Accumulate all pages before answering the user."""
    try:
        project, netlist, variant_state = _require_project()
    except ValueError as e:
        return json.dumps({"error": "no_project", "message": str(e)})

    altium_status = _altium.get_status() if sheet_name is None else {}
    return _get_sheet_context_impl(project, netlist, variant_state, sheet_name, altium_status, offset)


# ---------- list_variants ----------

def _list_variants_impl(variant_state: VariantState) -> str:
    variants = []
    for v in variant_state._variants:
        variants.append({
            "name": v.name,
            "dnp_count": len(v.dnp_refdes),
            "dnp_components": v.dnp_refdes,
            "is_active": v.name == variant_state.active.name,
        })
    return json.dumps({
        "active_variant": variant_state.active.name,
        "variants": variants,
    }, indent=2)


@mcp.tool(title="List Variants", annotations=ToolAnnotations(readOnlyHint=True))
def list_variants() -> str:
    """List all project variants and their DNP component lists.
    Call this at session start so the user can choose which variant to work in."""
    try:
        _, _, variant_state = _require_project()
    except ValueError as e:
        return json.dumps({"error": "no_project", "message": str(e)})
    return _list_variants_impl(variant_state)


# ---------- set_active_variant ----------

def _set_active_variant_impl(variant_state: VariantState, variant_name: str) -> str:
    try:
        variant_state.set_variant(variant_name)
        active = variant_state.active
        return json.dumps({
            "active_variant": active.name,
            "dnp_components": active.dnp_refdes,
            "message": f"Switched to variant '{active.name}'. {len(active.dnp_refdes)} components are DNP.",
        }, indent=2)
    except ValueError as e:
        return json.dumps({"error": "variant_not_found", "message": str(e)})


@mcp.tool(title="Set Active Variant", annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
def set_active_variant(variant_name: str) -> str:
    """Switch the active variant. DNP annotations on get_component and get_sheet_context
    will reflect the new variant immediately."""
    try:
        _, _, variant_state = _require_project()
    except ValueError as e:
        return json.dumps({"error": "no_project", "message": str(e)})
    return _set_active_variant_impl(variant_state, variant_name)


def _convert_units(obj, to_mm: bool, inside_mil: bool = False):
    """Convert unit-explicit mil values and containers to millimeters."""
    if not to_mm:
        return obj
    if isinstance(obj, dict):
        converted = {}
        for key, value in obj.items():
            is_mil_key = key.endswith("_mil")
            new_key = key[:-4] + "_mm" if is_mil_key else key
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                converted[new_key] = (
                    round(value * 0.0254, 4)
                    if is_mil_key or inside_mil
                    else value
                )
            else:
                converted[new_key] = _convert_units(
                    value,
                    to_mm,
                    inside_mil or is_mil_key,
                )
        return converted
    if isinstance(obj, list):
        return [
            _convert_units(value, to_mm, inside_mil)
            for value in obj
        ]
    if (
        isinstance(obj, (int, float))
        and not isinstance(obj, bool)
        and inside_mil
    ):
        return round(obj * 0.0254, 4)
    return obj


PcbUnits = Literal["mil", "mm"]


def _pcb_units(index, units: PcbUnits | None) -> tuple[bool, str]:
    resolved = (units or index.pcb.board.display_unit).lower()
    if resolved not in {"mil", "mm"}:
        raise ValueError("units must be 'mil' or 'mm'")
    return resolved == "mm", resolved


def _pcb_units_or_error(index, units: PcbUnits | None):
    try:
        to_mm, resolved = _pcb_units(index, units)
    except (AttributeError, ValueError):
        return None, None, {
            "error": "invalid_units",
            "message": "units must be 'mil' or 'mm'.",
        }
    return to_mm, resolved, None


def _input_to_mil(value: float, units: str) -> float:
    return value / 0.0254 if units == "mm" else value


def _finite_nonnegative(value: float) -> bool:
    return math.isfinite(value) and value >= 0.0


PCB_POLYGON_GEOMETRY_NOTE = (
    "Repour polygons in Altium and save the PcbDoc before relying on polygon "
    "results. These tools model saved nominal polygon outlines, not final "
    "region/fill copper; verify voids, cutouts, removed islands, and "
    "clearances in Altium."
)


def _annotate_dnp(records: list[dict]) -> None:
    if _variant_state is None:
        return
    for record in records:
        refdes = record.get("sch_refdes") or record.get("refdes")
        record["dnp"] = bool(refdes and _variant_state.is_dnp(refdes))


@mcp.tool(
    title="Get Board Info",
    annotations=ToolAnnotations(readOnlyHint=True),
    meta={"anthropic/maxResultSizeChars": QUERY_NET_MAX_RESULT_SIZE_CHARS},
)
def get_board_info(units: PcbUnits | None = None) -> str:
    """Return board geometry, stackup, counts, and data freshness.

    units controls returned coordinates and lengths; it defaults to the
    board's display unit.
    """
    try:
        project, netlist, _ = _require_project()
    except ValueError as error:
        return json.dumps({"error": "no_project", "message": str(error)})
    index, error = _pcb_session.get(project, netlist)
    if error:
        return json.dumps(error)
    board = index.pcb.board
    to_mm, unit_name, units_error = _pcb_units_or_error(index, units)
    if units_error:
        return json.dumps(units_error)
    sides = {
        row["side"]: row["c"]
        for row in index.db.execute(
            "SELECT side, COUNT(*) c FROM components GROUP BY side"
        )
    }
    copper_bbox = index.db.execute(
        "SELECT MIN(minx) a, MIN(miny) b, "
        "MAX(maxx) c, MAX(maxy) d FROM prims"
    ).fetchone()
    if board.outline_vertices:
        outline_x = [
            vertex[0] for vertex in board.outline_vertices
        ]
        outline_y = [
            vertex[1] for vertex in board.outline_vertices
        ]
        board_bbox = {
            "minx_mil": min(outline_x),
            "miny_mil": min(outline_y),
            "maxx_mil": max(outline_x),
            "maxy_mil": max(outline_y),
        }
        extents_source = "board_outline"
    else:
        board_bbox = {
            "minx_mil": copper_bbox["a"],
            "miny_mil": copper_bbox["b"],
            "maxx_mil": copper_bbox["c"],
            "maxy_mil": copper_bbox["d"],
        }
        extents_source = "copper"
    stackup = [
        {
            "name": layer.name,
            "kind": layer.kind,
            "stack_order": layer.stack_order,
            "copper_thick_mil": layer.copper_thick_mil,
            "diel_height_mil": layer.diel_height_mil,
            "diel_const": layer.diel_const,
            "material": layer.material,
        }
        for layer in board.layers
        if layer.stack_order is not None
    ]
    pcb_path = Path(project["pcb_doc_paths"][0])
    result = {
        "pcb_doc": pcb_path.name,
        "last_saved_utc": datetime.fromtimestamp(
            pcb_path.stat().st_mtime,
            tz=timezone.utc,
        ).isoformat(),
        "units": unit_name,
        "origin_mil": {
            "x_mil": board.origin_x,
            "y_mil": board.origin_y,
        },
        "copper_extents_mil": {
            "minx_mil": copper_bbox["a"],
            "miny_mil": copper_bbox["b"],
            "maxx_mil": copper_bbox["c"],
            "maxy_mil": copper_bbox["d"],
        },
        "board_extents_mil": board_bbox,
        "extents_source": extents_source,
        "stackup_source": board.stackup_source,
        "stackup": stackup,
        "netlist_updated_utc": _netlist_last_updated,
        "counts": index.counts(),
        "components_per_side": sides,
        "refdes_mapping_unmatched": index.unmatched_components(),
        "warnings": index.pcb.warnings,
        "skipped_records": index.pcb.skipped_records,
    }
    if result["counts"]["pours"]:
        result["analysis_notes"] = [PCB_POLYGON_GEOMETRY_NOTE]
    if len(project["pcb_doc_paths"]) > 1:
        result["note"] = (
            f"Project lists {len(project['pcb_doc_paths'])} PcbDocs; "
            f"using '{pcb_path.name}'. Others: "
            + ", ".join(
                Path(path).name
                for path in project["pcb_doc_paths"][1:]
            )
        )
    return json.dumps(_convert_units(result, to_mm), indent=2)


def _pcb_index_or_error():
    try:
        project, netlist, _ = _require_project()
    except ValueError as error:
        return None, {"error": "no_project", "message": str(error)}
    return _pcb_session.get(project, netlist)


def _resolve_layer_or_error(index, layer: str | None):
    if layer is None:
        return None, None
    resolved = index.resolve_layer(layer)
    if resolved is None:
        return None, {
            "error": "layer_not_found",
            "available_layers": [
                board_layer.name
                for board_layer in index.pcb.board.layers
                if board_layer.kind == "copper"
            ],
            "message": f"Layer '{layer}' not found.",
        }
    return resolved, None


def _safe_regex(pattern: str) -> bool:
    try:
        re.compile(pattern, re.IGNORECASE)
        return True
    except re.error:
        return False


@mcp.tool(
    title="Get Net PCB Routing",
    annotations=ToolAnnotations(readOnlyHint=True),
    meta={"anthropic/maxResultSizeChars": QUERY_NET_MAX_RESULT_SIZE_CHARS},
)
def get_net_pcb(net: str, units: PcbUnits | None = None) -> str:
    """Return physical PCB routing details for exact or regex-matched nets."""
    index, error = _pcb_index_or_error()
    if error:
        return json.dumps(error)
    to_mm, _, units_error = _pcb_units_or_error(index, units)
    if units_error:
        return json.dumps(units_error)
    exact = next(
        (
            name
            for name in index.pcb.nets
            if name.lower() == net.lower()
        ),
        None,
    )
    matches = (
        [exact]
        if exact
        else (
            [
                name
                for name in index.pcb.nets
                if re.search(net, name, re.IGNORECASE)
            ]
            if _safe_regex(net)
            else []
        )
    )
    if not matches:
        return json.dumps(
            {
                "error": "net_not_found",
                "pattern": net,
                "message": f"No PCB nets matching '{net}'.",
            }
        )
    if len(matches) > QUERY_NET_MAX_RESULTS:
        return json.dumps(
            {
                "error": "too_many_matches",
                "message": (
                    f"Pattern matched {len(matches)} nets "
                    f"(limit {QUERY_NET_MAX_RESULTS}). Be more specific."
                ),
            }
        )
    if len(matches) > 1:
        compact = []
        for match in matches:
            summary = index.net_summary(match)
            compact.append(
                {
                    "net": summary["net"],
                    "layers": [
                        layer["layer"] for layer in summary["layers"]
                    ],
                    "total_length_mil": round(
                        sum(
                            layer["length_mil"]
                            for layer in summary["layers"]
                        ),
                        1,
                    ),
                    "via_count": summary["via_count"],
                    "pad_count": summary["pad_count"],
                }
            )
        return json.dumps(
            _convert_units(
                {
                    "match_count": len(compact),
                    "nets": compact,
                    "hint": (
                        "Call get_net_pcb with an exact name "
                        "for full detail."
                    ),
                },
                to_mm,
            ),
            indent=2,
        )
    summary = index.net_summary(matches[0])
    _annotate_dnp(summary["pads"])
    if summary["pour_count"]:
        summary["geometry_note"] = PCB_POLYGON_GEOMETRY_NOTE
    return json.dumps(_convert_units(summary, to_mm), indent=2)


@mcp.tool(
    title="Get Net Neighbors",
    annotations=ToolAnnotations(readOnlyHint=True),
    meta={"anthropic/maxResultSizeChars": QUERY_NET_MAX_RESULT_SIZE_CHARS},
)
def get_net_neighbors(
    net: str,
    distance: float | None = None,
    layer: str | None = None,
    units: PcbUnits | None = None,
) -> str:
    """Return same-layer proximity and adjacent-layer overlap for a PCB net.

    An explicit distance is expressed in units (default: board display unit).
    Omitting distance uses a physical default of 10 mil.
    """
    index, error = _pcb_index_or_error()
    if error:
        return json.dumps(error)
    to_mm, input_units, units_error = _pcb_units_or_error(index, units)
    if units_error:
        return json.dumps(units_error)
    if distance is not None and not _finite_nonnegative(distance):
        return json.dumps(
            {
                "error": "invalid_distance",
                "message": "distance must be finite and nonnegative.",
            }
        )
    distance_mil = (
        10.0
        if distance is None
        else _input_to_mil(distance, input_units)
    )
    layer_id, layer_error = _resolve_layer_or_error(index, layer)
    if layer_error:
        return json.dumps(layer_error)
    result = index.net_neighbors(
        net,
        distance=distance_mil,
        layer=layer_id,
    )
    if result is None:
        return json.dumps(
            {
                "error": "net_not_found",
                "message": (
                    f"Net '{net}' not found on the PCB. "
                    "Use get_net_pcb with a pattern to discover names."
                ),
            }
        )
    result["geometry_note"] = PCB_POLYGON_GEOMETRY_NOTE
    return json.dumps(_convert_units(result, to_mm), indent=2)


@mcp.tool(
    title="Query PCB Region",
    annotations=ToolAnnotations(readOnlyHint=True),
    meta={"anthropic/maxResultSizeChars": QUERY_NET_MAX_RESULT_SIZE_CHARS},
)
def query_pcb_region(
    x: float,
    y: float,
    radius: float | None = None,
    layer: str | None = None,
    units: PcbUnits | None = None,
) -> str:
    """Return nets, components, and pours near a board coordinate.

    x, y, and an explicit radius are expressed in units (default: board
    display unit). Omitting radius uses a physical default of 50 mil.
    """
    index, error = _pcb_index_or_error()
    if error:
        return json.dumps(error)
    to_mm, input_units, units_error = _pcb_units_or_error(index, units)
    if units_error:
        return json.dumps(units_error)
    if not (math.isfinite(x) and math.isfinite(y)):
        return json.dumps(
            {
                "error": "invalid_coordinate",
                "message": "x and y must be finite.",
            }
        )
    if radius is not None and not _finite_nonnegative(radius):
        return json.dumps(
            {
                "error": "invalid_radius",
                "message": "radius must be finite and nonnegative.",
            }
        )
    x_mil = _input_to_mil(x, input_units)
    y_mil = _input_to_mil(y, input_units)
    radius_mil = (
        50.0
        if radius is None
        else _input_to_mil(radius, input_units)
    )
    layer_id, layer_error = _resolve_layer_or_error(index, layer)
    if layer_error:
        return json.dumps(layer_error)
    result = index.region_query(
        x_mil,
        y_mil,
        radius_mil,
        layer=layer_id,
    )
    _annotate_dnp(result["components"])
    result["geometry_note"] = PCB_POLYGON_GEOMETRY_NOTE
    return json.dumps(_convert_units(result, to_mm), indent=2)


@mcp.tool(
    title="Get Component Placement",
    annotations=ToolAnnotations(readOnlyHint=True),
    meta={"anthropic/maxResultSizeChars": QUERY_NET_MAX_RESULT_SIZE_CHARS},
)
def get_component_placement(
    refdes: str,
    units: PcbUnits | None = None,
) -> str:
    """Return physical placement and nearby-component details."""
    index, error = _pcb_index_or_error()
    if error:
        return json.dumps(error)
    to_mm, _, units_error = _pcb_units_or_error(index, units)
    if units_error:
        return json.dumps(units_error)
    instances = index.component_detail(refdes)
    if not instances:
        try:
            regex = re.compile(refdes, re.IGNORECASE)
            candidates = sorted(
                {
                    row["refdes"]
                    for row in index.db.execute(
                        "SELECT DISTINCT refdes FROM components "
                        "WHERE refdes IS NOT NULL"
                    )
                    if regex.search(row["refdes"])
                }
            )[:10]
        except re.error:
            candidates = []
        return json.dumps(
            {
                "error": "component_not_found",
                "message": f"'{refdes}' not on the PCB.",
                "suggestions": candidates,
            }
        )
    _annotate_dnp(instances)
    for instance in instances:
        _annotate_dnp(instance["nearest_components"])
    return json.dumps(
        _convert_units({"instances": instances}, to_mm),
        indent=2,
    )



SCHEMATIC_REVIEW_PROMPT = """\
Project: {name}
Sheets: {sheets}
Active variant: {active_variant}

You are starting a structured schematic review. Ask the user to choose
a scope before doing anything:
  - A specific sheet (e.g. "{first_sheet}")
  - The full project ({n} sheets, one at a time)

For large projects, consider reviewing each sheet as an independent task dispatched
in parallel — one agent per sheet or functional block. Each agent can self-initialize:
set_project_dir("{root_dir}") → set_active_variant("{active_variant}") →
get_sheet_context(sheet_name="<assigned sheet>"), then run Phases 1–2 and return
their tables. Merge all results into a single Phase 3 report with an added "Sheet" column.

Do not proceed until the user answers.

---

### Phase 1 — Understand Before You Judge

Call get_sheet_context. Each pin already includes connected_to —
the full cross-sheet neighbor list. Use this to trace every signal
source-to-destination. Call query_net only if you need to go two hops deep on a specific net.

For each IC that has external components influencing its operating
behavior, look up its manufacturer datasheet and confirm the parameters
those components set. The datasheet application circuit will tell you
which ones matter.

If you cannot find a datasheet for an IC, say so before proceeding —
do not assume pin functions or parameter values.

Then state explicitly:
  - What you believe this circuit does
  - What each key IC's operating parameters are, sourced from its datasheet
  - Anything you cannot determine from the netlist or datasheets —
    name it, ask about it

Done when: the user has confirmed or corrected your understanding.
Do not proceed to Phase 2 until then.

---

### Phase 2 — Audit (Evidenced Issues Only)

Assume the designer made mistakes. Your job is to find them.

Ground truth rule: the manufacturer datasheet overrides everything —
Altium pin names, net labels, user descriptions. Every finding must
trace to a datasheet value or a measurable netlist fact.
Report only what you can evidence. Do not speculate.

At minimum, check:
1. Pin assignments — does each IC pin connect to what the datasheet
   application circuit requires?
2. Passive values — do component values produce correct operating
   parameters per datasheet formulas?
3. Signal continuity — use connected_to on each critical pin to trace
   source-to-destination; verify correct termination and that every
   expected endpoint appears
4. Cross-sheet nets — use query_net with broad patterns to enumerate
   all cross-sheet references; flag dangling or unexpected appearances
5. Failure modes — for each sub-circuit: what happens if inputs are out
   of range, or a passive is off by 10%?

For circuit types that require it, apply first principles beyond this
list. The topology determines what matters.

Done when: you have worked through the checklist and any additional
checks the circuit demands. Do not proceed to Phase 3 until then.

---

### Phase 3 — Document

Present findings as three Markdown tables:

  Table 1 — Critical Issues
  | Component | Issue | Datasheet Requires | Schematic Shows |

  Table 2 — Warnings & Nitpicks
  | Component | Observation |

  Table 3 — Verified Critical Nets
  | Net | Source → Destination | Result |

Ask: "Any sub-circuits to dive deeper into, or alternative
architectures to brainstorm?"
"""


@mcp.tool(title="Schematic Review", annotations=ToolAnnotations(readOnlyHint=True))
def schematic_review() -> str:
    """Start a structured schematic review. Call when the user explicitly asks to review
    or verify the schematic (e.g. 'review this', 'check my schematic', 'do a design review',
    'is this correct?', 'does this look right?'). Do not call for general questions."""
    if _project is None or _altium._netlist is None or _variant_state is None:
        return json.dumps({
            "error": "no_project",
            "message": (
                "No project loaded. Run the session-start flow first: "
                "detect_altium_project → set_project_dir → list_variants → set_active_variant."
            ),
        })

    sheets = [s["name"] for s in _project["sheets"]]
    active_variant = _variant_state.active.name
    first_sheet = sheets[0] if sheets else "Power_Supply"
    n = len(sheets)
    name = _project["name"]

    return SCHEMATIC_REVIEW_PROMPT.format(
        name=name,
        sheets=", ".join(sheets),
        active_variant=active_variant,
        first_sheet=first_sheet,
        n=n,
        root_dir=_project["root_dir"],
    )



BRAINSTORM_CIRCUITS_PROMPT = """\
You are starting a structured circuit brainstorming session.
Follow these phases in order. Ask one question at a time — never more than one per message.

## Ground Rules

- Do not state component values, voltage ratings, current limits, pin assignments, or any other
  specs from memory. If you need to reference a specific part, use web search to find its datasheet first.
- Do not recommend a specific component unless you have verified its key specs from a datasheet
  or authoritative source during this session.
- If you are uncertain about a topology's behavior or limitations, say so and search before advising.

---

## Phase 0 — Context (skip if no project is loaded)

If a project is loaded, use the available tools before asking the user anything:
- Call get_sheet_context on the active or most relevant sheet.
- If the user mentioned a specific sub-circuit or net, call query_net and get_component to understand it.
- Summarize what is already on the relevant sheet(s) in one short paragraph: what the circuit does,
  key components, and any obvious constraints visible in the design.

If no project is loaded, skip to Phase 1.

---

## Phase 1 — Problem statement

Ask the user one open-ended question: "What does this circuit need to do?"

Do not assume a topology, domain, or electrical spec yet. If the answer is vague or could be
interpreted multiple ways, name what is confusing and ask again before moving on.

---

## Phase 2 — Constraints (one question at a time)

Based on the circuit type that emerged from Phase 1, identify which specs would most change your
topology recommendation. Ask about them one at a time — do not send a list of questions.

Stop asking once you have enough to propose meaningful options. State any assumptions you are
making before moving to Phase 3.

---

## Phase 3 — Propose 2–3 topologies

Lead with the simplest viable option. For each topology:
- Name it clearly.
- List key tradeoffs: complexity, cost, parts count, performance.
- Give one reason to choose it and one reason to skip it.

State your assumptions explicitly. Do not recommend an approach before completing Phase 2.

---

## Phase 4 — Fit check (skip if no project is loaded)

Before the user commits to an approach, check the existing design:
- Use search_components to find components that might already serve a similar role.
- Use query_net to check whether relevant power rails or signal nets already exist.

Do not guess from memory — verify with tools. If the design already has something relevant, say so.

---

## Phase 5 — Design summary

Once the user selects an approach:
- Summarize: topology chosen, key specs agreed, suggested components with brief reasoning.
- List any open questions that remain before layout can begin.

Do not suggest implementation steps or specific part numbers until the user approves this summary.
"""


@mcp.tool(title="Brainstorm Circuits", annotations=ToolAnnotations(readOnlyHint=True))
def brainstorm_circuits() -> str:
    """Start a structured circuit brainstorming session. Call when the user is asking
    how to design, improve, or choose an approach for a circuit — not just when they
    say "brainstorm". Works with or without a loaded project."""
    return BRAINSTORM_CIRCUITS_PROMPT


# ---------- package_for_xfn ----------

def _package_for_xfn_impl(
    project: dict,
    netlist: dict,
    variant_state,
    version: str,
) -> str:
    try:
        db_path = export_project(project, netlist, variant_state, version)
    except Exception as e:
        return json.dumps({"error": "export_failed", "message": str(e)})
    prj_pcb_name = Path(project["prj_pcb_path"]).name
    registry_warning = ""
    try:
        mark_xfn_exported(prj_pcb_name)
    except Exception as error:
        logging.warning(
            "Snapshot exported but registry update failed: %s",
            error,
        )
        registry_warning = (
            "\nWarning: snapshot export succeeded, but the local registry "
            f"could not be updated: {error}"
        )
    return (
        f"Exported to: {db_path}\n"
        "Share this file with your cross-functional team via Slack or a shared drive.\n"
        "Do not commit it to Git — it is a binary snapshot and will cause repository bloat."
        f"{registry_warning}"
    )


@mcp.tool(
    title="Package for Cross-Functional Team",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def package_for_xfn() -> str:
    """Export the current schematic project to a portable .db snapshot file for the
    cross-functional team. Only call this tool when the user explicitly asks to package
    or export the project for sharing with firmware, mechanical, test, or reliability
    engineers. Do not call speculatively."""
    try:
        project, netlist, variant_state = _require_project()
    except ValueError:
        return json.dumps({
            "error": "no_project",
            "message": "No project loaded. Ask the user to open a project in Altium first.",
        })
    return _package_for_xfn_impl(project, netlist, variant_state, _read_version())


if __name__ == "__main__":
    if "--version" in sys.argv:
        print(f"altium-copilot v{_read_version()}")  # noqa: T201
        sys.exit(0)
    threading.Thread(target=_check_for_update, args=(_read_version(),), daemon=True).start()
    try:
        mcp.run()
    finally:
        # After the MCP stdio transport closes, Python's exit sequence tries to
        # flush sys.stdout, which is now a closed pipe → ValueError.  Redirect to
        # devnull so the process exits cleanly and Claude Desktop doesn't see a
        # crashed server on next load.
        try:
            sys.stdout = open(os.devnull, "w")
            sys.stderr = open(os.devnull, "w")
        except Exception:
            pass
