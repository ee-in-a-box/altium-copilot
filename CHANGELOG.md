# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)

## [0.3.20] - 2026-04-19

### Added
- `schematic_review` tool — triggers a structured multi-phase design review automatically when you ask Claude to review a schematic. Claude audits components against datasheets, flags errors, and writes findings to a markdown report. Auto-triggers on explicit review intent; no manual invocation needed.
- Update notice in `detect_altium_project` — if a newer version is available, the server surfaces it directly in the tool result so you see it without leaving your chat.

### Changed
- Clearer install instructions in the README — both Claude Desktop and Claude Code sections now use numbered steps so setup is unambiguous.

### Removed
- `start_design_review` tool — replaced by `schematic_review`, which is smarter about when to activate and produces the same structured output.

## [0.2.5] - 2026-04-16

### Added
- `search_nets` tool — find nets by keyword without knowing exact names
- `start_design_review` tool — structured multi-phase design review with datasheet lookups
- Auto-update: server checks for new releases on startup and shows a banner
- `refresh_netlist` tool — reload netlist after saving changes in Altium
- MCP-native install via `irm | iex` PowerShell installer (no Python required)

### Changed
- `generate_netlist` returns bool (`True` = regenerated, `False` = cache hit)
- Netlist timestamp field renamed to `netlist_updated_utc` for clarity

## [0.1.0] - 2026-04-08

### Added
- Initial release
- `detect_altium_project`, `set_project_dir`, `list_variants`, `set_active_variant`
- `get_sheet_context`, `get_component`, `query_net`, `search_components`
- Variant-aware netlist with DNP support
- PyInstaller build + `.mcpb` packaging
