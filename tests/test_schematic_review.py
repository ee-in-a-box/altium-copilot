import pytest


@pytest.fixture()
def fake_project():
    import server.main as main_mod
    from server.parsers.prj_pcb import VariantState, VariantDefinition
    orig_project = main_mod._project
    orig_variant_state = main_mod._variant_state
    orig_netlist = main_mod._altium._netlist
    main_mod._project = {
        "name": "TestBoard",
        "root_dir": "C:/fake",
        "prj_pcb_path": "C:/fake/TestBoard.PrjPcb",
        "sheets": [
            {"name": "Power_Supply", "path": "C:/fake/Power_Supply.SchDoc"},
            {"name": "MCU", "path": "C:/fake/MCU.SchDoc"},
        ],
    }
    main_mod._variant_state = VariantState([VariantDefinition(name="Standard", dnp_refdes=[])])
    main_mod._altium._netlist = {"nets": {}, "pin_to_net": {}, "components": {}}
    yield
    main_mod._project = orig_project
    main_mod._variant_state = orig_variant_state
    main_mod._altium._netlist = orig_netlist


def test_schematic_review_cold_start_guard():
    """Returns a JSON error when no project is loaded."""
    import json
    import server.main as main_mod
    original = main_mod._project
    main_mod._project = None
    try:
        result = json.loads(main_mod.schematic_review())
        assert result["error"] == "no_project"
        assert "detect_altium_project" in result["message"]
    finally:
        main_mod._project = original


def test_schematic_review_includes_project_context(fake_project):
    """Happy path: result contains project name, sheets, and active variant."""
    import server.main as main_mod
    result = main_mod.schematic_review()
    assert "TestBoard" in result
    assert "Power_Supply" in result
    assert "MCU" in result
    assert "Standard" in result


def test_schematic_review_asks_scope(fake_project):
    """Happy path: result asks user to choose a scope."""
    import server.main as main_mod
    result = main_mod.schematic_review()
    assert "Power_Supply" in result  # first sheet offered as example
    assert "2 sheets" in result      # full project option


def test_schematic_review_contains_all_phases(fake_project):
    """Happy path: all three phase headings are present."""
    import server.main as main_mod
    result = main_mod.schematic_review()
    assert "Phase 1" in result
    assert "Phase 2" in result
    assert "Phase 3" in result


