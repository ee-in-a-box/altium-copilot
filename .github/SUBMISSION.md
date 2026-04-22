# Anthropic Desktop Extension Submission

Submission form: claude.com/docs/connectors/building/submission → "Desktop extension submission form"

---

## Server Basics

**Name:** Altium Copilot
**Version:** 0.1.4
**Description:** AI copilot for Altium Designer (Windows only). Reads live schematics from a running Altium instance — trace nets, inspect components, switch variants, and run structured design reviews, all from Claude. Requires Altium Designer installed and running on Windows.
**Author:** Maisam Pyarali
**Homepage / Repo:** https://github.com/ee-in-a-box/altium-copilot
**License:** MIT
**Platform:** Windows only (`win32`)
**Bundle file:** `dist/altium-copilot-0.1.1.mcpb`

---

## Connection Details

**Type:** Desktop Extension (local stdio process — no network server, no open ports)
**Transport:** stdio
**Requirements:** Altium Designer (any recent licensed version) running on the same Windows machine
**No user configuration required at install time** — Altium's project path is auto-detected via the Windows registry

---

## Tools (13 total)

| Tool | Read-only | Description |
|------|-----------|-------------|
| `detect_altium_project` | Yes | Detect Altium status and list known projects from local registry |
| `set_project_dir` | No* | Load project, parse .PrjPcb, generate netlist via Altium automation |
| `refresh_netlist` | No* | Re-generate netlist after user saves changes in Altium |
| `query_net` | Yes | Trace net connectivity; returns pins and one-hop neighbors |
| `get_component` | Yes | Full component detail: MPN, value, DNP flag, pin-to-net table |
| `search_components` | Yes | Regex search across refdes, MPN, or description |
| `search_nets` | Yes | Regex search across net names, returns pins inline |
| `get_sheet_context` | Yes | All components and connections on a schematic sheet |
| `list_variants` | Yes | All project variants and their DNP component lists |
| `set_active_variant` | No* | Switch active variant; updates DNP state in memory |
| `schematic_review` | Yes | Trigger structured 3-phase schematic review workflow |
| `brainstorm_circuits` | Yes | Trigger structured 5-phase circuit brainstorming workflow |

*Writes are in-memory only or trigger Altium's own built-in export — no schematic source files are modified.

---

## Example Prompts

```
"Is Altium running? What project do you see?"
"Load my Altium project at C:\Projects\MyBoard"
"I just saved a change to the schematic — please refresh"
"Trace the VCC net and tell me everything connected to it"
"Give me the full details for U4 — MPN, value, and all pins"
"Find all TVS diodes in the design"
"List every SPI net in the project"
"What components and connections are on the Power Management sheet?"
"What variants does this project have and what parts are DNP in each?"
"Switch to the Production variant"
"Save this review as power-rail-review.md"
"Review my schematic for power integrity issues"
"Brainstorm a 12V to 3.3V buck converter with at least 2A output"
```

---

## Privacy & Data Handling

- **No data leaves the device.** The extension reads local schematic files and returns data directly to Claude Desktop. Nothing is uploaded to any remote server.
- **No telemetry or analytics.**
- **Local writes** are limited to `%USERPROFILE%\.ee-in-a-box\` — project registry, update state, and optional user-saved review reports.
- **One outbound read:** on startup, the extension fetches a version string from GitHub Releases to check for updates. No user data is sent. Users can block this by restricting outbound access to `github.com`.
- **No credentials or secrets are accessed or stored.**

---

## Documentation & Privacy Policy Links

- README: https://github.com/ee-in-a-box/altium-copilot#readme
- Privacy policy: https://github.com/ee-in-a-box/altium-copilot/blob/main/.github/PRIVACY.md
- Changelog: https://github.com/ee-in-a-box/altium-copilot/blob/main/CHANGELOG.md
- Logo (PNG): https://raw.githubusercontent.com/ee-in-a-box/altium-copilot/main/assets/icon.png

---

## Reviewer Instructions

### Without Altium (structure test)
1. Install `altium-copilot-0.1.1.mcpb` via Claude Desktop → Settings → Extensions → Install Extension
2. Ask: *"Is Altium running?"*
3. Extension returns `{"error": "altium_not_running", ...}` — verify Claude surfaces this gracefully

### With Altium (full test)
1. Open Altium Designer on Windows with any `.PrjPcb` project
2. Tell Claude: *"Load my project at C:\path\to\project"*
3. Altium briefly shows a "Generating Netlist" dialog (~5 seconds) — this is the extension triggering Altium's built-in Design → Netlist → Protel export via keystroke automation
4. All 13 tools are now active — run the example prompts above

### Security notes
- Local stdio process only — no open ports, no network server
- Keyboard automation is scoped to Altium Designer's window
- Writes only to `%USERPROFILE%\.ee-in-a-box\`
- No credentials accessed

### Update model
- Users who installed from the directory receive updates automatically when a new version is published
- Each new release: bump `version` in `manifest.json`, run `.\pack.ps1`, submit updated `.mcpb` via the submission form
