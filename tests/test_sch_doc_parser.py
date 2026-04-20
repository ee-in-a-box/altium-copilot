from pathlib import Path
import pytest
from server.parsers.sch_doc import parse_sch_doc

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def sheet1():
    return parse_sch_doc(str(FIXTURES / "sheet1.SchDoc"))


def test_known_component_present(sheet1):
    assert "U1" in sheet1


def test_component_mpn_plain_form(sheet1):
    # U1 uses plain 'Manufacturer Part Number'
    assert sheet1["U1"].mpn == "STM32F407VGT6"


def test_component_mpn_suffix_fallback(sheet1):
    # R11 has 'Manufacturer Part Number 1' — no plain form
    assert "R11" in sheet1
    assert sheet1["R11"].mpn == "ERJ-3EKF1000V"


def test_component_description(sheet1):
    assert sheet1["U1"].description is not None
    assert "STM32" in sheet1["U1"].description


def test_named_pins_extracted(sheet1):
    # J1 is a debug connector with named pins
    assert sheet1["J1"].pins.get("1") == "VCC"
    assert sheet1["J1"].pins.get("3") == "GND"


def test_unnamed_pins_skipped(sheet1):
    # Passive components (R, C) have generic pin names — not stored
    # R11 pins should be empty or absent (name was '?')
    pins = sheet1["R11"].pins
    assert "?" not in pins.values()


def test_all_expected_components_present(sheet1):
    expected = {"U1", "U2", "R11", "C1", "J1", "X1", "RST1"}
    assert expected.issubset(set(sheet1.keys()))


def test_no_power_symbols(sheet1):
    # Power ports (RECORD=17) must not appear — they have no refdes
    for refdes in sheet1:
        assert refdes  # empty refdes would indicate a leaked power port
        assert refdes not in ("VCC", "GND", "3V3", "5V")


def test_rst1_mpn(sheet1):
    assert sheet1["RST1"].mpn == "B3U-1000P"


def test_sheet2_smoke():
    result = parse_sch_doc(str(FIXTURES / "sheet2.SchDoc"))
    assert len(result) > 0
    assert "U3" in result
    assert result["U3"].mpn == "LTC6811HG-1#3ZZTRPBF"


def test_multipart_dedup():
    # sheet1.SchDoc has STM32F407 split across multiple parts — must appear once
    result = parse_sch_doc(str(FIXTURES / "sheet1.SchDoc"))
    stm32_entries = [r for r in result if result[r].description and "STM32" in result[r].description]
    refdes_set = set(stm32_entries)
    # One physical chip = one refdes
    assert len(refdes_set) == 1
