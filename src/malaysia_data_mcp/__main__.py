"""Entry point so `python -m malaysia_data_mcp` works.

This file lets external launchers (Claude Desktop, MCP Inspector, etc.)
start the server without knowing the internal module path. Without it,
`python -m malaysia_data_mcp` fails because Python treats the package as
non-runnable.

Caught during fresh-install integration testing — the test that found this
is "does Claude Desktop actually launch the server."
"""
from malaysia_data_mcp.presentation.mcp_server import main

if __name__ == "__main__":
    main()
