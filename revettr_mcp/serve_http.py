"""HTTP transport entry point for Smithery deployment.

Security note: Set the REVETTR_MCP_TOKEN environment variable in production.
When set, a warning is logged that auth is not enforced at the transport level
and the endpoint must be placed behind an authenticating reverse proxy (e.g.
Nginx, Caddy, or a cloud load balancer with bearer-token validation).
"""

import logging
import os

from revettr_mcp.server import mcp

logger = logging.getLogger("revettr_mcp.serve_http")

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8081"))
    token = os.environ.get("REVETTR_MCP_TOKEN")

    if not token:
        logger.warning(
            "REVETTR_MCP_TOKEN is not set. The MCP HTTP endpoint has NO "
            "authentication. Set REVETTR_MCP_TOKEN and place this service "
            "behind an authenticating reverse proxy before exposing to the "
            "internet."
        )
    else:
        logger.warning(
            "REVETTR_MCP_TOKEN is set but auth is NOT enforced at the "
            "transport level. Ensure this endpoint is behind an "
            "authenticating reverse proxy that validates the bearer token."
        )

    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
