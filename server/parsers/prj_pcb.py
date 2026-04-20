import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VariantDefinition:
    name: str
    dnp_refdes: list[str] = field(default_factory=list)


@dataclass
class PrjPcbData:
    sheet_paths: list[str]
    variants: list[VariantDefinition]


def parse_prj_pcb(path: str) -> PrjPcbData:
    text = Path(path).read_text(encoding="utf-8-sig")
    project_dir = Path(path).parent
    sections = _split_sections(text)
    sheet_paths = _extract_sheets(sections, project_dir)
    variants = _extract_variants(sections)
    return PrjPcbData(sheet_paths=sheet_paths, variants=variants)


def _split_sections(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_header: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^\[(.+)\]\s*$", line)
        if m:
            if current_header is not None:
                sections.append((current_header, current_lines))
            current_header = m.group(1)
            current_lines = []
        elif current_header is not None:
            current_lines.append(line)
    if current_header is not None:
        sections.append((current_header, current_lines))
    return sections


def _get_field(lines: list[str], key: str) -> str | None:
    for line in lines:
        m = re.match(rf"^\s*{re.escape(key)}\s*=\s*(.*)\s*$", line, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def _parse_inline_props(s: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in s.split("|"):
        if "=" in part:
            key, _, val = part.partition("=")
            result[key.strip()] = val.strip()
    return result


def _extract_sheets(sections: list[tuple[str, list[str]]], project_dir: Path) -> list[str]:
    sheets: list[str] = []
    for header, lines in sections:
        if not re.match(r"^Document\d+$", header, re.IGNORECASE):
            continue
        raw = _get_field(lines, "DocumentPath")
        if not raw:
            continue
        normalized = raw.replace("\\", "/")
        if not normalized.lower().endswith(".schdoc"):
            continue
        abs_path = str((project_dir / normalized).resolve())
        sheets.append(abs_path)
    return sheets


def _extract_variants(sections: list[tuple[str, list[str]]]) -> list[VariantDefinition]:
    headers = [h for h, _ in sections]
    if any(re.match(r"^ProjectVariant\d+$", h, re.IGNORECASE) for h in headers):
        return _extract_format_a(sections)
    if any(re.match(r"^Variation\d+$", h, re.IGNORECASE) for h in headers):
        return _extract_format_b(sections)
    return [VariantDefinition(name="Default")]


def _extract_format_a(sections: list[tuple[str, list[str]]]) -> list[VariantDefinition]:
    variants: list[VariantDefinition] = []
    for header, lines in sections:
        if not re.match(r"^ProjectVariant\d+$", header, re.IGNORECASE):
            continue
        name = _get_field(lines, "Description")
        if not name:
            continue
        dnp: list[str] = []
        for line in lines:
            m = re.match(r"^\s*Variation\d+=(.+)$", line, re.IGNORECASE)
            if not m:
                continue
            props = _parse_inline_props(m.group(1))
            designator = props.get("Designator", "")
            kind = props.get("Kind", "")
            alternate = props.get("AlternatePart", "")
            if designator and kind == "1" and alternate == "":
                dnp.append(designator)
        variants.append(VariantDefinition(name=name, dnp_refdes=dnp))
    return variants or [VariantDefinition(name="Default")]


class VariantState:
    def __init__(self, variants: list[VariantDefinition]):
        self._variants = variants
        self._active = variants[0] if variants else VariantDefinition(name="Default")

    def set_variant(self, name: str) -> None:
        match = next((v for v in self._variants if v.name.lower() == name.lower()), None)
        if match is None:
            available = [v.name for v in self._variants]
            raise ValueError(f"Variant '{name}' not found. Available: {available}")
        self._active = match

    def is_dnp(self, refdes: str) -> bool:
        return refdes in self._active.dnp_refdes

    @property
    def active(self) -> VariantDefinition:
        return self._active

def _extract_format_b(sections: list[tuple[str, list[str]]]) -> list[VariantDefinition]:
    variants: list[VariantDefinition] = []
    for header, lines in sections:
        if re.match(r"^Variation\d+$", header, re.IGNORECASE):
            name = _get_field(lines, "VariantName")
            if name:
                variants.append(VariantDefinition(name=name))

    active: VariantDefinition | None = None
    for header, lines in sections:
        if re.match(r"^Variation\d+$", header, re.IGNORECASE):
            name = _get_field(lines, "VariantName")
            active = next((v for v in variants if v.name == name), None)
        elif re.match(r"^CompVar\d+$", header, re.IGNORECASE) and active:
            kind = _get_field(lines, "VariantKind")
            if kind == "3":
                refdes = _get_field(lines, "RefDesignator1")
                if refdes:
                    active.dnp_refdes.append(refdes)

    return variants or [VariantDefinition(name="Default")]
