"""Revettr MCP Server — counterparty risk scoring as an MCP tool."""

from revettr_mcp.server import mcp

__all__ = ["mcp"]


def main():
    """Entry point for `revettr-mcp` CLI command."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
