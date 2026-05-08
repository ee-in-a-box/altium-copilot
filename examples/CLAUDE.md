# [Board Name] — system context

> The schematic is the source of truth for *what is connected to what*. This doc is for everything the schematic can't tell you: what this board is, who it talks to, why it exists, and the few conceptual traps to avoid. Keep it short. If a line of this doc would need editing because a component, value, or net name changed, it doesn't belong here — that detail lives in the schematic.

## What this is

[One paragraph. What does this board do? Where does it live in the system — what sits upstream and downstream of it? What assembly or product does it belong to? What are the two or three things it is responsible for?]

## Glossary

Terms Claude might confuse — define them precisely here.

- **[Term A] vs. [Term B]** — [Term A] is X. [Term B] is Y. They are often confused because Z.
- **[Vendor term] vs. [internal term]** — [explain which name appears in the schematic and which appears in datasheets/docs]
- **[Connector or signal name]** — [what it carries, why it matters, any gotchas]

## System-level constraints

Requirements that define the operating envelope. These don't change with PCB revision.

- **[Power rail]:** [voltage range, tolerance, max current]
- **[Bus or interface]:** [protocol, speed, isolation requirements]
- **[Continuous / peak power]:** [values and conditions]
- **[Timing constraint]:** [requirement and why it exists]
- **[Isolation barrier]:** [what is isolated from what, and why]
- **[Environmental]:** [temperature range, humidity, ingress protection if relevant]

## How to query the schematic

Use the altium-copilot MCP tools — don't try to remember values from a previous session:

- `get_sheet_context` — all components on a sheet with pin-to-net connections; start here
- `get_component` — full detail for a specific refdes (e.g. U4, J2)
- `query_net` — trace a net by name across all sheets
- `list_variants` — see DNP differences between variants

Active variant matters. Check which variant is selected before reading DNP status.

## Where things live

One-line pointer per resource — link or path, whatever is accessible.

- **Requirements doc:** [link or location]
- **Block diagram:** [link or location]
- **Design files / PCB:** [link or location]
- **Test reports:** [link or location]
- **Component datasheets:** [link or location]

## Owner

[Name] — [email or contact]
