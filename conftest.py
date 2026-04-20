import sys
import os
from pathlib import Path

import pytest

# Make 'server' importable as a package from the project root (for existing tests)
sys.path.insert(0, os.path.dirname(__file__))
# Also allow direct imports from server/ (for new services tests)
sys.path.insert(0, str(Path(__file__).parent / "server"))


@pytest.fixture
def sample_netlist():
    return {
        "nets": {
            "MCU_UART_TX": [("U1", "PA9"), ("R45", "1")],
            "USB_UART_RX": [("R45", "2"), ("U2", "RX")],
            "3V3": [("U1", "VCC"), ("C1", "1")],
            "GND": [("U1", "GND"), ("C1", "2")],
        },
        "pin_to_net": {
            "U1": {"PA9": "MCU_UART_TX", "VCC": "3V3", "GND": "GND"},
            "R45": {"1": "MCU_UART_TX", "2": "USB_UART_RX"},
            "U2": {"RX": "USB_UART_RX"},
            "C1": {"1": "3V3", "2": "GND"},
        },
        "components": {
            "U1": {
                "mpn": "STM32G474RET6",
                "description": "ARM Cortex-M4 MCU",
                "value": None,
                "sheet": "MCU",
                "pins": {
                    "PA9": {"name": "PA9", "net": "MCU_UART_TX"},
                    "VCC": {"name": "VCC", "net": "3V3"},
                    "GND": {"name": "GND", "net": "GND"},
                },
            },
            "R45": {
                "mpn": "RC0402FR-0710KL",
                "description": "RES 10K OHM",
                "value": "10K",
                "sheet": "Comms",
                "pins": {
                    "1": {"name": "~", "net": "MCU_UART_TX"},
                    "2": {"name": "~", "net": "USB_UART_RX"},
                },
            },
            "U2": {
                "mpn": "CH340G",
                "description": "USB UART Bridge",
                "value": None,
                "sheet": "Comms",
                "pins": {"RX": {"name": "RX", "net": "USB_UART_RX"}},
            },
            "C1": {
                "mpn": "GRM155R61A225ME11",
                "description": "CAP 2.2uF 10V",
                "value": "2.2uF",
                "sheet": "PowerSupply",
                "pins": {
                    "1": {"name": "+", "net": "3V3"},
                    "2": {"name": "-", "net": "GND"},
                },
            },
        },
    }
