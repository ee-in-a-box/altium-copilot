# Altium Copilot

[![CI](https://github.com/ee-in-a-box/altium-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/ee-in-a-box/altium-copilot/actions/workflows/ci.yml)
[![Downloads](https://img.shields.io/github/downloads/ee-in-a-box/altium-copilot/total?color=brightgreen)](https://github.com/ee-in-a-box/altium-copilot/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)]()

**Software engineers have Claude Code. Hardware engineers have been pasting netlists into chat.**

> Read the full writeup → [maisamp.github.io](https://maisamp.github.io/posts/altium-copilot/)

Altium Copilot gives Claude real-time read access to your open Altium project. Ask it about component values, trace a net across sheets, review your schematic, brainstorm a circuit — all from your Claude chat interface, grounded in your actual design files.

For now, the copilot is read-only. It only extracts data. It cannot modify your schematic, move components, or overwrite your `.PrjPcb` file, **more features coming soon.**

Part of the [ee-in-a-box](https://github.com/ee-in-a-box) suite.

![Demo](assets/Intro.gif)



---

## What it does

| What you ask | What happens |
|---|---|
| *"What's connected to the 3.3V net?"* | Traces the net across all sheets |
| *"What's different in the Prototype variant?"* | Compares DNP lists between variants |
| *"Review this power supply circuit"* | Structured multi-phase schematic review |
| *"What does U12 do?"* | Pulls component, all pins, connected nets |

---

## Specialist modes

Claude activates these automatically based on what you say — no commands needed.

| Mode | Triggers when you say... | What happens |
|---|---|---|
| `schematic_review` | *"review this"*, *"is this correct?"*, *"check my power supply"* | 3-phase structured audit: Claude reads datasheets and confirms its understanding before flagging anything. Every finding cites a datasheet value or a netlist fact. Report saved to markdown. |
| `brainstorm_circuits` | *"I want to add a new circuit, lets brainstorm"*, *"How would i improve this circuit"*, *"What power supply topology should I use here?"*  | 5-phase design session: reads your loaded schematic first, then asks one question at a time — problem, constraints, proposes 2–3 topologies with tradeoffs, checks your existing design before recommending anything new. |

---

## Requirements

- Windows
- [Altium Designer](https://www.altium.com/altium-designer) (must be running with a project open)
- [Claude Desktop](https://claude.ai/download) — works with Pro and Enterprise subscriptions

---

## Install

### Claude Desktop

1. Install [Claude Desktop](https://claude.ai/download)
2. Open **PowerShell** (search `powershell` in the Start menu) and run:
   ```powershell
   irm https://raw.githubusercontent.com/ee-in-a-box/altium-copilot/main/install.ps1 | iex
   ```
3. Open Altium Designer with your project loaded
4. Open Claude Desktop and start asking

### Claude Code

1. Install [Claude Code](https://claude.ai/claude-code)
2. Open **PowerShell** and run:
   ```powershell
   irm https://raw.githubusercontent.com/ee-in-a-box/altium-copilot/main/install.ps1 | iex
   ```
3. Open Altium Designer with your project loaded
4. Start a new Claude Code session and start asking

---

## Usage

Once installed, open Claude and ask anything about your schematic — the copilot detects your running Altium instance and orients itself to your project automatically.

**Example prompts:**
- *"What's connected to the 3.3V net?"*
- *"What's U4 doing on this page?"*
- *"What's different between my schematic variants?"*
- *"How should i improve this circuit?"*
- *"Is this power supply circuit correct?"* — triggers a structured design review automatically

---

## Privacy

Your data stays yours. The MCP server runs locally, doesn't log anything, and doesn't phone home. All schematic data is sent only to Claude via your own Enterprise or Pro subscription.

---

## 🚀 NEW: Sharing with your team

Want to share the same capabilities with firmware, mechanical, and test engineers without them needing an Altium license?

Ask Claude to package your project:

> *"Package this Altium project to share with the cross functional team"* / *"Export this Altium project for sharing"*

Claude calls `package_for_xfn`, which writes a portable SQLite snapshot (`.db`) next to your `.PrjPcb`. Share that file with your team via Confluence, Slack, or a shared drive.

Your teammates open it with **[pcb-copilot](https://github.com/ee-in-a-box/pcb-copilot)** — a companion MCP server that gives Claude the same schematic Q&A tools against the snapshot, no Altium license required. Pairs well with the free [Altium 365 Viewer](https://www.altium.com/altium-365/viewer) for visual reference alongside the AI Q&A.

---

## What i'm experimenting with next

- **PCB layout understanding** — same live-access model, extended to the board layer
- **Simulator** — walks you through simulating and validating your design before you spin a board
- **Librarian** — periodic audits of your component libraries, flags stale or discontinued entries
- **Supply Chain Expert** — component availability, lead times, alternatives, and sourcing risk

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

For bug reports and support, open an issue at [github.com/ee-in-a-box/altium-copilot/issues](https://github.com/ee-in-a-box/altium-copilot/issues).

---

## License

MIT © Maisam Pyarali
