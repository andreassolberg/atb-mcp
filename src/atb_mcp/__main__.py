"""Entry point for the ATB MCP server."""

import os
from .server import mcp


def main():
    transport = os.environ.get("MCP_TRANSPORT", "http")
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "8000"))
    mcp.run(transport=transport, host=host, port=port)


if __name__ == "__main__":
    main()
