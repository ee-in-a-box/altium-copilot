import json
from copy import deepcopy
from pathlib import Path

import pytest

import server.main as main_mod
from server.main import PcbSession
from server.parsers.pcb_doc import Primitive
from server.parsers.prj_pcb import VariantDefinition, VariantState
from server.services.pcb_index import PcbIndex
from tests.test_pcb_index import NETLIST, pcb_data  # noqa: F401


def test_pcb_session_no_pcb_doc():
    session = PcbSession()
    index, error = session.get(
        {"pcb_doc_paths": [], "name": "Demo"},
        netlist={},
    )
    assert index is None
    assert error["error"] == "no_pcb_document"


def test_pcb_session_missing_file(tmp_path: Path):
    session = PcbSession()
    index, error = session.get(
        {
            "pcb_doc_paths": [str(tmp_path / "gone.PcbDoc")],
            "name": "Demo",
        },
        netlist={},
    )
    assert index is None
    assert error["error"] == "pcb_file_missing"


def test_pcb_session_caches_by_mtime(tmp_path: Path, monkeypatch):
    pcb_file = tmp_path / "Board.PcbDoc"
    pcb_file.write_bytes(b"fake")
    calls = []

    def fake_load(path, netlist):
        calls.append((path, netlist))
        return object()

    session = PcbSession()
    monkeypatch.setattr(session, "_load", fake_load)
    project = {
        "pcb_doc_paths": [str(pcb_file)],
        "name": "Demo",
    }
    netlist = {}
    first, first_error = session.get(project, netlist=netlist)
    second, second_error = session.get(project, netlist=netlist)
    assert first_error is None
    assert second_error is None
    assert first is second
    assert len(calls) == 1

    import os

    os.utime(pcb_file, (0, 9_999_999_999))
    third, third_error = session.get(project, netlist=netlist)
    assert third_error is None
    assert third is not None
    assert len(calls) == 2


def test_pcb_session_reloads_when_netlist_mapping_changes(
    tmp_path: Path,
    monkeypatch,
):
    pcb_file = tmp_path / "Board.PcbDoc"
    pcb_file.write_bytes(b"fake")
    loads = []

    def fake_load(path, netlist):
        loads.append(netlist)
        return {"mapped_from": netlist}

    session = PcbSession()
    monkeypatch.setattr(session, "_load", fake_load)
    project = {
        "pcb_doc_paths": [str(pcb_file)],
        "name": "Demo",
    }

    first, first_error = session.get(project, netlist={"revision": 1})
    second, second_error = session.get(project, netlist={"revision": 2})

    assert first_error is None
    assert second_error is None
    assert first["mapped_from"] == {"revision": 1}
    assert second["mapped_from"] == {"revision": 2}
    assert len(loads) == 2


def test_pcb_session_parse_failure(tmp_path: Path, monkeypatch):
    pcb_file = tmp_path / "Board.PcbDoc"
    pcb_file.write_bytes(b"fake")
    session = PcbSession()

    def fail_load(path, netlist):
        raise ValueError(f"not an OLE file: {path}")

    monkeypatch.setattr(session, "_load", fail_load)
    index, error = session.get(
        {
            "pcb_doc_paths": [str(pcb_file)],
            "name": "Demo",
        },
        netlist={},
    )
    assert index is None
    assert error["error"] == "pcb_parse_failed"
    assert "not an OLE file" in error["message"]


@pytest.fixture
def loaded_pcb(pcb_data, monkeypatch, tmp_path: Path):
    pcb_file = tmp_path / "Board.PcbDoc"
    pcb_file.write_bytes(b"fake")
    index = PcbIndex(pcb_data, NETLIST)
    index.pcb.board.origin_x = 100.0
    index.pcb.board.origin_y = 200.0
    monkeypatch.setattr(
        main_mod,
        "_project",
        {
            "name": "Demo",
            "root_dir": str(tmp_path),
            "prj_pcb_path": "x",
            "sheets": [],
            "pcb_doc_paths": [str(pcb_file)],
        },
    )
    monkeypatch.setattr(main_mod._altium, "_netlist", NETLIST)
    monkeypatch.setattr(
        main_mod,
        "_variant_state",
        VariantState([VariantDefinition(name="Default")]),
    )
    monkeypatch.setattr(main_mod._pcb_session, "_load", lambda path, netlist: index)
    main_mod._pcb_session._index = None
    return index


def test_get_net_pcb(loaded_pcb):
    result = json.loads(main_mod.get_net_pcb("clk_a"))
    assert result["net"] == "CLK_A"
    assert result["via_count"] == 1


def test_get_net_pcb_pattern_discovery_is_compact(loaded_pcb):
    result = json.loads(main_mod.get_net_pcb("CLK"))
    assert result["match_count"] == 2
    assert "hint" in result
    assert all("pads" not in summary for summary in result["nets"])


def test_get_net_pcb_exact_name_takes_precedence_over_regex(
    loaded_pcb,
    pcb_data,
    monkeypatch,
):
    data = deepcopy(pcb_data)
    data.nets.append("CLK_AUX")
    data.primitives.append(
        Primitive(
            kind="track",
            layer=1,
            net=3,
            component=None,
            x1=0.0,
            y1=0.0,
            x2=10.0,
            y2=0.0,
            width=1.0,
        )
    )
    exact_index = PcbIndex(data, NETLIST)
    monkeypatch.setattr(
        main_mod._pcb_session,
        "_load",
        lambda path, netlist: exact_index,
    )
    main_mod._pcb_session._index = None

    result = json.loads(main_mod.get_net_pcb("CLK_A"))

    assert result["net"] == "CLK_A"
    assert "match_count" not in result


def test_get_net_pcb_warns_when_returning_polygon_outlines(loaded_pcb):
    result = json.loads(main_mod.get_net_pcb("GND"))

    assert result["pour_count"] > 0
    assert "repour" in result["geometry_note"].lower()
    assert "nominal polygon outlines" in result["geometry_note"]


def test_get_net_pcb_not_found(loaded_pcb):
    result = json.loads(main_mod.get_net_pcb("XYZZY"))
    assert result["error"] == "net_not_found"


def test_get_net_neighbors_tool(loaded_pcb):
    result = json.loads(
        main_mod.get_net_neighbors("CLK_A", distance=10.0)
    )
    assert any(
        neighbor["net"] == "CLK_B"
        for neighbor in result["neighbors"]
    )
    assert "repour" in result["geometry_note"].lower()


def test_get_net_neighbors_bad_layer(loaded_pcb):
    result = json.loads(
        main_mod.get_net_neighbors(
            "CLK_A",
            distance=5.0,
            layer="Nope",
        )
    )
    assert result["error"] == "layer_not_found"
    assert "Top Layer" in result["available_layers"]


def test_query_pcb_region_tool(loaded_pcb):
    result = json.loads(
        main_mod.query_pcb_region(150.0, 100.0, radius=20.0)
    )
    assert any(net["net"] == "CLK_A" for net in result["nets"])
    assert "nominal polygon outlines" in result["geometry_note"]


def test_get_component_placement_tool(loaded_pcb):
    result = json.loads(main_mod.get_component_placement("U3B"))
    assert result["instances"][0]["sch_refdes"] == "U3B"


def test_get_component_placement_annotates_dnp_instances(loaded_pcb):
    main_mod._variant_state = VariantState(
        [VariantDefinition(name="Prod", dnp_refdes=["U3B"])]
    )

    result = json.loads(main_mod.get_component_placement("U3B"))

    assert result["instances"][0]["dnp"] is True


def test_query_pcb_region_annotates_dnp_components(loaded_pcb):
    main_mod._variant_state = VariantState(
        [VariantDefinition(name="Prod", dnp_refdes=["U3B"])]
    )

    result = json.loads(
        main_mod.query_pcb_region(500.0, 100.0, radius=1.0)
    )

    component = next(
        item
        for item in result["components"]
        if item["sch_refdes"] == "U3B"
    )
    assert component["dnp"] is True


def test_get_net_pcb_annotates_dnp_pad_endpoints(loaded_pcb):
    main_mod._variant_state = VariantState(
        [VariantDefinition(name="Prod", dnp_refdes=["U3B"])]
    )

    result = json.loads(main_mod.get_net_pcb("CLK_B"))

    pad = next(
        item for item in result["pads"] if item["sch_refdes"] == "U3B"
    )
    assert pad["dnp"] is True


def test_get_component_placement_not_found_suggests_regex_matches(
    loaded_pcb,
):
    result = json.loads(main_mod.get_component_placement("U[0-9]"))
    assert result["error"] == "component_not_found"
    assert result["suggestions"] == ["U3"]


def test_units_mm_conversion(loaded_pcb):
    result = json.loads(main_mod.get_net_pcb("CLK_A", units="mm"))
    top_layer = result["layers"][0]
    assert "length_mm" in top_layer
    assert top_layer["length_mm"] == pytest.approx(100 * 0.0254)


def test_mm_units_apply_to_neighbor_distance_input(loaded_pcb):
    result = json.loads(
        main_mod.get_net_neighbors(
            "CLK_A",
            distance=0.254,
            units="mm",
        )
    )
    assert result["distance_mm"] == pytest.approx(0.254)
    assert any(
        neighbor["net"] == "CLK_B"
        for neighbor in result["neighbors"]
    )


def test_mm_units_apply_to_region_coordinate_inputs(loaded_pcb):
    result = json.loads(
        main_mod.query_pcb_region(
            x=3.81,
            y=2.54,
            radius=0.508,
            units="mm",
        )
    )
    assert result["x_mm"] == pytest.approx(3.81)
    assert result["radius_mm"] == pytest.approx(0.508)
    assert any(net["net"] == "CLK_A" for net in result["nets"])


@pytest.mark.parametrize("tool_call", [
    lambda: main_mod.get_board_info(units="inch"),
    lambda: main_mod.get_net_pcb("CLK_A", units="inch"),
    lambda: main_mod.get_net_neighbors("CLK_A", units="inch"),
    lambda: main_mod.query_pcb_region(0, 0, units="inch"),
    lambda: main_mod.get_component_placement("U3", units="inch"),
])
def test_pcb_tools_reject_invalid_units(loaded_pcb, tool_call):
    result = json.loads(tool_call())
    assert result["error"] == "invalid_units"


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_neighbor_distance_must_be_finite_and_nonnegative(
    loaded_pcb,
    value,
):
    result = json.loads(
        main_mod.get_net_neighbors("CLK_A", distance=value)
    )
    assert result["error"] == "invalid_distance"


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_region_radius_must_be_finite_and_nonnegative(
    loaded_pcb,
    value,
):
    result = json.loads(
        main_mod.query_pcb_region(0, 0, radius=value)
    )
    assert result["error"] == "invalid_radius"


def test_board_origin_values_convert_to_mm(loaded_pcb):
    result = json.loads(main_mod.get_board_info(units="mm"))
    assert result["origin_mm"] == {
        "x_mm": pytest.approx(2.54),
        "y_mm": pytest.approx(5.08),
    }


def test_board_info_discloses_multiple_pcbdocs(loaded_pcb):
    main_mod._project["pcb_doc_paths"].append("Other.PcbDoc")
    result = json.loads(main_mod.get_board_info())
    assert "Project lists 2 PcbDocs" in result["note"]
    assert "Other.PcbDoc" in result["note"]


def test_board_info_prefers_board_outline_extents(loaded_pcb):
    loaded_pcb.pcb.board.outline_vertices = [
        (10.0, 20.0),
        (110.0, 20.0),
        (110.0, 220.0),
    ]
    result = json.loads(main_mod.get_board_info(units="mil"))
    assert result["extents_source"] == "board_outline"
    assert result["board_extents_mil"] == {
        "minx_mil": 10.0,
        "miny_mil": 20.0,
        "maxx_mil": 110.0,
        "maxy_mil": 220.0,
    }
    assert any(
        "repour" in note.lower()
        for note in result["analysis_notes"]
    )


def test_server_instructions_include_pcb_workflow():
    assert "## PCB / Layout Questions" in main_mod.SERVER_INSTRUCTIONS
    assert "Call get_board_info first" in main_mod.SERVER_INSTRUCTIONS
    assert "geometric facts" in main_mod.SERVER_INSTRUCTIONS
    assert "repour" in main_mod.SERVER_INSTRUCTIONS.lower()
