"""Reporting / visual-output tools (the ``report`` group): image_generator.

Each module exposes a typed result model and a service function that turns a VCollab model into a
shareable artifact (e.g. a rendered image). The shared ``produce_output`` helper (in
:mod:`vcollab_mcp.tools._output`) makes the write crash-safe. The FastMCP wiring (and the shared
``report`` tag) lives in :mod:`vcollab_mcp.server`.
"""
