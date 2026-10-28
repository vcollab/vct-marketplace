"""Start the VCollab MCP server in its plugin edition.

The plugin's .mcp.json runs this file with uv (``uv run --frozen ... python server.py``). The
plugin edition exposes no arbitrary-code path: its VCollab Pro batch tool accepts XML jobs only.
"""

from vcollab_mcp.__main__ import main

if __name__ == "__main__":
    main(["--edition", "plugin"])
