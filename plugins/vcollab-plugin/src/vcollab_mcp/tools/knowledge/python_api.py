"""``python_api`` — searchable ``_VCollabAPI`` reference, from the vcollab-python-api skill.

The bundled reference Markdown is regularly structured: ``### Section`` headings group the API, and
each function is a ``#### `name``` block with a description paragraph, a ```python signature fence,
and a ``**Returns**`` line. We parse it once into ~1,178 entries and search by name/keyword.
"""

from __future__ import annotations

import re
from functools import cache

from pydantic import BaseModel, Field

from ._data import read_member, strip_frontmatter

_SKILL = "vcollab-python-api.skill"
_OVERVIEW = "vcollab-python-api/SKILL.md"
_REFERENCE = "vcollab-python-api/references/VCollab_Python_API_Reference.md"

_FUNC_RE = re.compile(r"^####\s+`([^`]+)`\s*$")
_SECTION_RE = re.compile(r"^###\s+(.+?)\s*$")


class ApiFunction(BaseModel):
    """One ``_VCollabAPI`` function entry."""

    name: str = Field(description="Function name, e.g. 'xExportHTML'.")
    signature: str = Field(description="Python call signature.")
    description: str = Field(description="What the function does (and parameter notes).")
    returns: str = Field(default="", description="Return type/meaning, if documented.")
    section: str = Field(default="", description="API category the function belongs to.")


class VCollabApiAnswer(BaseModel):
    """Result of an API lookup."""

    query: str = Field(default="", description="The search query, if any.")
    section: str = Field(default="", description="The section filter, if any.")
    results: list[ApiFunction] = Field(
        default_factory=list, description="Matching functions (most relevant first)."
    )
    sections: list[str] = Field(
        default_factory=list, description="All API sections (populated when browsing/empty query)."
    )
    guidance: str = Field(
        default="", description="API usage guidance (populated when no query/section is given)."
    )
    message: str = Field(description="Human-readable summary of what was returned.")


def _parse_reference(md: str) -> list[ApiFunction]:
    """Parse the reference Markdown into a flat list of function entries."""
    entries: list[ApiFunction] = []
    section = ""
    lines = md.splitlines()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        sec = _SECTION_RE.match(line)
        if sec and not line.startswith("####"):
            section = sec.group(1).strip().strip("`")
            i += 1
            continue
        func = _FUNC_RE.match(line)
        if not func:
            i += 1
            continue
        name = func.group(1).strip()
        i += 1
        desc: list[str] = []
        code: list[str] = []
        returns = ""
        in_code = False
        while i < n:
            cur = lines[i]
            if _FUNC_RE.match(cur) or cur.startswith("## ") or (
                _SECTION_RE.match(cur) and not cur.startswith("####")
            ):
                break
            if cur.strip() == "---":
                i += 1
                break
            if cur.lstrip().startswith("```"):
                in_code = not in_code
                i += 1
                continue
            if in_code:
                code.append(cur)
            elif cur.startswith("**Returns**"):
                returns = cur.strip()
            elif cur.strip():
                desc.append(cur.strip())
            i += 1
        entries.append(
            ApiFunction(
                name=name,
                signature="\n".join(code).strip(),
                description=" ".join(desc).strip(),
                returns=returns,
                section=section,
            )
        )
    return entries


@cache
def _load_functions() -> tuple[ApiFunction, ...]:
    """Parse and cache the reference (immutable tuple so the cached value isn't mutated)."""
    return tuple(_parse_reference(read_member(_SKILL, _REFERENCE)))


@cache
def _section_names() -> tuple[str, ...]:
    seen: list[str] = []
    for fn in _load_functions():
        if fn.section and fn.section not in seen:
            seen.append(fn.section)
    return tuple(seen)


def _score(fn: ApiFunction, query: str, words: list[str]) -> int:
    name = fn.name.lower()
    score = 0
    if name == query:
        score += 1000
    elif name.startswith(query):
        score += 500
    elif query and query in name:
        score += 250
    haystack = f"{fn.name} {fn.description}".lower()
    for word in words:
        if word in name:
            score += 20
        elif word in haystack:
            score += 10
    return score


def python_api(query: str = "", section: str = "", limit: int = 20) -> VCollabApiAnswer:
    """Look up ``_VCollabAPI`` functions (see the registered tool for full docs).

    With a ``query`` → ranked matching functions. With a ``section`` → that category's functions.
    With neither → the API overview plus the list of sections.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1.")
    functions = _load_functions()
    q = (query or "").strip().lower()
    sec = (section or "").strip().lower()

    if not q and not sec:
        overview = strip_frontmatter(read_member(_SKILL, _OVERVIEW))
        names = _section_names()
        return VCollabApiAnswer(
            sections=list(names),
            guidance=overview,
            message=(
                f"VCollab Pro _VCollabAPI: {len(functions)} functions across {len(names)} "
                "sections. Pass `query` (a function name or keyword) to look one up, or `section` "
                "to list a category."
            ),
        )

    if sec:
        matches = [fn for fn in functions if sec in fn.section.lower()][:limit]
        return VCollabApiAnswer(
            section=section,
            results=matches,
            message=f"{len(matches)} function(s) in sections matching {section!r}.",
        )

    words = [w for w in re.split(r"[\s,]+", q) if w]
    scored = sorted(
        ((_score(fn, q, words), fn) for fn in functions),
        key=lambda pair: (-pair[0], pair[1].name),
    )
    matches = [fn for score, fn in scored if score > 0][:limit]
    return VCollabApiAnswer(
        query=query,
        results=matches,
        message=(
            f"{len(matches)} function(s) matching {query!r}."
            if matches
            else f"No functions matched {query!r}. Try a broader keyword or a function-name prefix."
        ),
    )
