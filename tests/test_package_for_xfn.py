import json
from main import _package_for_xfn_impl


class _FakeVariant:
    def __init__(self, name, dnp_refdes=None):
        self.name = name
        self.dnp_refdes = dnp_refdes or []


class _FakeVS:
    def __init__(self, variants=None):
        self._variants = variants or []


def _project(tmp_path):
    return {
        "name": "MotorController",
        "root_dir": str(tmp_path),
        "prj_pcb_path": str(tmp_path / "MotorController.PrjPcb"),
        "sheets": [{"name": "MCU", "path": ""}],
    }


def _netlist():
    return {
        "nets": {"VCC": [("U1", "1")]},
        "pin_to_net": {"U1": {"1": "VCC"}},
        "components": {
            "U1": {
                "mpn": "STM32G474",
                "description": "MCU",
                "value": None,
                "sheet": "MCU",
                "pins": {"1": {"name": "VCC", "net": "VCC"}},
            }
        },
    }


def test_success_response_contains_path(tmp_path):
    result = _package_for_xfn_impl(_project(tmp_path), _netlist(), _FakeVS(), "0.1.10")
    expected_path = str(tmp_path / "MotorController-pcb-copilot.db")
    assert f"Exported to: {expected_path}" in result


def test_success_response_contains_sharing_guidance(tmp_path):
    result = _package_for_xfn_impl(_project(tmp_path), _netlist(), _FakeVS(), "0.1.0")
    assert "Slack" in result
    assert "Git" in result


def test_duplicate_refdes_returns_error_json(tmp_path):
    class _DuplicateDict(dict):
        def items(self):
            comp = {"mpn": None, "description": None, "value": None, "sheet": "MCU", "pins": {}}
            yield "R1", comp
            yield "R1", comp

    netlist = {"nets": {}, "pin_to_net": {}, "components": _DuplicateDict()}
    result = json.loads(_package_for_xfn_impl(_project(tmp_path), netlist, _FakeVS(), "0.1.0"))
    assert result["error"] == "export_failed"
    assert "R1" in result["message"]
