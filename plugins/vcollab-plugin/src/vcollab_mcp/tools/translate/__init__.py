"""Native-file → CAX translators (the ``translate`` group): vmovecae, vmovecad.

Each module exposes a typed result model and a service function that wraps a VCollab batch
translator, producing a ``.cax`` from a native solver (CAE) or CAD file. The shared
``produce_output`` helper (in :mod:`vcollab_mcp.tools._output`) makes the write crash-safe.
"""
