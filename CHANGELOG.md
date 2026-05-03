# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [0.2.1] - 2026-05-03

### Fixed
- Netlist generation now retries on focus acquisition timeout and mid-sequence focus loss (another window stealing focus) instead of surfacing an error immediately — up to 3 attempts before giving up
- PowerShell focus poll reduced from 10 s to 5 s so transient failures retry faster; worst-case total wait drops from 30 s to 15 s

---

## [0.2.0] - 2026-05-03

### Added
- `package_for_xfn` tool — exports the loaded project to a portable SQLite `.db` snapshot that cross-functional team members (firmware, mechanical, test, reliability) can query with [pcb-copilot](https://github.com/ee-in-a-box/pcb-copilot) without needing Altium
- SQLite export schema: `project`, `sheets`, `variants`, `components`, `nets`, `pins` tables with indexed lookups; `nets.pin_count` for fanout queries
- Registry now stamps `last_exported_xfn` timestamp on every successful `package_for_xfn` call
- `CONTRIBUTING.md`: DB schema versioning guidelines — bump `SCHEMA_VERSION` in `export.py` and `SUPPORTED_SCHEMA_VERSION` in pcb-copilot on any schema change

### Removed
- `--update` self-update command — the one-line `install.ps1` installer handles updates; in-chat update notifications are retained

### Fixed
- Registry writes are now atomic (write to `.tmp` then `os.replace`) — no corruption on crash or power loss
- Connection leak in SQLite export when an exception occurred mid-write; now always closes the connection in `finally`
- Swallowed `OSError` in export rollback path — exceptions now propagate correctly
- Duplicate `HIGH_FANOUT_THRESHOLD` definition removed (was defined in both `export.py` and `main.py`)

### Internal
- 330 lines of new test coverage: `test_export.py`, `test_package_for_xfn.py`, registry tests for `mark_xfn_exported`
- `.gitignore`: added `*-pcb-copilot.db` (binary export snapshots) and `.worktrees/`

---

## [0.1.10] - 2026-04-23

### Internal
- Release workflow now runs lint and tests before building — a failing test blocks the release

---

## [0.1.9] - 2026-04-23

### Fixed
- Netlist foreground acquisition now uses `AttachThreadInput` so `SetForegroundWindow` reliably succeeds even when Altium is behind another window or minimized; focus poll timeout extended to 10s (was 1.5s) — no keystrokes are sent if focus is never confirmed
- Settle time after focus increased to 2s; ESC sent before menu sequence to clear any residual state; inter-keystroke delay increased to 50ms

---

## [0.1.7] - 2026-04-23

### Fixed
- Subsheet fan-out suffix matching extended: numeric-only suffixes with a separator now matched, chained segments now matched and bare numeric suffixes without a separator correctly rejected (`C111`)

---

## [0.1.6] - 2026-04-22

### Fixed
- MCP server initialization timeout on cold starts: update check now runs on a background thread so `mcp.run()` starts immediately instead of blocking on a GitHub HTTP call
- Subsheet fan-out pin enrichment: refdes suffix matching now handles all separator styles (`_`, `.`, `-`, none), any case, multi-letter suffixes, and trailing digits

---

## [0.1.5] - 2026-04-22

### Fixed
- Netlist keystroke reliability on slow machines: increased inter-keystroke delay from 1ms to 10ms, added 1s settle wait after Altium gains focus before sending the first key (prevents dropped Alt+D on slower PCs)
- Added ESC after netlist generation (with 1s delay) to dismiss any lingering Altium dialog
- Clear error when a non-schematic tab is active (homepage, Extensions and Updates, etc.) — instead of timing out with a confusing "check Altium is responsive" message, Claude now tells you to click on a schematic sheet tab

### Removed
- `save_schematic_review` tool — unnecessary overhead; ask Claude to write the review directly if you want it saved

### Internal
- Scoped pytest to `tests/` directory to prevent vendor directory crash on collection

---

## [0.1.4] - 2026-04-20

### Changed
- `brainstorm_circuits` trigger broadened — now fires on any question about topology, architecture, or how to design/improve a sub-circuit, not just when the user says "brainstorm"
- `brainstorm_circuits` docstring updated to match

---

## [0.1.3] - 2026-04-20

### Changed
- `get_sheet_context` is now the primary tool for all circuit questions, not just design reviews — server instructions guide Claude to start every question with a single bulk sheet load before falling back to `query_net` or `get_component`
- Cross-sheet tracing now uses `get_sheet_context(sheet_name=X)` instead of calling `get_component` one-by-one for each cross-sheet neighbor — significantly faster on dense, multi-sheet designs
- `get_sheet_context` docstring updated to make the cross-sheet and general Q&A use cases explicit

---

## [0.1.2] - 2026-04-20

### Changed
- Added `title` and `readOnlyHint`/`destructiveHint` annotations to all 13 tools — Claude Desktop now surfaces correct read/write intent for each tool call
- Schematic review prompt refactored to a template string — same review behavior, cleaner internals
- `manifest.json`: richer description, author GitHub URL, repository metadata, otter icon

### Added
- `assets/icon.png` — otter icon displayed in Claude Desktop Extensions UI when installed via `.mcpb`

---

## [0.1.1] - 2026-04-20

### Changed
- Removed `.mcpb` packaging — installer downloads the `.exe` directly, no bundle needed
- Simplified release workflow: dropped Node.js dependency and checksums generation

## [0.1.0] - 2026-04-19

### Added
- Initial release
- `detect_altium_project` — detects your running Altium instance and surfaces known projects
- `set_project_dir` — loads a project and builds the netlist context Claude works from
- `list_variants` / `set_active_variant` — switch between project variants; DNP components are excluded automatically
- `get_sheet_context` — reads the active schematic sheet and summarizes components on it
- `get_component` — pulls a component's description, parameters, and all connected nets by refdes
- `query_net` — traces a net across all sheets and returns every pin connected to it
- `search_components` — finds components by refdes, MPN, or description using regex
- `search_nets` — finds nets by keyword without needing exact names
- `refresh_netlist` — reloads the netlist after saving changes in Altium
- `schematic_review` — structured 3-phase design review: reads datasheets, audits against them, saves findings to a markdown report
- `brainstorm_circuits` — 5-phase design session: reads your loaded schematic, asks constraints, proposes topologies with tradeoffs
- Auto-update: server checks for new releases on startup and notifies you in chat
- One-line installer via PowerShell (`irm | iex`) — no Python required
- PyInstaller build — ships as a standalone `.exe`, no Python required
