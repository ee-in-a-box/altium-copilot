import pytest
from pathlib import Path
from server.parsers.prj_pcb import parse_prj_pcb, VariantState, VariantDefinition

FIXTURES = Path(__file__).parent / "fixtures"


def test_sheet_paths_are_absolute():
    result = parse_prj_pcb(str(FIXTURES / "test.prjpcb"))
    assert all(Path(p).is_absolute() for p in result.sheet_paths)


def test_sheet_list_contains_known_sheets():
    result = parse_prj_pcb(str(FIXTURES / "test.prjpcb"))
    names = [Path(p).name for p in result.sheet_paths]
    assert "sheet1.SchDoc" in names
    assert "sheet2.SchDoc" in names
    assert "top_sheet.SchDoc" in names


def test_sheet_list_excludes_non_schdoc():
    result = parse_prj_pcb(str(FIXTURES / "test.prjpcb"))
    names = [Path(p).name for p in result.sheet_paths]
    # .Harness and .OutJob files must not appear
    assert not any(n.endswith(".Harness") for n in names)
    assert not any(n.endswith(".OutJob") for n in names)


def test_format_a_variant_parsed():
    # test.prjpcb has one ProjectVariant1 with DNP: R81, R80, R189, R188
    result = parse_prj_pcb(str(FIXTURES / "test.prjpcb"))
    assert len(result.variants) == 1
    variant = result.variants[0]
    assert "R81" in variant.dnp_refdes
    assert "R80" in variant.dnp_refdes
    assert "R189" in variant.dnp_refdes
    assert "R188" in variant.dnp_refdes


def test_format_a_alternate_part_not_dnp():
    # Kind=2 = alternate part swap, must not appear in dnp_refdes
    content = """\
[ProjectVariant1]
Description=Test
Variation1=Designator=C1|Kind=2|AlternatePart=ALT_PART
Variation2=Designator=R1|Kind=1|AlternatePart=
"""
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.PrjPcb', delete=False, encoding='utf-8') as f:
        f.write(content)
        tmp = f.name
    try:
        result = parse_prj_pcb(tmp)
        variant = result.variants[0]
        assert "R1" in variant.dnp_refdes
        assert "C1" not in variant.dnp_refdes
    finally:
        os.unlink(tmp)


def test_no_variants_returns_default():
    content = "[Design]\nVersion=1.0\n[Document1]\nDocumentPath=Sheet1.SchDoc\n"
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.PrjPcb', delete=False, encoding='utf-8') as f:
        f.write(content)
        tmp = f.name
    try:
        result = parse_prj_pcb(tmp)
        assert len(result.variants) == 1
        assert result.variants[0].name == "Default"
        assert result.variants[0].dnp_refdes == []
    finally:
        os.unlink(tmp)


def test_variant_state_is_dnp():
    result = parse_prj_pcb(str(FIXTURES / "test.prjpcb"))
    state = VariantState(result.variants)
    assert state.is_dnp("R81")
    assert state.is_dnp("R80")
    assert state.is_dnp("R189")
    assert state.is_dnp("R188")
    assert not state.is_dnp("C1")


def test_variant_state_set_variant():
    variants = [
        VariantDefinition(name="Default", dnp_refdes=[]),
        VariantDefinition(name="Production", dnp_refdes=["C45"]),
    ]
    state = VariantState(variants)
    assert not state.is_dnp("C45")
    state.set_variant("Production")
    assert state.is_dnp("C45")


def test_variant_state_set_variant_case_insensitive():
    variants = [VariantDefinition(name="Production", dnp_refdes=["R1"])]
    state = VariantState(variants)
    state.set_variant("production")
    assert state.is_dnp("R1")


def test_variant_state_set_variant_not_found():
    state = VariantState([VariantDefinition(name="Default")])
    with pytest.raises(ValueError, match="not found"):
        state.set_variant("DoesNotExist")


def test_format_b_variant_parsing():
    content = """\
[Variation1]
VariantName=Production

[CompVar1]
RefDesignator1=C45
VariantKind=3

[CompVar2]
RefDesignator1=R12
VariantKind=3

[Variation2]
VariantName=Debug

[CompVar3]
RefDesignator1=U7
VariantKind=3
"""
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.PrjPcb', delete=False, encoding='utf-8') as f:
        f.write(content)
        tmp = f.name
    try:
        result = parse_prj_pcb(tmp)
        names = [v.name for v in result.variants]
        assert "Production" in names
        assert "Debug" in names
        prod = next(v for v in result.variants if v.name == "Production")
        assert "C45" in prod.dnp_refdes
        assert "R12" in prod.dnp_refdes
        debug = next(v for v in result.variants if v.name == "Debug")
        assert "U7" in debug.dnp_refdes
    finally:
        os.unlink(tmp)
