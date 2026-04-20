# tests/test_brainstorm_circuits.py


def test_brainstorm_circuits_no_project_required():
    """Returns a non-empty string even when no project is loaded."""
    import server.main as main_mod
    original = main_mod._project
    main_mod._project = None
    try:
        result = main_mod.brainstorm_circuits()
        assert isinstance(result, str)
        assert len(result) > 0
    finally:
        main_mod._project = original


def test_brainstorm_circuits_contains_all_phases():
    """Prompt includes all six phase headings (0 through 5)."""
    import server.main as main_mod
    result = main_mod.brainstorm_circuits()
    for phase in ["Phase 0", "Phase 1", "Phase 2", "Phase 3", "Phase 4", "Phase 5"]:
        assert phase in result, f"Missing {phase}"


def test_brainstorm_circuits_references_context_tools():
    """Prompt references the tools Claude should use in Phase 0."""
    import server.main as main_mod
    result = main_mod.brainstorm_circuits()
    assert "get_sheet_context" in result
    assert "query_net" in result
    assert "get_component" in result


def test_brainstorm_circuits_references_fit_check_tools():
    """Prompt references search tools for Phase 4 fit check."""
    import server.main as main_mod
    result = main_mod.brainstorm_circuits()
    assert "search_components" in result
    assert "search_nets" in result


def test_brainstorm_circuits_enforces_one_question_at_a_time():
    """Prompt instructs Claude to ask one question at a time."""
    import server.main as main_mod
    result = main_mod.brainstorm_circuits()
    lower = result.lower()
    assert "one question" in lower or "one at a time" in lower


def test_brainstorm_circuits_requires_datasheet_verification():
    """Prompt instructs Claude not to state component specs from memory."""
    import server.main as main_mod
    result = main_mod.brainstorm_circuits()
    lower = result.lower()
    assert "datasheet" in lower
    assert "memory" in lower


def test_server_instructions_includes_brainstorm_trigger():
    """SERVER_INSTRUCTIONS contains the brainstorm_circuits trigger line."""
    import server.main as main_mod
    assert "brainstorm_circuits" in main_mod.SERVER_INSTRUCTIONS
