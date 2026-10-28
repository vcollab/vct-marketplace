"""Pre-flight validation tools (the ``validate`` group): vmovecaevalidate.

Each module exposes a typed result model and a service function that checks an input (e.g. a
VMoveCAE command file) WITHOUT performing a translation or writing a ``.cax``. The shared
command-file helper (in :mod:`vcollab_mcp.tools._command_file`) is reused with the ``translate``
group. The FastMCP wiring (and the shared ``validate`` tag) lives in :mod:`vcollab_mcp.server`.
"""
