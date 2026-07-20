from copy import deepcopy

import pytest

from server.parsers.pcb_doc import (
    BoardInfo,
    PcbComponent,
    PcbData,
    PcbLayer,
    PolygonPour,
    Primitive,
)
from server.services.pcb_index import PcbIndex


def _layer(v6, name, order, kind="copper", **kwargs):
    return PcbLayer(
        v6_id=v6,
        name=name,
        kind=kind,
        stack_order=order,
        **kwargs,
    )


def _board():
    return BoardInfo(
        origin_x=0.0,
        origin_y=0.0,
        sheet_x=0.0,
        sheet_y=0.0,
        sheet_width=1000.0,
        sheet_height=1000.0,
        display_unit="mil",
        stackup_source="v9",
        layers=[
            _layer(1, "Top Layer", 0),
            _layer(
                None,
                "Dielectric1",
                1,
                kind="dielectric",
                diel_height_mil=5.0,
            ),
            _layer(2, "L2-GND", 2),
            _layer(3, "L3-SIG", 4),
            _layer(32, "Bottom Layer", 6),
        ],
    )


def _track(net, layer, x1, y1, x2, y2, width=6.0, component=None):
    return Primitive(
        kind="track",
        layer=layer,
        net=net,
        component=component,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        width=width,
    )


def _pad(
    net,
    component,
    x,
    y,
    name="1",
    layer=1,
    width=10.0,
    height=None,
    shape=1,
    rotation=0.0,
):
    return Primitive(
        kind="pad",
        layer=layer,
        net=net,
        component=component,
        x1=x,
        y1=y,
        x2=x,
        y2=y,
        width=width,
        height=height if height is not None else width,
        shape=shape,
        rotation=rotation,
        pad_name=name,
    )


@pytest.fixture
def pcb_data():
    return PcbData(
        board=_board(),
        nets=["GND", "CLK_A", "CLK_B"],
        components=[
            PcbComponent(
                index=0,
                refdes="U3",
                source_uid_tail="NWGG",
                channel_path="top\\VS\\Top",
                x=100.0,
                y=100.0,
                rotation=0.0,
                side="top",
            ),
            PcbComponent(
                index=1,
                refdes="U3",
                source_uid_tail="NWGG",
                channel_path="top\\VS\\Bottom",
                x=500.0,
                y=100.0,
                rotation=0.0,
                side="top",
            ),
            PcbComponent(
                index=2,
                refdes="R1",
                source_uid_tail="RRRR",
                channel_path=None,
                x=300.0,
                y=300.0,
                rotation=90.0,
                side="bottom",
            ),
        ],
        primitives=[
            _pad(net=1, component=0, x=100.0, y=100.0),
            _pad(net=0, component=0, x=100.0, y=110.0, name="2"),
            _pad(net=2, component=1, x=500.0, y=100.0),
            _pad(net=0, component=1, x=500.0, y=110.0, name="2"),
            _pad(net=0, component=2, x=300.0, y=300.0),
            _track(net=1, layer=1, x1=100, y1=100, x2=200, y2=100),
            _track(net=1, layer=3, x1=200, y1=100, x2=300, y2=100),
            _track(net=2, layer=1, x1=100, y1=103, x2=200, y2=103),
            Primitive(
                kind="via",
                layer=1,
                layer_to=32,
                net=1,
                component=None,
                x1=200,
                y1=100,
                x2=200,
                y2=100,
                width=20.0,
                hole=8.0,
            ),
        ],
        pours=[
            PolygonPour(
                pour_id=0,
                net=0,
                layer=2,
                hatch_style="Solid",
                vertices=[
                    (0, 0),
                    (1000, 0),
                    (1000, 1000),
                    (0, 1000),
                ],
            )
        ],
        layer_name_to_v6={
            "top layer": 1,
            "l2-gnd": 2,
            "l3-sig": 3,
            "bottom layer": 32,
            "top": 1,
            "bottom": 32,
        },
    )


NETLIST = {
    "components": {
        "U3A": {
            "unique_id": "NWGG",
            "pins": {
                "1": {"name": "CLK", "net": "CLK_A"},
                "2": {"name": "GND", "net": "GND"},
            },
        },
        "U3B": {
            "unique_id": "NWGG",
            "pins": {
                "1": {"name": "CLK", "net": "CLK_B"},
                "2": {"name": "GND", "net": "GND"},
            },
        },
        "R1": {
            "unique_id": "RRRR",
            "pins": {"1": {"name": "~", "net": "GND"}},
        },
    },
}


def test_build_and_counts(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    counts = index.counts()
    assert counts["tracks"] == 3
    assert counts["arcs"] == 0
    assert counts["vias"] == 1
    assert counts["pads"] == 5
    assert counts["pours"] == 1
    assert counts["nets"] == 3
    assert counts["components"] == 3


def test_rtree_shadow_matches_primitive_rows_when_available(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    assert isinstance(index._has_rtree, bool)
    if index._has_rtree:
        primitive_count = index.db.execute(
            "SELECT COUNT(*) FROM prims"
        ).fetchone()[0]
        shadow_count = index.db.execute(
            "SELECT COUNT(*) FROM prims_rtree"
        ).fetchone()[0]
        assert shadow_count == primitive_count


def test_refdes_resolution_direct_and_signature(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    rows = index.find_components("U3")
    assert {row["sch_refdes"] for row in rows} == {"U3A", "U3B"}
    by_schematic = {row["sch_refdes"]: row for row in rows}
    assert by_schematic["U3A"]["channel_path"] == "top\\VS\\Top"
    assert by_schematic["U3B"]["channel_path"] == "top\\VS\\Bottom"
    assert index.find_components("R1")[0]["sch_refdes"] == "R1"
    assert (
        index.find_components("U3B")[0]["channel_path"]
        == "top\\VS\\Bottom"
    )


def test_refdes_resolution_unmatched_count(pcb_data):
    index = PcbIndex(pcb_data, netlist=None)
    assert index.unmatched_components() == 3
    resolved_index = PcbIndex(pcb_data, NETLIST)
    assert resolved_index.unmatched_components() == 0


def test_refdes_resolution_rejects_partial_signature_match(pcb_data):
    data = deepcopy(pcb_data)
    data.components.append(
        PcbComponent(
            index=3,
            refdes="U9",
            source_uid_tail="PARTIAL",
            channel_path="top\\Partial",
            x=700.0,
            y=100.0,
            rotation=0.0,
            side="top",
        )
    )
    data.primitives.extend([
        _pad(net=1, component=3, x=700.0, y=100.0, name="1"),
        _pad(net=0, component=3, x=710.0, y=100.0, name="2"),
    ])
    netlist = deepcopy(NETLIST)
    netlist["components"].update({
        "U9A": {
            "unique_id": "PARTIAL",
            "pins": {
                "1": {"net": "CLK_A"},
                "2": {"net": "CLK_B"},
            },
        },
        "U9B": {
            "unique_id": "PARTIAL",
            "pins": {
                "1": {"net": "CLK_B"},
                "2": {"net": "CLK_B"},
            },
        },
    })
    index = PcbIndex(data, netlist)
    assert index.find_components("U9")[0]["sch_refdes"] is None


def test_layer_resolution(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    index.pcb.layer_name_to_v6["mid30"] = 31
    assert index.resolve_layer("L3-SIG") == 3
    assert index.resolve_layer("l3-sig") == 3
    assert index.resolve_layer("nope") is None
    assert index.resolve_layer("MID30") is None


def test_net_summary(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    summary = index.net_summary("CLK_A")
    assert summary["net"] == "CLK_A"
    layers = {layer["layer"]: layer for layer in summary["layers"]}
    assert layers["Top Layer"]["segment_count"] == 1
    assert layers["Top Layer"]["length_mil"] == pytest.approx(100.0)
    assert layers["Top Layer"]["bbox_mil"] == {
        "minx_mil": pytest.approx(97.0),
        "miny_mil": pytest.approx(97.0),
        "maxx_mil": pytest.approx(203.0),
        "maxy_mil": pytest.approx(103.0),
    }
    assert layers["L3-SIG"]["length_mil"] == pytest.approx(100.0)
    assert summary["via_count"] == 1
    assert summary["vias"][0]["span"] == "Top Layer -> Bottom Layer"
    assert summary["pads"][0]["refdes"] == "U3"
    assert summary["pads"][0]["sch_refdes"] == "U3A"
    assert summary["bbox_mil"] == {
        "minx_mil": pytest.approx(95.0),
        "miny_mil": pytest.approx(90.0),
        "maxx_mil": pytest.approx(303.0),
        "maxy_mil": pytest.approx(110.0),
    }


def test_net_summary_unknown_net(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    assert index.net_summary("NOPE") is None


def test_net_summary_caps_detail_collections_and_reports_totals(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    index.MAX_NET_DETAIL_RESULTS = 0
    summary = index.net_summary("CLK_A")
    assert summary["via_count"] == 1
    assert summary["vias"] == []
    assert summary["vias_has_more"] is True
    assert summary["pad_count"] == 1
    assert summary["pads"] == []
    assert summary["pads_has_more"] is True


def test_net_neighbors_same_layer(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    result = index.net_neighbors("CLK_A", distance=10.0)
    names = [neighbor["net"] for neighbor in result["neighbors"]]
    assert "CLK_B" in names
    clock_b = next(
        neighbor
        for neighbor in result["neighbors"]
        if neighbor["net"] == "CLK_B"
    )
    assert clock_b["layer"] == "Top Layer"
    assert clock_b["min_edge_distance_mil"] == 0.0
    assert clock_b["parallel_run_mil"] == pytest.approx(100.0)


def test_net_neighbors_excludes_far_nets(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    result = index.net_neighbors("CLK_A", distance=0.5, layer=3)
    assert result["neighbors"] == []


def test_net_neighbors_broadside(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    result = index.net_neighbors("CLK_A", distance=5.0)
    assert "GND" in [entry["net"] for entry in result["broadside"]]


def test_broadside_uses_per_layer_target_extents(pcb_data):
    data = deepcopy(pcb_data)
    data.nets.extend(["TARGET_GAP", "MID_GAP"])
    data.primitives.extend([
        _track(net=3, layer=1, x1=0, y1=500, x2=100, y2=500),
        _track(net=3, layer=3, x1=900, y1=500, x2=1000, y2=500),
        _track(net=4, layer=2, x1=450, y1=500, x2=550, y2=500),
    ])
    index = PcbIndex(data, NETLIST)
    result = index.net_neighbors("TARGET_GAP", distance=5.0)
    assert "MID_GAP" not in [
        entry["net"] for entry in result["broadside"]
    ]


def test_inner_layer_queries_include_through_via_candidates(pcb_data):
    data = deepcopy(pcb_data)
    data.nets.append("VIA_NET")
    data.primitives.append(
        Primitive(
            kind="via",
            layer=1,
            layer_to=32,
            net=3,
            component=None,
            x1=250.0,
            y1=105.0,
            x2=250.0,
            y2=105.0,
            width=10.0,
            hole=5.0,
        )
    )
    index = PcbIndex(data, NETLIST)

    neighbors = index.net_neighbors("CLK_A", distance=1.0, layer=3)
    assert any(
        neighbor["net"] == "VIA_NET"
        for neighbor in neighbors["neighbors"]
    )

    reverse = index.net_neighbors("VIA_NET", distance=1.0, layer=3)
    assert any(
        neighbor["net"] == "CLK_A"
        for neighbor in reverse["neighbors"]
    )

    region = index.region_query(250.0, 105.0, radius=0.0, layer=3)
    assert any(net["net"] == "VIA_NET" for net in region["nets"])
    via_net = next(net for net in region["nets"] if net["net"] == "VIA_NET")
    assert via_net["layers"] == ["L3-SIG"]


def test_inner_layer_region_includes_multilayer_pad(pcb_data):
    data = deepcopy(pcb_data)
    data.nets.append("PTH_NET")
    data.board.layers.append(
        _layer(74, "Multi-Layer", None, kind="non-stack")
    )
    data.primitives.append(
        _pad(
            net=3,
            component=None,
            x=250.0,
            y=105.0,
            layer=74,
            width=10.0,
        )
    )
    index = PcbIndex(data, NETLIST)
    region = index.region_query(250.0, 105.0, radius=0.0, layer=3)
    assert any(net["net"] == "PTH_NET" for net in region["nets"])


def test_net_neighbors_caps_broadside(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    index.MAX_NEIGHBORS = 0
    result = index.net_neighbors("CLK_A", distance=5.0)
    assert result["broadside"] == []
    assert result["broadside_count"] > 0
    assert result["broadside_has_more"] is True


def test_net_neighbors_unknown_net(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    assert index.net_neighbors("NOPE", distance=10.0) is None


def test_region_query(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    result = index.region_query(150.0, 100.0, radius=60.0)
    net_names = [net["net"] for net in result["nets"]]
    assert "CLK_A" in net_names
    assert "CLK_B" in net_names
    clock_a = next(net for net in result["nets"] if net["net"] == "CLK_A")
    assert clock_a["min_distance_mil"] == 0.0
    assert "U3" in [
        component["refdes"] for component in result["components"]
    ]
    ground_pour = next(
        pour for pour in result["pours"] if pour["net"] == "GND"
    )
    assert ground_pour["inside_pour"] is True


def test_region_query_layer_filter(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    result = index.region_query(250.0, 100.0, radius=10.0, layer=3)
    assert [net["net"] for net in result["nets"]] == ["CLK_A"]


def test_region_query_excludes_pour_when_only_bbox_is_near(pcb_data):
    data = deepcopy(pcb_data)
    data.pours = [
        PolygonPour(
            pour_id=0,
            net=0,
            layer=2,
            hatch_style="Solid",
            vertices=[(0, 0), (100, 0), (0, 100)],
        )
    ]
    index = PcbIndex(data, NETLIST)
    result = index.region_query(90.0, 90.0, radius=5.0, layer=2)
    assert result["pours"] == []


def test_component_without_coordinates_does_not_appear_at_origin(pcb_data):
    data = deepcopy(pcb_data)
    data.components.append(
        PcbComponent(
            index=3,
            refdes=None,
            source_uid_tail=None,
            channel_path=None,
            x=None,
            y=None,
            rotation=None,
            side="top",
        )
    )
    index = PcbIndex(data, NETLIST)
    result = index.region_query(0.0, 0.0, radius=1.0)
    assert result["components"] == []


def test_rectangular_pad_uses_rotated_shape_not_max_diameter(pcb_data):
    data = deepcopy(pcb_data)
    data.nets.extend(["RECT_PAD", "FAR_TRACK"])
    data.components.append(
        PcbComponent(
            index=3,
            refdes="J1",
            source_uid_tail=None,
            channel_path=None,
            x=0.0,
            y=0.0,
            rotation=0.0,
            side="top",
        )
    )
    data.primitives.extend([
        _pad(
            net=3,
            component=3,
            x=0.0,
            y=0.0,
            width=100.0,
            height=10.0,
            shape=2,
        ),
        _track(
            net=4,
            layer=1,
            x1=-10.0,
            y1=40.0,
            x2=10.0,
            y2=40.0,
            width=2.0,
        ),
    ])
    index = PcbIndex(data, NETLIST)
    component = index.find_components("J1")[0]
    assert component["minx"] == pytest.approx(-50.0)
    assert component["maxx"] == pytest.approx(50.0)
    assert component["miny"] == pytest.approx(-5.0)
    assert component["maxy"] == pytest.approx(5.0)
    neighbors = index.net_neighbors("RECT_PAD", distance=10.0)
    assert "FAR_TRACK" not in [
        neighbor["net"] for neighbor in neighbors["neighbors"]
    ]
    region = index.region_query(0.0, 40.0, radius=10.0)
    assert "RECT_PAD" not in [net["net"] for net in region["nets"]]


def test_region_query_caps_pours(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    index.MAX_REGION_RESULTS = 0
    result = index.region_query(150.0, 100.0, radius=60.0)
    assert result["nets"] == []
    assert result["components"] == []
    assert result["pours"] == []
    assert result["net_count"] > 0
    assert result["component_count"] > 0
    assert result["pour_count"] > 0
    assert result["nets_has_more"] is True
    assert result["components_has_more"] is True
    assert result["pours_has_more"] is True


def test_component_detail(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    details = index.component_detail("U3B")
    assert len(details) == 1
    instance = details[0]
    assert (instance["refdes"], instance["sch_refdes"]) == ("U3", "U3B")
    assert instance["channel_path"] == "top\\VS\\Bottom"
    assert instance["x_mil"] == 500.0
    assert {pin["pin"] for pin in instance["pins"]} == {"1", "2"}
    pin_1 = next(pin for pin in instance["pins"] if pin["pin"] == "1")
    assert pin_1["net"] == "CLK_B"
    assert "R1" in [
        component["refdes"]
        for component in instance["nearest_components"]
    ]


def test_component_detail_ambiguous_returns_all(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    assert len(index.component_detail("U3")) == 2


def test_component_detail_not_found(pcb_data):
    index = PcbIndex(pcb_data, NETLIST)
    assert index.component_detail("U99") == []
