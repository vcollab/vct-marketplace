"""``caxinfo`` — extract typed metadata from a VCollab ``.cax`` file.

``CaxInfo.exe`` (``CaxInfo <cax_file> [output_file]``) prints a flat ``<vct:metadata>`` block
of ``<attribute name=.. value=..>`` elements to stdout. Per the VCollab help, this metadata
covers the file's **change history**, **parts/element-set** info, and **available results**.

This module parses that into a typed :class:`CaxInfoResult`: it reconstructs the change history
from the ``... (Original Modification)`` / ``... (Latest Translation)`` attribute variants,
promotes the model/results source-file info, and splits the comma-separated
``Parts`` / ``Results`` / ``Instances`` / ``Time Steps`` lists into arrays.

(The optional ``[output_file]`` argument only redirects the same metadata to a file; we always
read it from stdout, so it is not exposed.)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from pydantic import BaseModel, Field

from ...paths import PathPolicy
from ...process import run_executable
from ...settings import Settings

_NAMESPACE = "http://www.vcollab.com/xml/namespace"

# Change-history attributes look like "Application name (Latest Translation)". The stage is the
# parenthetical; the same four fields recur per stage.
_HISTORY_RE = re.compile(r"^(Application name|Application version|Cax version|Date) \((.+)\)$")
_HISTORY_FIELD = {
    "Application name": "application",
    "Application version": "application_version",
    "Cax version": "cax_version",
    "Date": "date",
}


class CaxTranslation(BaseModel):
    """One entry in a CAX file's change history (a translation/modification event)."""

    stage: str = Field(description="e.g. 'Original Modification' or 'Latest Translation'.")
    application: str | None = None
    application_version: str | None = None
    cax_version: str | None = None
    date: str | None = None


class CaxInfoResult(BaseModel):
    """Structured metadata extracted from a CAX file."""

    file: str = Field(description="The CAX file that was inspected.")
    model_file: str | None = Field(default=None, description="Source model file name.")
    model_file_type: str | None = Field(
        default=None, description="Source solver/format, e.g. 'Nastran OP2'."
    )
    results_file: str | None = Field(
        default=None, description="Separate source results file, if any."
    )
    results_file_type: str | None = Field(default=None)
    category: str | None = Field(default=None, description="Analysis category, e.g. 'Structural'.")

    # Representative translation (most recent known: Latest Translation, else Original).
    cax_version: str | None = Field(default=None)
    application: str | None = Field(default=None, description="Translating application name.")
    application_version: str | None = Field(default=None)
    translation_date: str | None = Field(default=None)

    native_file_size: str | None = Field(
        default=None, description="Source model file size (human-readable)."
    )
    native_results_file_size: str | None = Field(default=None)
    cax_file_size: str | None = Field(default=None, description="CAX file size (human-readable).")

    num_parts: int = 0
    num_results: int = 0
    num_instances: int = 0
    num_cut_sections: int = 0
    num_iso_surfaces: int = 0
    num_iso_volumes: int = 0
    num_flow_lines: int = 0

    parts: list[str] = Field(default_factory=list)
    results: list[str] = Field(default_factory=list)
    instances: list[str] = Field(default_factory=list)
    time_steps: list[str] = Field(default_factory=list)

    history: list[CaxTranslation] = Field(
        default_factory=list, description="Change history (translation/modification events)."
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="All raw attributes from CaxInfo, for fields not promoted above.",
    )


def caxinfo(input_path: str, *, settings: Settings, paths: PathPolicy) -> CaxInfoResult:
    """Run ``CaxInfo.exe`` on a ``.cax`` file and return typed metadata."""
    resolved = paths.resolve_input(input_path)
    exe = settings.resolve_executable("caxinfo")
    result = run_executable(
        exe,
        [str(resolved)],
        timeout=settings.timeout_for("caxinfo"),
        env=settings.subprocess_env(),
    )
    return parse_caxinfo(result.stdout, file_name=resolved.name)


def parse_caxinfo(raw: str, *, file_name: str) -> CaxInfoResult:
    """Parse raw ``CaxInfo.exe`` stdout into a :class:`CaxInfoResult`.

    Pure function (no I/O) so it can be unit-tested against captured fixtures.
    """
    attrs = _extract_attributes(raw)
    history = _parse_history(attrs)
    rep = _representative(history)

    return CaxInfoResult(
        file=file_name,
        model_file=attrs.get("Model File"),
        model_file_type=attrs.get("Model File Type"),
        results_file=attrs.get("Results File"),
        results_file_type=attrs.get("Results File Type"),
        category=attrs.get("Category"),
        cax_version=rep.cax_version if rep else None,
        application=rep.application if rep else None,
        application_version=rep.application_version if rep else None,
        translation_date=rep.date if rep else None,
        native_file_size=attrs.get("Native Model File Size"),
        native_results_file_size=attrs.get("Native Results File Size"),
        cax_file_size=attrs.get("Cax File Size"),
        num_parts=_as_int(attrs.get("Number of Parts")),
        num_results=_as_int(attrs.get("Number of Results")),
        num_instances=_as_int(attrs.get("Number of Instances")),
        num_cut_sections=_as_int(attrs.get("Number of Cut-sections")),
        num_iso_surfaces=_as_int(attrs.get("Number of Iso-surfaces")),
        num_iso_volumes=_as_int(attrs.get("Number of Iso-volumes")),
        num_flow_lines=_as_int(attrs.get("Number of Flow-lines")),
        parts=_as_list(attrs.get("Parts")),
        results=_as_list(attrs.get("Results")),
        instances=_as_list(attrs.get("Instances")),
        time_steps=_as_list(attrs.get("Time Steps")),
        history=history,
        metadata=attrs,
    )


def _extract_attributes(raw: str) -> dict[str, str]:
    """Pull every ``<attribute name=.. value=..>`` into a dict, namespace-agnostic."""
    start = raw.find("<")
    if start == -1:
        return {}
    xml_text = raw[start:]
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    attrs: dict[str, str] = {}
    # Match the 'attribute' tag with or without the vct namespace prefix.
    for tag in ("attribute", f"{{{_NAMESPACE}}}attribute"):
        for node in root.iter(tag):
            name = node.get("name")
            if name:
                attrs[name] = node.get("value", "")
    return attrs


def _parse_history(attrs: dict[str, str]) -> list[CaxTranslation]:
    """Reconstruct the change history from '<field> (<stage>)' attributes, in file order."""
    stages: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for name, value in attrs.items():
        match = _HISTORY_RE.match(name)
        if match is None:
            continue
        field_label, stage = match.group(1), match.group(2)
        if stage not in stages:
            stages[stage] = {}
            order.append(stage)
        stages[stage][_HISTORY_FIELD[field_label]] = value
    return [CaxTranslation(stage=stage, **stages[stage]) for stage in order]


def _representative(history: list[CaxTranslation]) -> CaxTranslation | None:
    """Pick the entry that best describes the file's current state: latest, else original."""
    if not history:
        return None
    for entry in history:
        if "latest" in entry.stage.lower():
            return entry
    for entry in history:
        if "original" in entry.stage.lower():
            return entry
    return history[0]


def _as_int(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(value.strip())
    except ValueError:
        return 0


def _as_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]
