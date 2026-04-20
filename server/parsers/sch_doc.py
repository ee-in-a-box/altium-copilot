import re
import struct
from dataclasses import dataclass, field

import olefile

_MPN_RE = re.compile(r"^Manufacturer Part Number( (\d+))?$", re.IGNORECASE)


@dataclass
class ComponentMeta:
    refdes: str = ""
    description: str | None = None
    mpn: str | None = None
    value: str | None = None
    pins: dict[str, str] = field(default_factory=dict)  # pin_number -> pin_name


def parse_sch_doc(path: str) -> dict[str, ComponentMeta]:
    """Parse an Altium .SchDoc OLE file and return component metadata keyed by refdes.

    The OwnerIndex field in child records (pins, designators, parameters) refers to
    the 0-based sequential record number of the parent RECORD=1 minus 1, i.e. the
    record immediately preceding the component record in the file stream.
    """
    with olefile.OleFileIO(path) as f:
        data = f.openstream("FileHeader").read()

    # Parsing state
    # Key: owner_key = record_num - 1 for the RECORD=1 entry
    components_by_owner: dict[int, ComponentMeta] = {}
    # Map owner_key of duplicate parts (same UniqueID) to the canonical owner_key
    canonical_owner: dict[int, int] = {}   # any owner_key -> canonical owner_key
    uid_seen: dict[str, int] = {}          # UniqueID -> canonical owner_key
    best_mpn_priority: dict[int, int] = {} # canonical owner_key -> lowest suffix seen (0 = best)

    offset = 0
    record_num = 0
    while offset < len(data):
        if offset + 4 > len(data):
            break
        rec_len = struct.unpack_from("<I", data, offset)[0]
        if rec_len == 0 or rec_len > 500_000:
            break
        rec_bytes = data[offset + 4 : offset + 4 + rec_len]
        text = rec_bytes.decode("latin-1")

        m = re.search(r"\|RECORD=(\d+)", text)
        if m:
            record_type = int(m.group(1))
            props = _parse_props(text)
            # owner_key for a RECORD=1 at record_num is (record_num - 1),
            # matching the OwnerIndex used by child records.
            if record_type == 1:
                _handle_component(
                    props, record_num, components_by_owner, canonical_owner, uid_seen
                )
            elif record_type == 34:
                _handle_designator(props, components_by_owner, canonical_owner)
            elif record_type == 2:
                _handle_pin(props, components_by_owner, canonical_owner)
            elif record_type == 41:
                _handle_parameter(
                    props, components_by_owner, canonical_owner, best_mpn_priority
                )
            # RECORD=17 (power ports) intentionally skipped

        offset += 4 + rec_len
        record_num += 1

    return {comp.refdes: comp for comp in components_by_owner.values() if comp.refdes}


def _parse_props(text: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for part in text.split("|"):
        if "=" in part:
            key, _, val = part.partition("=")
            key = key.strip()
            val = val.strip()
            if key.startswith("%UTF8%"):
                # The record was decoded as latin-1, so %UTF8% values are
                # latin-1 bytes that are actually UTF-8. Re-encode→decode to
                # get the correct Unicode (e.g. "ÂµF" → "µF").
                try:
                    val = val.encode("latin-1").decode("utf-8")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
                props[key[6:]] = val
            elif key not in props:
                props[key] = val
    return props


def _handle_component(
    props: dict[str, str],
    record_num: int,
    components_by_owner: dict[int, ComponentMeta],
    canonical_owner: dict[int, int],
    uid_seen: dict[str, int],
) -> None:
    # The owner_key used by child records equals record_num - 1
    owner_key = record_num - 1
    uid = props.get("UniqueID", "")
    desc = props.get("ComponentDescription") or None

    if uid and uid in uid_seen:
        # Subsequent part of a multi-part component — map to canonical owner_key
        canonical_owner[owner_key] = uid_seen[uid]
    else:
        comp = ComponentMeta(description=desc)
        components_by_owner[owner_key] = comp
        canonical_owner[owner_key] = owner_key
        if uid:
            uid_seen[uid] = owner_key


def _handle_designator(
    props: dict[str, str],
    components_by_owner: dict[int, ComponentMeta],
    canonical_owner: dict[int, int],
) -> None:
    if props.get("Name") != "Designator":
        return
    owner_str = props.get("OwnerIndex")
    text = props.get("Text", "")
    if not owner_str or not text:
        return
    key = canonical_owner.get(int(owner_str), int(owner_str))
    if key in components_by_owner:
        components_by_owner[key].refdes = text


def _handle_pin(
    props: dict[str, str],
    components_by_owner: dict[int, ComponentMeta],
    canonical_owner: dict[int, int],
) -> None:
    owner_str = props.get("OwnerIndex")
    name = props.get("Name", "")
    designator = props.get("Designator", "")
    if not owner_str or not designator:
        return
    if not name or name == "?":
        return
    key = canonical_owner.get(int(owner_str), int(owner_str))
    if key in components_by_owner:
        components_by_owner[key].pins[designator] = name


def _handle_parameter(
    props: dict[str, str],
    components_by_owner: dict[int, ComponentMeta],
    canonical_owner: dict[int, int],
    best_mpn_priority: dict[int, int],
) -> None:
    owner_str = props.get("OwnerIndex")
    name = props.get("Name", "")
    text = props.get("Text", "")
    if not owner_str or not text or text.startswith('"'):
        return
    key = canonical_owner.get(int(owner_str), int(owner_str))
    if key not in components_by_owner:
        return
    comp = components_by_owner[key]

    if name == "Value":
        comp.value = text
        return

    m = _MPN_RE.match(name)
    if m:
        # Priority: no suffix (0) beats suffix 1 beats suffix 2 etc.
        priority = int(m.group(2)) if m.group(2) else 0
        if priority < best_mpn_priority.get(key, 999):
            comp.mpn = text
            best_mpn_priority[key] = priority
        return

    # Fall back to Comment as MPN when no Manufacturer Part Number exists.
    # Comment is used as the primary part number in many Altium libraries.
    if name == "Comment" and best_mpn_priority.get(key, 999) == 999:
        comp.mpn = text
