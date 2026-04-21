# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)


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
