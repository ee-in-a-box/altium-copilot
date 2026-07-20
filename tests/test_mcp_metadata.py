import asyncio
import json
from pathlib import Path

import server.main as main_mod


def _manifest() -> dict:
    return json.loads(
        (Path(__file__).parents[1] / "manifest.json").read_text(
            encoding="utf-8"
        )
    )


def test_manifest_declares_every_registered_mcp_tool():
    registered = {
        tool.name
        for tool in asyncio.run(main_mod.mcp.list_tools())
    }
    declared = {tool["name"] for tool in _manifest()["tools"]}

    assert declared == registered


def test_mcp_initialize_version_matches_manifest():
    options = main_mod.mcp._mcp_server.create_initialization_options()

    assert options.server_version == _manifest()["version"]
