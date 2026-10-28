"""CAX combination tools (the ``merge`` group): caxmerge.

Each module exposes a typed result model and a service function that combines VCollab files into a
single ``.cax`` (e.g. merging several result files, or baking a ``.vpt`` viewpoint file into a CAX).
The shared ``produce_output`` helper (in :mod:`vcollab_mcp.tools._output`) makes the write
crash-safe. The FastMCP wiring (and the shared ``merge`` tag) lives in :mod:`vcollab_mcp.server`.
"""
