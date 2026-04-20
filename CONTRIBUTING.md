# Contributing to Altium Copilot

## How contributions work

`main` is protected — no one can push to it directly, including maintainers.
All changes go through a pull request and require:
- Passing CI (lint + tests)
- An approving review from a maintainer

**To contribute:**
1. Fork the repo
2. Create a branch (`git checkout -b my-feature`)
3. Make your changes and ensure `pytest` passes locally
4. Open a PR against `main`

Only maintainers can tag a release (`git tag v*`), which is what triggers the
build and publish workflow. Contributors cannot ship a release.

---

## Prerequisites

- Windows (the MCP uses PowerShell to talk to Altium Designer)
- Python 3.13+ with a virtual environment
- Node.js (for `npx @anthropic-ai/mcpb`)

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install pyinstaller
```

## Running locally (no build needed)

```bash
.venv\Scripts\python server/main.py
```

Or register it directly with Claude Code:

```json
{
  "mcpServers": {
    "altium-copilot": {
      "command": "C:\\path\\to\\altium-copilot\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\altium-copilot\\server\\main.py"]
    }
  }
}
```

## Running tests

```bash
.venv\Scripts\pytest
```

## Releasing a new version

Releases are fully automated via GitHub Actions (`.github/workflows/release.yml`).
Push a version tag and the workflow builds the binary, packs the `.mcpb`, and
publishes a GitHub Release — no manual build steps needed.

```bash
git tag v0.2.0
git push origin v0.2.0
```

The workflow:
1. Reads the version from the tag (`v0.2.0` → `0.2.0`)
2. Patches `manifest.json` with that version
3. Compiles `server/dist/altium-copilot.exe` with PyInstaller on a Windows runner
4. Packs `altium-copilot-0.2.0.mcpb` with `npx @anthropic-ai/mcpb pack`
5. Creates a GitHub Release with the `.mcpb` as the downloadable asset

Users who already have the MCP installed will get updated instructions automatically
the next time the server starts (guidance is embedded in `SERVER_INSTRUCTIONS` and
takes effect immediately without any reinstallation step).

### Building locally (for testing before a release)

```bash
.venv\Scripts\pip install pyinstaller

.venv\Scripts\pyinstaller `
    --onefile `
    --name altium-copilot `
    --distpath server/dist `
    --workpath build `
    --add-data "server/scripts;scripts" `
    --paths server `
    server/main.py
```

Test the resulting `server/dist/altium-copilot.exe` on a machine **without Python installed** before tagging.

## How the bundle works

| What | Where it lives |
|------|---------------|
| Server code + Python runtime | compiled into `server/dist/altium-copilot.exe` by PyInstaller |
| PowerShell scripts | embedded in the `.exe` via `--add-data`; extracted to `sys._MEIPASS/scripts/` at runtime |

The `manifest.json` `mcp_config.command` points to the `.exe` directly, so Claude
Desktop needs nothing else on the PATH.

## Project structure

```
server/
  main.py          — MCP tool definitions (FastMCP)
  altium.py        — Altium Designer client (PowerShell bridge)
  netlist_parser.py
  parsers/         — .PrjPcb and .SchDoc parsers
  services/        — registry, sheet context, and page netlist helpers
  scripts/         — PowerShell scripts called at runtime
  dist/            — compiled binary (git-ignored, produced by PyInstaller)

tests/             — pytest suite
```

## What gets shipped

The GitHub Release contains only `altium-copilot.exe` and `checksums.txt`.
Python source, tests, docs, and the `.venv` are never shipped to end users.
