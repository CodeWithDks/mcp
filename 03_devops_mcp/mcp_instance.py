"""
Shared FastMCP server instance and GitHubClient.

Every module that registers tools/resources/prompts (read_tools.py,
update_tools.py, create_tools.py, resources.py, prompts.py) imports `mcp`
and `github` from here instead of creating its own — this is what lets
decorators in separate files all attach to the same running server.
"""

from fastmcp import FastMCP

# pyrefly: ignore [missing-import]
from github_client import GitHubClient

mcp = FastMCP("github_mcp")
github = GitHubClient()