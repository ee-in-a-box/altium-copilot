# tests/test_variant_tools.py
import json
import pytest
from parsers.prj_pcb import VariantDefinition, VariantState
from main import _list_variants_impl, _set_active_variant_impl


@pytest.fixture
def vs_with_variants():
    return VariantState([
        VariantDefinition(name="Default", dnp_refdes=[]),
        VariantDefinition(name="Production", dnp_refdes=["C45", "R12", "U7"]),
    ])


def test_list_variants(vs_with_variants):
    result = json.loads(_list_variants_impl(vs_with_variants))
    assert result["active_variant"] == "Default"
    names = [v["name"] for v in result["variants"]]
    assert names == ["Default", "Production"]
    default_entry = next(v for v in result["variants"] if v["name"] == "Default")
    assert default_entry["is_active"] is True
    assert default_entry["dnp_count"] == 0
    prod_entry = next(v for v in result["variants"] if v["name"] == "Production")
    assert prod_entry["is_active"] is False
    assert prod_entry["dnp_count"] == 3
    assert "U7" in prod_entry["dnp_components"]


def test_set_active_variant_success(vs_with_variants):
    result = json.loads(_set_active_variant_impl(vs_with_variants, "Production"))
    assert result["active_variant"] == "Production"
    assert "C45" in result["dnp_components"]
    assert vs_with_variants.active.name == "Production"


def test_set_active_variant_not_found(vs_with_variants):
    result = json.loads(_set_active_variant_impl(vs_with_variants, "Nonexistent"))
    assert result["error"] == "variant_not_found"
    assert vs_with_variants.active.name == "Default"


def test_set_active_variant_case_insensitive(vs_with_variants):
    result = json.loads(_set_active_variant_impl(vs_with_variants, "production"))
    assert result["active_variant"] == "Production"


def test_list_variants_single_default():
    vs = VariantState([VariantDefinition(name="Default")])
    result = json.loads(_list_variants_impl(vs))
    assert len(result["variants"]) == 1
    assert result["variants"][0]["is_active"] is True
