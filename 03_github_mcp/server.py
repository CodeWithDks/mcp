"""
github_mcp — server entry point.

This is the file you point Claude Desktop / MCP Inspector at. It doesn't
define any tools itself — it imports mcp_instance.mcp (the shared server)
and every module that registers tools/resources/prompts against it via
decorators, then runs the server.

Project layout:
    github_client.py   API client (all GitHub HTTP calls)
    mcp_instance.py     Shared FastMCP + GitHubClient instances
    helpers.py          Error handling, pagination, response simplification
    schemas.py           Pydantic input models + enums
    read_tools.py        Read-only tools           (safe, no confirmation needed)
    update_tools.py     Tools that modify existing resources
    create_tools.py     Tools that create new resources
    resources.py        MCP resources (devops://github/...)
    prompts.py            MCP prompts (multi-tool workflow templates)
    server.py            <- you are here
"""

from mcp_instance import mcp

# Each import below has side effects: it runs the module's @mcp.tool /
# @mcp.resource / @mcp.prompt decorators, registering everything onto the
# shared `mcp` instance. The imported names aren't used directly, hence noqa.
import read_tools  # noqa: F401
import update_tools  # noqa: F401
import create_tools  # noqa: F401
import resources  # noqa: F401
import prompts  # noqa: F401


if __name__ == "__main__":
    mcp.run()