"""Read packaged ``.skill`` bundles (zip archives of SKILL.md + references).

The skill files live inside the installed package (``vcollab_mcp/skills/*.skill``) so they load the
same way in a dev checkout, a pip wheel, and the portable build. Each ``.skill`` is a zip whose top
entry is a folder named after the skill, e.g. ``cae-expert/SKILL.md``,
``cae-expert/references/domains.md``.
"""

from __future__ import annotations

import io
import zipfile
from functools import cache
from importlib.resources import files

# Data lives in vcollab_mcp/skills/. Resolve it through the real ``vcollab_mcp`` package and
# traverse to the data file — the canonical importlib.resources pattern, robust whether the package
# is installed as a directory (editable / portable) or a zip wheel.
_PACKAGE = "vcollab_mcp"
_SKILLS_SUBDIR = "skills"


@cache
def _skill_bytes(skill_file: str) -> bytes:
    """Return the raw bytes of a packaged ``.skill`` archive (cached)."""
    return (files(_PACKAGE) / _SKILLS_SUBDIR / skill_file).read_bytes()


@cache
def read_member(skill_file: str, member: str) -> str:
    """Return a UTF-8 text member from inside a ``.skill`` zip archive (cached).

    Raises:
        KeyError: the member path is not present in the archive.
    """
    with zipfile.ZipFile(io.BytesIO(_skill_bytes(skill_file))) as archive:
        return archive.read(member).decode("utf-8")


def strip_frontmatter(markdown: str) -> str:
    """Drop a leading YAML ``--- ... ---`` frontmatter block, returning the body.

    Only the first two ``---`` delimiters are consumed, so ``---`` horizontal rules later in the
    body are preserved.
    """
    if markdown.lstrip().startswith("---"):
        parts = markdown.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return markdown
