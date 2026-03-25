"""HTTP transport entry point for Smithery deployment."""

import os
from revettr_mcp.server import mcp

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8081"))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
