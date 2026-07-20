"""Parser for Altium .PcbDoc OLE compound files.

Pure parsing only: OLE streams -> dataclasses. No MCP or index logic here.
All lengths and coordinates are converted to float mils at parse time.
"""

import math
import re
import struct
from dataclasses import dataclass, field

import olefile

ALTIUM_UNITS_PER_MIL = 10000
MM_PER_MIL = 0.0254
NO_NET = 0xFFFF
NO_COMPONENT = 0xFFFF

_DIM_RE = re.compile(r"^\s*(-?[\d.]+(?:[eE][+-]?\d+)?)\s*(mil|mm)?\s*$")


def parse_dim_mil(raw: str | None) -> float | None:
    """Parse an Altium dimension string into mils."""
    if not raw:
        return None
    match = _DIM_RE.match(raw)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    if match.group(2) == "mm":
        return value / MM_PER_MIL
    return value


def read_text_records(data: bytes) -> list[dict[str, str]]:
    """Decode u32-length-prefixed, pipe-delimited text-property records."""
    records: list[dict[str, str]] = []
    offset = 0
    while offset + 4 <= len(data):
        (record_length,) = struct.unpack_from("<I", data, offset)
        if record_length == 0 or offset + 4 + record_length > len(data):
            break
        text = (
            data[offset + 4 : offset + 4 + record_length]
            .rstrip(b"\x00")
            .decode("latin-1", "replace")
        )
        properties: dict[str, str] = {}
        for part in text.split("|"):
            if "=" in part:
                key, _, value = part.partition("=")
                properties[key.strip().upper()] = value
        records.append(properties)
        offset += 4 + record_length
    return records


@dataclass
class Primitive:
    """One copper or geometry primitive normalized to mils."""

    kind: str
    layer: int
    net: int | None
    component: int | None
    x1: float
    y1: float
    x2: float
    y2: float
    width: float
    height: float | None = None
    rotation: float = 0.0
    shape: int | None = None
    source_id: int | None = None
    layer_to: int | None = None
    hole: float | None = None
    pad_name: str | None = None
    pour_id: int | None = None


def iter_binary_records(data: bytes):
    """Yield (record_type, payload) from u8-type/u32-length records."""
    offset = 0
    while offset + 5 <= len(data):
        record_type = data[offset]
        (record_length,) = struct.unpack_from("<I", data, offset + 1)
        if offset + 5 + record_length > len(data):
            break
        yield (
            record_type,
            data[offset + 5 : offset + 5 + record_length],
        )
        offset += 5 + record_length


def _units_to_mil(units: int) -> float:
    return units / ALTIUM_UNITS_PER_MIL


def _optional_index(value: int, sentinel: int) -> int | None:
    return None if value == sentinel else value


def _valid_layer(layer: int) -> bool:
    return 0 < layer <= 82


def decode_tracks(data: bytes) -> tuple[list[Primitive], int]:
    """Decode Tracks6 records."""
    primitives: list[Primitive] = []
    skipped = 0
    for record_type, payload in iter_binary_records(data):
        if (
            record_type != 4
            or len(payload) < 33
            or not _valid_layer(payload[0])
        ):
            skipped += 1
            continue
        net = struct.unpack_from("<H", payload, 3)[0]
        component = struct.unpack_from("<H", payload, 7)[0]
        x1, y1, x2, y2, width = struct.unpack_from(
            "<iiiii",
            payload,
            13,
        )
        if width <= 0:
            skipped += 1
            continue
        primitives.append(
            Primitive(
                kind="track",
                layer=payload[0],
                net=_optional_index(net, NO_NET),
                component=_optional_index(component, NO_COMPONENT),
                x1=_units_to_mil(x1),
                y1=_units_to_mil(y1),
                x2=_units_to_mil(x2),
                y2=_units_to_mil(y2),
                width=_units_to_mil(width),
            )
        )
    return primitives, skipped


def decode_vias(data: bytes) -> tuple[list[Primitive], int]:
    """Decode Vias6 records."""
    primitives: list[Primitive] = []
    skipped = 0
    for record_type, payload in iter_binary_records(data):
        if record_type != 3 or len(payload) < 31:
            skipped += 1
            continue
        layer_from, layer_to = payload[29], payload[30]
        if not (_valid_layer(layer_from) and _valid_layer(layer_to)):
            skipped += 1
            continue
        net = struct.unpack_from("<H", payload, 3)[0]
        component = struct.unpack_from("<H", payload, 7)[0]
        x, y, diameter, hole = struct.unpack_from("<iiii", payload, 13)
        if diameter <= 0 or hole < 0 or hole > diameter:
            skipped += 1
            continue
        x_mil = _units_to_mil(x)
        y_mil = _units_to_mil(y)
        primitives.append(
            Primitive(
                kind="via",
                layer=layer_from,
                layer_to=layer_to,
                net=_optional_index(net, NO_NET),
                component=_optional_index(component, NO_COMPONENT),
                x1=x_mil,
                y1=y_mil,
                x2=x_mil,
                y2=y_mil,
                width=_units_to_mil(diameter),
                hole=_units_to_mil(hole),
            )
        )
    return primitives, skipped


ARC_CHORD_STEP_DEG = 30.0
ARC_MAX_SAGITTA_MIL = 0.25


def decode_arcs(data: bytes) -> tuple[list[Primitive], int]:
    """Decode Arcs6 records into chord segments for proximity math."""
    primitives: list[Primitive] = []
    skipped = 0
    for arc_id, (record_type, payload) in enumerate(
        iter_binary_records(data)
    ):
        if (
            record_type != 1
            or len(payload) < 45
            or not _valid_layer(payload[0])
        ):
            skipped += 1
            continue
        try:
            net = struct.unpack_from("<H", payload, 3)[0]
            component = struct.unpack_from("<H", payload, 7)[0]
            center_x, center_y = struct.unpack_from("<ii", payload, 13)
            (radius,) = struct.unpack_from("<i", payload, 21)
            start_angle, end_angle = struct.unpack_from("<dd", payload, 25)
            (width,) = struct.unpack_from("<i", payload, 41)
        except struct.error:
            skipped += 1
            continue
        if (
            radius <= 0
            or width < 0
            or not math.isfinite(start_angle)
            or not math.isfinite(end_angle)
        ):
            skipped += 1
            continue
        if width == 0 and net == NO_NET:
            # Component/mechanical outline arcs can legitimately be zero-width
            # and netless; they are not copper primitives for these tools.
            continue
        if width == 0:
            skipped += 1
            continue
        center_x_mil = _units_to_mil(center_x)
        center_y_mil = _units_to_mil(center_y)
        radius_mil = _units_to_mil(radius)
        sweep = (end_angle - start_angle) % 360.0 or 360.0
        adaptive_step = math.degrees(
            2.0
            * math.acos(
                max(
                    -1.0,
                    1.0 - min(ARC_MAX_SAGITTA_MIL / radius_mil, 2.0),
                )
            )
        )
        chord_step = min(
            ARC_CHORD_STEP_DEG,
            max(adaptive_step, 0.5),
        )
        steps = max(2, math.ceil(sweep / chord_step))
        points = [
            (
                center_x_mil
                + radius_mil
                * math.cos(math.radians(start_angle + sweep * index / steps)),
                center_y_mil
                + radius_mil
                * math.sin(math.radians(start_angle + sweep * index / steps)),
            )
            for index in range(steps + 1)
        ]
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            primitives.append(
                Primitive(
                    kind="arc",
                    layer=payload[0],
                    net=_optional_index(net, NO_NET),
                    component=_optional_index(component, NO_COMPONENT),
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    width=_units_to_mil(width),
                    source_id=arc_id,
                )
            )
    return primitives, skipped


_PAD_SUBRECORD_COUNT = 5
_PAD_MAIN_INDEX = 3
_PAD_MAIN_MIN_LENGTH = 60


def decode_pads(data: bytes) -> tuple[list[Primitive], int]:
    """Decode Pads6 multi-subrecord records."""
    primitives: list[Primitive] = []
    skipped = 0
    offset = 0
    while offset + 5 <= len(data):
        record_type = data[offset]
        (name_length,) = struct.unpack_from("<I", data, offset + 1)
        if offset + 5 + name_length > len(data):
            break
        name_blob = data[offset + 5 : offset + 5 + name_length]
        pad_name = (
            name_blob[1 : 1 + name_blob[0]].decode("latin-1", "replace")
            if name_blob
            else ""
        )
        position = offset + 5 + name_length
        subrecords: list[bytes] = []
        truncated = False
        for _ in range(_PAD_SUBRECORD_COUNT):
            if position + 4 > len(data):
                truncated = True
                break
            (subrecord_length,) = struct.unpack_from("<I", data, position)
            if position + 4 + subrecord_length > len(data):
                truncated = True
                break
            subrecords.append(
                data[position + 4 : position + 4 + subrecord_length]
            )
            position += 4 + subrecord_length
        if truncated:
            break
        offset = position
        main = subrecords[_PAD_MAIN_INDEX]
        if (
            record_type != 2
            or len(main) < _PAD_MAIN_MIN_LENGTH
            or not _valid_layer(main[0])
        ):
            skipped += 1
            continue
        net = struct.unpack_from("<H", main, 3)[0]
        component = struct.unpack_from("<H", main, 7)[0]
        x, y = struct.unpack_from("<ii", main, 13)
        (
            size_x,
            size_y,
            _mid_size_x,
            _mid_size_y,
            _bottom_size_x,
            _bottom_size_y,
            hole,
        ) = struct.unpack_from("<iiiiiii", main, 21)
        shape = main[49]
        (rotation,) = struct.unpack_from("<d", main, 52)
        if size_x <= 0 or size_y <= 0 or hole < 0:
            skipped += 1
            continue
        x_mil = _units_to_mil(x)
        y_mil = _units_to_mil(y)
        primitives.append(
            Primitive(
                kind="pad",
                layer=main[0],
                net=_optional_index(net, NO_NET),
                component=_optional_index(component, NO_COMPONENT),
                x1=x_mil,
                y1=y_mil,
                x2=x_mil,
                y2=y_mil,
                width=_units_to_mil(size_x),
                height=_units_to_mil(size_y),
                rotation=rotation if math.isfinite(rotation) else 0.0,
                shape=shape,
                hole=_units_to_mil(hole),
                pad_name=pad_name,
            )
        )
    return primitives, skipped


@dataclass
class PcbLayer:
    """One physical stackup or legacy board layer."""

    v6_id: int | None
    name: str
    kind: str
    stack_order: int | None
    copper_thick_mil: float | None = None
    diel_height_mil: float | None = None
    diel_const: float | None = None
    material: str | None = None


@dataclass
class BoardInfo:
    """Board coordinate system and layer metadata."""

    origin_x: float | None
    origin_y: float | None
    sheet_x: float | None
    sheet_y: float | None
    sheet_width: float | None
    sheet_height: float | None
    display_unit: str
    layers: list[PcbLayer]
    stackup_source: str
    outline_vertices: list[tuple[float, float]] = field(
        default_factory=list
    )


@dataclass
class PcbComponent:
    """A Components6 placement record."""

    index: int
    refdes: str | None
    source_uid_tail: str | None
    channel_path: str | None
    x: float | None
    y: float | None
    rotation: float | None
    side: str


@dataclass
class PolygonPour:
    """A polygon-pour outline and its copper identity."""

    pour_id: int
    net: int | None
    layer: int | None
    hatch_style: str | None
    vertices: list[tuple[float, float]]


def decode_board(records: list[dict[str, str]]) -> BoardInfo:
    """Decode Board6 text properties into coordinate and stackup metadata."""
    properties = records[0] if records else {}
    name_to_v6: dict[str, int] = {}
    for key, value in properties.items():
        match = re.fullmatch(r"LAYER(\d+)NAME", key)
        if match:
            name_to_v6[value.lower()] = int(match.group(1))

    layers: list[PcbLayer] = []
    order = 0
    stackup_source = "legacy"
    while True:
        prefix = f"V9_STACK_LAYER{order}_"
        if f"{prefix}NAME" not in properties:
            break
        stackup_source = "v9"
        name = properties[f"{prefix}NAME"]
        copper_thickness = parse_dim_mil(
            properties.get(f"{prefix}COPTHICK")
        )
        dielectric_height = parse_dim_mil(
            properties.get(f"{prefix}DIELHEIGHT")
        )
        if copper_thickness is not None:
            kind = "copper"
        elif (
            dielectric_height is not None
            or f"{prefix}DIELTYPE" in properties
        ):
            kind = "dielectric"
        else:
            kind = "non-stack"
        dielectric_constant = properties.get(f"{prefix}DIELCONST")
        layers.append(
            PcbLayer(
                v6_id=name_to_v6.get(name.lower()),
                name=name,
                kind=kind,
                stack_order=order,
                copper_thick_mil=copper_thickness,
                diel_height_mil=dielectric_height,
                diel_const=(
                    float(dielectric_constant)
                    if dielectric_constant
                    else None
                ),
                material=properties.get(f"{prefix}DIELMATERIAL"),
            )
        )
        order += 1

    stack_names = {layer.name.lower() for layer in layers}
    for layer_name, v6_id in sorted(
        name_to_v6.items(),
        key=lambda item: item[1],
    ):
        if layer_name not in stack_names:
            layers.append(
                PcbLayer(
                    v6_id=v6_id,
                    name=properties[f"LAYER{v6_id}NAME"],
                    kind="non-stack",
                    stack_order=None,
                )
            )

    if stackup_source == "legacy":
        layers = [
            PcbLayer(
                v6_id=v6_id,
                name=properties[f"LAYER{v6_id}NAME"],
                kind="copper" if v6_id <= 32 else "non-stack",
                stack_order=None,
            )
            for _layer_name, v6_id in sorted(
                name_to_v6.items(),
                key=lambda item: item[1],
            )
        ]

    outline_vertices: list[tuple[float, float]] = []
    vertex_index = 0
    while (
        f"VX{vertex_index}" in properties
        and f"VY{vertex_index}" in properties
    ):
        x = parse_dim_mil(properties[f"VX{vertex_index}"])
        y = parse_dim_mil(properties[f"VY{vertex_index}"])
        if x is not None and y is not None:
            outline_vertices.append((x, y))
        vertex_index += 1

    return BoardInfo(
        origin_x=parse_dim_mil(properties.get("ORIGINX")),
        origin_y=parse_dim_mil(properties.get("ORIGINY")),
        sheet_x=parse_dim_mil(properties.get("SHEETX")),
        sheet_y=parse_dim_mil(properties.get("SHEETY")),
        sheet_width=parse_dim_mil(properties.get("SHEETWIDTH")),
        sheet_height=parse_dim_mil(properties.get("SHEETHEIGHT")),
        display_unit=(
            "mil" if properties.get("DISPLAYUNIT", "1") == "1" else "mm"
        ),
        layers=layers,
        stackup_source=stackup_source,
        outline_vertices=outline_vertices,
    )


def decode_nets(records: list[dict[str, str]]) -> list[str]:
    """Decode Nets6 record order into the PCB net-name table."""
    return [
        record.get("NAME", f"__unnamed_{index}")
        for index, record in enumerate(records)
    ]


def decode_components(
    records: list[dict[str, str]],
) -> list[PcbComponent]:
    """Decode Components6 placement and schematic-source metadata."""
    components: list[PcbComponent] = []
    for index, record in enumerate(records):
        source_uid = record.get("SOURCEUNIQUEID", "")
        rotation_raw = record.get("ROTATION")
        try:
            rotation = float(rotation_raw) if rotation_raw else None
        except ValueError:
            rotation = None
        components.append(
            PcbComponent(
                index=index,
                refdes=record.get("SOURCEDESIGNATOR") or None,
                source_uid_tail=(
                    source_uid.rsplit("\\", 1)[-1] if source_uid else None
                ),
                channel_path=(
                    record.get("SOURCEHIERARCHICALPATH") or None
                ),
                x=parse_dim_mil(record.get("X")),
                y=parse_dim_mil(record.get("Y")),
                rotation=rotation,
                side=(
                    "bottom"
                    if record.get("LAYER", "").upper() == "BOTTOM"
                    else "top"
                ),
            )
        )
    return components


def decode_polygons(
    records: list[dict[str, str]],
    layer_name_to_v6: dict[str, int],
) -> tuple[list[PolygonPour], list[Primitive]]:
    """Decode pour outlines for containment and proximity queries."""
    pours: list[PolygonPour] = []
    edges: list[Primitive] = []
    for pour_id, record in enumerate(records):
        vertices: list[tuple[float, float]] = []
        vertex_index = 0
        while (
            f"VX{vertex_index}" in record
            and f"VY{vertex_index}" in record
        ):
            x = parse_dim_mil(record[f"VX{vertex_index}"])
            y = parse_dim_mil(record[f"VY{vertex_index}"])
            if x is not None and y is not None:
                vertices.append((x, y))
            vertex_index += 1
        net_raw = record.get("NET")
        layer = layer_name_to_v6.get(record.get("LAYER", "").lower())
        pour = PolygonPour(
            pour_id=pour_id,
            net=int(net_raw) if net_raw and net_raw.isdigit() else None,
            layer=layer,
            hatch_style=record.get("HATCHSTYLE"),
            vertices=vertices,
        )
        pours.append(pour)
        if layer is None or len(vertices) < 3:
            continue
        closed = vertices + [vertices[0]]
        for (x1, y1), (x2, y2) in zip(closed, closed[1:]):
            edges.append(
                Primitive(
                    kind="track",
                    layer=layer,
                    net=pour.net,
                    component=None,
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    width=0.0,
                    pour_id=pour_id,
                )
            )
    return pours, edges


@dataclass
class PcbData:
    """Parsed PCB content ready for indexing."""

    board: BoardInfo
    nets: list[str]
    components: list[PcbComponent]
    primitives: list[Primitive]
    pours: list[PolygonPour]
    layer_name_to_v6: dict[str, int]
    warnings: list[str] = field(default_factory=list)
    skipped_records: dict[str, int] = field(default_factory=dict)


def _build_layer_aliases(board: BoardInfo) -> dict[str, int]:
    aliases = {
        layer.name.lower(): layer.v6_id
        for layer in board.layers
        if layer.v6_id is not None
    }
    aliases.setdefault("top", 1)
    aliases.setdefault("bottom", 32)
    # Altium's V6 signal-layer numbering is fixed regardless of stack size:
    # 1 = Top, 2..31 = Mid1..Mid30, 32 = Bottom. Polygons6 (and other text
    # streams) reference inner copper layers by this positional alias rather
    # than by LAYERnNAME, so it must be resolvable even though no board we've
    # seen actually populates all 30 mid slots.
    for mid_index in range(1, 31):
        aliases.setdefault(f"mid{mid_index}", mid_index + 1)
    return aliases


def parse_streams(streams: dict[str, bytes]) -> PcbData:
    """Assemble parsed PCB data from raw OLE stream bytes."""
    warnings: list[str] = []
    skipped_records: dict[str, int] = {}

    def text(stream: str) -> list[dict[str, str]]:
        if stream not in streams:
            warnings.append(f"{stream.split('/')[0]} stream missing")
            return []
        try:
            return read_text_records(streams[stream])
        except Exception as error:
            warnings.append(
                f"{stream.split('/')[0]} parse failed: {error}"
            )
            return []

    try:
        board = decode_board(text("Board6/Data"))
    except Exception as error:
        warnings.append(f"Board6 parse failed: {error}")
        board = decode_board([])
    try:
        nets = decode_nets(text("Nets6/Data"))
    except Exception as error:
        warnings.append(f"Nets6 parse failed: {error}")
        nets = []
    try:
        components = decode_components(text("Components6/Data"))
    except Exception as error:
        warnings.append(f"Components6 parse failed: {error}")
        components = []
    layer_aliases = _build_layer_aliases(board)

    primitives: list[Primitive] = []
    binary_decoders = (
        ("Tracks6/Data", decode_tracks),
        ("Vias6/Data", decode_vias),
        ("Arcs6/Data", decode_arcs),
        ("Pads6/Data", decode_pads),
    )
    for stream, decoder in binary_decoders:
        stream_name = stream.split("/")[0]
        if stream not in streams:
            warnings.append(f"{stream_name} stream missing")
            continue
        try:
            decoded, skipped = decoder(streams[stream])
        except Exception as error:
            warnings.append(f"{stream_name} parse failed: {error}")
            continue
        primitives.extend(decoded)
        if skipped:
            skipped_records[stream_name] = skipped

    pours: list[PolygonPour] = []
    if "Polygons6/Data" in streams:
        try:
            pours, edges = decode_polygons(
                text("Polygons6/Data"),
                layer_aliases,
            )
            primitives.extend(edges)
        except Exception as error:
            warnings.append(f"Polygons6 parse failed: {error}")
    else:
        warnings.append("Polygons6 stream missing")

    valid_primitives = []
    invalid_net_count = 0
    for primitive in primitives:
        if primitive.net is not None and primitive.net >= len(nets):
            invalid_net_count += 1
            continue
        valid_primitives.append(primitive)
    if invalid_net_count:
        skipped_records["net_range"] = invalid_net_count

    return PcbData(
        board=board,
        nets=nets,
        components=components,
        primitives=valid_primitives,
        pours=pours,
        layer_name_to_v6=layer_aliases,
        warnings=warnings,
        skipped_records=skipped_records,
    )


_WANTED_STREAMS = (
    "Board6/Data",
    "Nets6/Data",
    "Components6/Data",
    "Tracks6/Data",
    "Vias6/Data",
    "Arcs6/Data",
    "Pads6/Data",
    "Polygons6/Data",
)


def parse_pcb_doc(path: str) -> PcbData:
    """Read a .PcbDoc OLE file and parse the streams used by PCB tools."""
    streams: dict[str, bytes] = {}
    read_warnings: list[str] = []
    with olefile.OleFileIO(path) as ole:
        available = {"/".join(stream) for stream in ole.listdir()}
        for stream in _WANTED_STREAMS:
            if stream in available:
                try:
                    streams[stream] = ole.openstream(stream).read()
                except Exception as error:
                    read_warnings.append(
                        f"{stream.split('/')[0]} read failed: {error}"
                    )
    parsed = parse_streams(streams)
    parsed.warnings = read_warnings + parsed.warnings
    return parsed
