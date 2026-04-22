# Local Testing — altium-copilot.mcpb

## Prerequisites

- Claude Desktop installed (latest version)
- Altium Designer installed and licensed
- An Altium project (.PrjPcb) you can open for testing

## Install the bundle

1. Open Claude Desktop
2. Go to **Settings → Extensions → Advanced settings → Install Extension**
3. Drag and drop `dist/altium-copilot-0.1.1.mcpb` onto the window
4. Claude Desktop will display the extension name, description, and tool list
5. Click **Install** — no configuration prompts should appear (the extension needs no user-supplied paths)

## Smoke tests

Open a new conversation in Claude Desktop with Altium running and a project open, then run each prompt:

### 1. Detection
> "Is Altium running?"

Expected: Claude calls `detect_altium_project` and reports the open project name and known projects from your registry.

### 2. Load project
> "Load my project from C:\path\to\my\project"

Expected: Claude calls `set_project_dir`, parses the .PrjPcb, generates a netlist, and reports sheet count and variant count.

### 3. Net tracing
> "What is connected to the VCC net?"

Expected: Claude calls `query_net("VCC")` and lists all pins and one-hop neighbors.

### 4. Component lookup
> "Tell me about U1"

Expected: Claude calls `get_component("U1")` and returns the MPN, value, and pin-to-net table.

### 5. Component search
> "Find all decoupling capacitors"

Expected: Claude calls `search_components` with a description pattern and returns grouped results.

### 6. Net search
> "List all SPI nets"

Expected: Claude calls `search_nets("SPI")` and returns matching net names with pins.

### 7. Sheet context
> "What's on the power sheet?"

Expected: Claude calls `get_sheet_context` for the power sheet.

### 8. Variants
> "What variants does this project have?"

Expected: Claude calls `list_variants` and shows variant names and DNP lists.

### 9. Switch variant
> "Switch to the production variant"

Expected: Claude calls `set_active_variant` and confirms the switch.

### 10. Schematic review
> "Review my schematic"

Expected: Claude calls `schematic_review` and begins a 3-phase structured review.

### 11. Brainstorm
> "Brainstorm a 5V buck converter circuit for me"

Expected: Claude calls `brainstorm_circuits` and begins a structured 5-phase session.

### 12. Refresh after edit
> (Make a change in Altium, save it, then say) "I just saved a change in Altium"

Expected: Claude calls `refresh_netlist` and confirms the netlist was regenerated.

## What to verify

- No permission prompts beyond what is described above appear during install
- All 12 tool calls succeed without errors
- The extension does not request network access (all data stays local)
- Review files appear in `%USERPROFILE%\.ee-in-a-box\schematic-reviews\`

## Uninstall

Settings → Extensions → altium-copilot → Remove
