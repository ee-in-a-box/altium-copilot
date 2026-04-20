from pathlib import Path


def parse_protel_netlist(path) -> dict:
    """Parse a Protel .NET file into nets and an inverted pin index.

    Returns:
        {
            "nets": {net_name: [(refdes, pin), ...]},
            "pin_to_net": {refdes: {pin: net_name}},
        }
    """
    nets: dict[str, list[tuple[str, str]]] = {}
    pin_to_net: dict[str, dict[str, str]] = {}

    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()

    in_comp_block = False
    in_net_block = False
    current_net: str | None = None

    for line in lines:
        s = line.strip()

        if s == "[":
            in_comp_block = True
            continue
        if s == "]":
            in_comp_block = False
            continue
        if in_comp_block:
            continue

        if s == "(":
            in_net_block = True
            current_net = None
            continue
        if s == ")":
            in_net_block = False
            current_net = None
            continue
        if not in_net_block or not s:
            continue

        if current_net is None:
            current_net = s
            nets[current_net] = []
        else:
            idx = s.rfind("-")
            if idx <= 0:
                continue
            refdes = s[:idx]
            pin = s[idx + 1:]
            nets[current_net].append((refdes, pin))
            pin_to_net.setdefault(refdes, {})[pin] = current_net

    return {"nets": nets, "pin_to_net": pin_to_net}
