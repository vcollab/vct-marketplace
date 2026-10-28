"""``cae_expert`` — senior CAE-engineer review knowledge from the cae-expert skill bundle."""

from __future__ import annotations

from pydantic import BaseModel, Field

from ._data import read_member, strip_frontmatter

_SKILL = "cae-expert.skill"

# topic -> member path inside the skill zip.
_TOPICS: dict[str, str] = {
    "overview": "cae-expert/SKILL.md",
    "domains": "cae-expert/references/domains.md",
    "postprocessing": "cae-expert/references/postprocessing.md",
}
_AVAILABLE = [*_TOPICS, "all"]


class CaeExpertKnowledge(BaseModel):
    """A slice of the CAE-expert knowledge base."""

    topic: str = Field(description="The topic returned.")
    content: str = Field(description="The Markdown knowledge content for the topic.")
    available_topics: list[str] = Field(
        default_factory=lambda: list(_AVAILABLE),
        description="All topics this tool can return.",
    )


def cae_expert(topic: str = "overview") -> CaeExpertKnowledge:
    """Return CAE-expert review guidance for ``topic`` (see the registered tool for full docs).

    Raises:
        ValueError: ``topic`` is not one of the available topics.
    """
    key = (topic or "overview").strip().lower()
    if key not in _AVAILABLE:
        raise ValueError(
            f"Unknown topic {topic!r}. Choose one of: {', '.join(_AVAILABLE)}."
        )

    if key == "all":
        sections = [
            f"# {name}\n\n{strip_frontmatter(read_member(_SKILL, path))}"
            for name, path in _TOPICS.items()
        ]
        content = "\n\n---\n\n".join(sections)
    else:
        content = strip_frontmatter(read_member(_SKILL, _TOPICS[key]))

    return CaeExpertKnowledge(topic=key, content=content, available_topics=list(_AVAILABLE))
