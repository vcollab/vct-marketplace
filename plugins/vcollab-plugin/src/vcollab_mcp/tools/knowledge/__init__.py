"""Knowledge tools — expose packaged VCollab/CAE reference material to the LLM.

These tools serve the contents of the bundled ``.skill`` packages (see ``vcollab_mcp/skills/``)
as ordinary MCP tool results, so any client gets the knowledge uniformly (unlike skill *resources*,
which clients surface inconsistently):

* :func:`cae_expert` — senior-CAE-engineer review protocol + domain/post-processing references.
* :func:`python_api` — searchable ``_VCollabAPI`` function reference for writing ``vcollabpro``
  Python scripts.
"""
