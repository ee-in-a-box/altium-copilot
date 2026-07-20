import math
import struct

import pytest

from server.parsers.pcb_doc import (
    NO_NET,
    PcbData,
    decode_arcs,
    decode_board,
    decode_components,
    decode_nets,
    decode_pads,
    decode_polygons,
    decode_tracks,
    decode_vias,
    iter_binary_records,
    parse_dim_mil,
    parse_streams,
    read_text_records,
)
from server.parsers.pcb_doc import _build_layer_aliases


def _text_record(props: dict[str, str]) -> bytes:
    body = (
        ("|" + "|".join(f"{k}={v}" for k, v in props.items())).encode("latin-1")
        + b"\x00"
    )
    return struct.pack("<I", len(body)) + body


def test_read_text_records_parses_props():
    data = _text_record({"NAME": "GND"}) + _text_record({"NAME": "3V3", "X": "5"})
    recs = read_text_records(data)
    assert recs == [{"NAME": "GND"}, {"NAME": "3V3", "X": "5"}]


def test_read_text_records_stops_on_truncated_record():
    data = _text_record({"NAME": "GND"}) + struct.pack("<I", 9999) + b"|A=B"
    assert read_text_records(data) == [{"NAME": "GND"}]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("5mil", 5.0),
        ("2.7559mil", 2.7559),
        ("0.127mm", 5.0),
        ("1000", 1000.0),
        (" 1.80000000000000E+0002", 180.0),
    ],
)
def test_parse_dim_mil(raw, expected):
    assert parse_dim_mil(raw) == pytest.approx(expected, abs=1e-3)


def test_parse_dim_mil_invalid_returns_none():
    assert parse_dim_mil("") is None
    assert parse_dim_mil("abc") is None
    assert parse_dim_mil(None) is None


def _bin_record(record_type: int, payload: bytes) -> bytes:
    return bytes([record_type]) + struct.pack("<I", len(payload)) + payload


def _track_payload(
    layer=1,
    net=0,
    component=0xFFFF,
    x1=1000_0000,
    y1=1000_0000,
    x2=1050_0000,
    y2=1000_0000,
    width=6_0000,
) -> bytes:
    payload = bytearray(49)
    payload[0] = layer
    struct.pack_into("<H", payload, 3, net)
    struct.pack_into("<H", payload, 7, component)
    struct.pack_into("<iiiii", payload, 13, x1, y1, x2, y2, width)
    return bytes(payload)


def _via_payload(layer_from=1, layer_to=32) -> bytes:
    payload = bytearray(80)
    struct.pack_into("<H", payload, 3, 5)
    struct.pack_into("<H", payload, 7, 0xFFFF)
    struct.pack_into(
        "<iiii",
        payload,
        13,
        200_0000,
        300_0000,
        20_0000,
        8_0000,
    )
    payload[29], payload[30] = layer_from, layer_to
    return bytes(payload)


def _arc_payload(layer=1, radius=1_0000) -> bytes:
    payload = bytearray(45)
    payload[0] = layer
    struct.pack_into("<H", payload, 3, 2)
    struct.pack_into("<ii", payload, 13, 100_0000, 100_0000)
    struct.pack_into("<i", payload, 21, radius)
    struct.pack_into("<dd", payload, 25, 0.0, 90.0)
    struct.pack_into("<i", payload, 41, 2000)
    return bytes(payload)


def test_iter_binary_records_frames_correctly():
    data = _bin_record(4, b"\x01" * 49) + _bin_record(4, b"\x02" * 49)
    records = list(iter_binary_records(data))
    assert len(records) == 2
    assert records[0] == (4, b"\x01" * 49)


def test_iter_binary_records_stops_on_truncation():
    data = _bin_record(4, b"\x01" * 49) + b"\x04" + struct.pack("<I", 9999)
    assert len(list(iter_binary_records(data))) == 1


def test_decode_tracks():
    data = _bin_record(4, _track_payload(layer=3, net=7, width=6_0000))
    primitives, skipped = decode_tracks(data)
    assert skipped == 0
    track = primitives[0]
    assert (track.kind, track.layer, track.net, track.width) == (
        "track",
        3,
        7,
        6.0,
    )
    assert (track.x1, track.y1, track.x2, track.y2) == (
        1000.0,
        1000.0,
        1050.0,
        1000.0,
    )


def test_decode_tracks_no_net_and_short_payload_skipped():
    good = _bin_record(4, _track_payload(net=NO_NET))
    short = _bin_record(4, b"\x01" * 10)
    primitives, skipped = decode_tracks(good + short)
    assert primitives[0].net is None
    assert skipped == 1


def test_decode_tracks_out_of_range_layer_skipped():
    primitives, skipped = decode_tracks(_bin_record(4, _track_payload(layer=0)))
    assert primitives == []
    assert skipped == 1


def test_decode_tracks_rejects_wrong_type_and_nonpositive_width():
    wrong_type = _bin_record(3, _track_payload())
    negative_width = _bin_record(4, _track_payload(width=-1))
    primitives, skipped = decode_tracks(wrong_type + negative_width)
    assert primitives == []
    assert skipped == 2


def test_decode_vias():
    primitives, skipped = decode_vias(_bin_record(3, _via_payload()))
    via = primitives[0]
    assert (via.kind, via.net, via.layer, via.layer_to) == ("via", 5, 1, 32)
    assert (via.x1, via.y1, via.width) == (200.0, 300.0, 20.0)
    assert via.hole == 8.0
    assert skipped == 0


def test_decode_vias_out_of_range_layer_skipped():
    primitives, skipped = decode_vias(
        _bin_record(3, _via_payload(layer_from=200))
    )
    assert primitives == []
    assert skipped == 1


def test_decode_arcs_explodes_to_segments():
    primitives, skipped = decode_arcs(_bin_record(1, _arc_payload()))
    assert skipped == 0
    assert all(segment.kind == "arc" for segment in primitives)
    assert {segment.source_id for segment in primitives} == {0}
    assert len(primitives) >= 2
    first, last = primitives[0], primitives[-1]
    assert (first.x1, first.y1) == (
        pytest.approx(101.0),
        pytest.approx(100.0),
    )
    assert (last.x2, last.y2) == (
        pytest.approx(100.0),
        pytest.approx(101.0),
    )


def test_decode_arcs_out_of_range_layer_skipped():
    primitives, skipped = decode_arcs(_bin_record(1, _arc_payload(layer=200)))
    assert primitives == []
    assert skipped == 1


def test_decode_arcs_skips_nan_record_without_losing_healthy_records():
    malformed = bytearray(_arc_payload())
    struct.pack_into("<d", malformed, 25, float("nan"))
    data = _bin_record(1, bytes(malformed)) + _bin_record(1, _arc_payload())
    primitives, skipped = decode_arcs(data)
    assert skipped == 1
    assert primitives


def test_decode_arcs_adapts_chords_for_large_radius_length_accuracy():
    primitives, skipped = decode_arcs(
        _bin_record(1, _arc_payload(radius=1000_0000))
    )
    length = sum(
        math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1)
        for segment in primitives
    )
    assert skipped == 0
    assert length == pytest.approx(math.pi * 500.0, abs=0.5)


def _pad_record(
    name="1",
    layer=1,
    net=3,
    component=5,
    x=150_0000,
    y=250_0000,
    sx=2_4000,
    sy=3_5000,
    hole=0,
    rotation=90.0,
    shape=2,
    extra_sub=b"",
) -> bytes:
    name_bytes = name.encode("latin-1")
    name_blob = bytes([len(name_bytes)]) + name_bytes
    main = bytearray(185)
    main[0] = layer
    struct.pack_into("<H", main, 3, net)
    struct.pack_into("<H", main, 7, component)
    struct.pack_into("<ii", main, 13, x, y)
    struct.pack_into("<iiiiiii", main, 21, sx, sy, sx, sy, sx, sy, hole)
    main[49] = shape
    struct.pack_into("<d", main, 52, rotation)
    subrecords = [b"\x00", b"\x00" * 5, b"\x00", bytes(main), extra_sub]
    body = struct.pack("<I", len(name_blob)) + name_blob
    for subrecord in subrecords:
        body += struct.pack("<I", len(subrecord)) + subrecord
    return b"\x02" + body


def test_decode_pads():
    data = _pad_record(name="A7", net=3, component=5, rotation=90.0)
    primitives, skipped = decode_pads(data)
    assert skipped == 0
    pad = primitives[0]
    assert (pad.kind, pad.pad_name, pad.layer, pad.net, pad.component) == (
        "pad",
        "A7",
        1,
        3,
        5,
    )
    assert (pad.x1, pad.y1) == (150.0, 250.0)
    assert (pad.width, pad.height) == (2.4, 3.5)
    assert (pad.shape, pad.rotation) == (2, 90.0)
    assert pad.hole == 0.0


def test_decode_pads_with_extended_subrecord():
    data = _pad_record(extra_sub=b"\x00" * 651) + _pad_record(name="2")
    primitives, skipped = decode_pads(data)
    assert [pad.pad_name for pad in primitives] == ["1", "2"]
    assert skipped == 0


def test_decode_pads_short_main_subrecord_skipped():
    name_blob = b"\x011"
    body = struct.pack("<I", len(name_blob)) + name_blob
    for subrecord in [b"\x00", b"\x00" * 5, b"\x00", b"\x00" * 20, b""]:
        body += struct.pack("<I", len(subrecord)) + subrecord
    primitives, skipped = decode_pads(b"\x02" + body)
    assert primitives == []
    assert skipped == 1


def test_decode_pads_out_of_range_layer_skipped():
    primitives, skipped = decode_pads(_pad_record(layer=200))
    assert primitives == []
    assert skipped == 1


BOARD_PROPS = {
    "ORIGINX": "7283.4648mil",
    "ORIGINY": "7775.5913mil",
    "SHEETX": "1000mil",
    "SHEETY": "1000mil",
    "SHEETWIDTH": "10000mil",
    "SHEETHEIGHT": "8000mil",
    "DISPLAYUNIT": "1",
    "LAYER1NAME": "Top Layer",
    "LAYER2NAME": "L2-GND",
    "LAYER32NAME": "Bottom Layer",
    "LAYER33NAME": "Top Overlay",
    "V9_STACK_LAYER0_NAME": "Top Layer",
    "V9_STACK_LAYER0_LAYERID": "16777217",
    "V9_STACK_LAYER0_COPTHICK": "2.7559mil",
    "V9_STACK_LAYER1_NAME": "Dielectric1",
    "V9_STACK_LAYER1_LAYERID": "17039361",
    "V9_STACK_LAYER1_DIELTYPE": "1",
    "V9_STACK_LAYER1_DIELCONST": "3.800",
    "V9_STACK_LAYER1_DIELHEIGHT": "5mil",
    "V9_STACK_LAYER1_DIELMATERIAL": "Isola FR370HR",
    "V9_STACK_LAYER2_NAME": "L2-GND",
    "V9_STACK_LAYER2_LAYERID": "16777218",
    "V9_STACK_LAYER2_COPTHICK": "2.7559mil",
}


def test_decode_board_stackup_and_origin():
    board = decode_board([BOARD_PROPS])
    assert board.origin_x == pytest.approx(7283.4648)
    assert board.display_unit == "mil"
    top = next(layer for layer in board.layers if layer.name == "Top Layer")
    assert (top.v6_id, top.kind, top.stack_order) == (1, "copper", 0)
    assert top.copper_thick_mil == pytest.approx(2.7559)
    dielectric = next(
        layer for layer in board.layers if layer.name == "Dielectric1"
    )
    assert (
        dielectric.kind,
        dielectric.diel_const,
        dielectric.material,
    ) == ("dielectric", 3.8, "Isola FR370HR")
    assert dielectric.diel_height_mil == pytest.approx(5.0)
    ground = next(layer for layer in board.layers if layer.name == "L2-GND")
    assert (ground.v6_id, ground.stack_order) == (2, 2)
    overlay = next(
        layer for layer in board.layers if layer.name == "Top Overlay"
    )
    assert (overlay.v6_id, overlay.kind, overlay.stack_order) == (
        33,
        "non-stack",
        None,
    )


def test_decode_board_legacy_fallback():
    board = decode_board(
        [{"LAYER1NAME": "Top Layer", "LAYER2NAME": "Bottom Layer"}]
    )
    assert board.stackup_source == "legacy"
    assert [layer.name for layer in board.layers][:2] == [
        "Top Layer",
        "Bottom Layer",
    ]


def test_decode_board_outline_vertices():
    board = decode_board([
        {
            **BOARD_PROPS,
            "VX0": "10mil",
            "VY0": "20mil",
            "VX1": "110mil",
            "VY1": "20mil",
            "VX2": "110mil",
            "VY2": "220mil",
        }
    ])
    assert board.outline_vertices == [
        (10.0, 20.0),
        (110.0, 20.0),
        (110.0, 220.0),
    ]


def test_decode_nets():
    assert decode_nets([{"NAME": "GND"}, {"NAME": "3V3"}]) == ["GND", "3V3"]


def test_decode_components():
    components = decode_components(
        [
            {
                "SOURCEDESIGNATOR": "U3",
                "SOURCEUNIQUEID": "\\TTMAPHZK\\HBSRZYDI\\NWGGFMAY",
                "SOURCEHIERARCHICALPATH": "top_sheet\\Voltage Sense\\Top",
                "X": "12952.756mil",
                "Y": "13425.1969mil",
                "ROTATION": " 1.80000000000000E+0002",
                "LAYER": "TOP",
            },
            {
                "LAYER": "BOTTOM",
            },
        ]
    )
    u3 = components[0]
    assert (u3.index, u3.refdes, u3.side, u3.rotation) == (
        0,
        "U3",
        "top",
        180.0,
    )
    assert u3.source_uid_tail == "NWGGFMAY"
    assert u3.channel_path == "top_sheet\\Voltage Sense\\Top"
    assert u3.x == pytest.approx(12952.756)
    assert (components[1].refdes, components[1].side) == (None, "bottom")


def test_decode_polygons():
    pours, edges = decode_polygons(
        [
            {
                "LAYER": "TOP",
                "NET": "5",
                "HATCHSTYLE": "Solid",
                "VX0": "0mil",
                "VY0": "0mil",
                "VX1": "100mil",
                "VY1": "0mil",
                "VX2": "100mil",
                "VY2": "50mil",
            }
        ],
        layer_name_to_v6={"top layer": 1, "top": 1},
    )
    assert pours[0].net == 5
    assert pours[0].layer == 1
    assert pours[0].vertices == [
        (0.0, 0.0),
        (100.0, 0.0),
        (100.0, 50.0),
    ]
    assert len(edges) == 3
    assert all(
        edge.kind == "track" and edge.pour_id == 0 and edge.width == 0.0
        for edge in edges
    )
    assert (edges[-1].x1, edges[-1].y1, edges[-1].x2, edges[-1].y2) == (
        100.0,
        50.0,
        0.0,
        0.0,
    )


def test_build_layer_aliases_resolves_mid_layer_positional_names():
    # Polygons6 (and other text streams) reference inner copper layers by
    # Altium's fixed positional alias (MID1, MID2, ...), not by LAYERnNAME —
    # regression test for a board where an L2-GND pour's layer failed to
    # resolve because only "top"/"bottom" fallbacks existed.
    board = decode_board([BOARD_PROPS])
    aliases = _build_layer_aliases(board)
    assert aliases["mid1"] == 2
    assert aliases["l2-gnd"] == 2
    assert aliases["mid1"] == aliases["l2-gnd"]
    assert aliases["mid30"] == 31


def test_decode_polygons_resolves_inner_layer_via_mid_alias():
    board = decode_board([BOARD_PROPS])
    aliases = _build_layer_aliases(board)
    pours, edges = decode_polygons(
        [
            {
                "LAYER": "MID1",
                "NET": "0",
                "VX0": "0mil", "VY0": "0mil",
                "VX1": "10mil", "VY1": "0mil",
                "VX2": "10mil", "VY2": "10mil",
            }
        ],
        layer_name_to_v6=aliases,
    )
    assert pours[0].layer == 2
    assert len(edges) == 3  # proximity edges must be built, not silently dropped


def _stream_text(records: list[dict[str, str]]) -> bytes:
    return b"".join(_text_record(record) for record in records)


def test_parse_streams_assembles_pcbdata():
    streams = {
        "Board6/Data": _stream_text([BOARD_PROPS]),
        "Nets6/Data": _stream_text([{"NAME": "GND"}, {"NAME": "CLK"}]),
        "Components6/Data": _stream_text(
            [
                {
                    "SOURCEDESIGNATOR": "R1",
                    "X": "0mil",
                    "Y": "0mil",
                    "LAYER": "TOP",
                }
            ]
        ),
        "Tracks6/Data": _bin_record(
            4,
            _track_payload(layer=1, net=1, component=0),
        ),
        "Vias6/Data": b"",
        "Arcs6/Data": b"",
        "Pads6/Data": _pad_record(name="1", layer=1, net=0, component=0),
        "Polygons6/Data": _stream_text(
            [
                {
                    "LAYER": "TOP",
                    "NET": "0",
                    "VX0": "0mil",
                    "VY0": "0mil",
                    "VX1": "10mil",
                    "VY1": "0mil",
                    "VX2": "10mil",
                    "VY2": "10mil",
                }
            ]
        ),
    }
    pcb = parse_streams(streams)
    assert isinstance(pcb, PcbData)
    assert pcb.nets == ["GND", "CLK"]
    assert pcb.components[0].refdes == "R1"
    assert {primitive.kind for primitive in pcb.primitives} == {
        "track",
        "pad",
    }
    assert len(pcb.pours) == 1
    assert pcb.skipped_records == {}
    assert pcb.warnings == []


def test_parse_streams_missing_stream_warns_but_continues():
    streams = {
        "Board6/Data": _stream_text([BOARD_PROPS]),
        "Nets6/Data": _stream_text([{"NAME": "GND"}]),
    }
    pcb = parse_streams(streams)
    assert pcb.nets == ["GND"]
    assert any("Tracks6" in warning for warning in pcb.warnings)


def test_parse_streams_isolates_invalid_board_text_values():
    streams = {
        "Board6/Data": _stream_text([
            {
                **BOARD_PROPS,
                "V9_STACK_LAYER1_DIELCONST": "not-a-number",
            }
        ]),
        "Nets6/Data": _stream_text([{"NAME": "GND"}]),
        "Components6/Data": _stream_text([]),
    }
    pcb = parse_streams(streams)
    assert pcb.nets == ["GND"]
    assert any(
        "Board6 parse failed" in warning
        for warning in pcb.warnings
    )


def test_parse_streams_drops_out_of_range_net_references():
    streams = {
        "Board6/Data": _stream_text([BOARD_PROPS]),
        "Nets6/Data": _stream_text([{"NAME": "GND"}]),
        "Components6/Data": b"",
        "Tracks6/Data": _bin_record(4, _track_payload(net=9)),
        "Vias6/Data": b"",
        "Arcs6/Data": b"",
        "Pads6/Data": b"",
        "Polygons6/Data": b"",
    }
    pcb = parse_streams(streams)
    assert pcb.primitives == []
    assert pcb.skipped_records["net_range"] == 1
