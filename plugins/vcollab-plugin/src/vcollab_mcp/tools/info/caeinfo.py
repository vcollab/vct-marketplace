"""``caeinfo`` — extract typed metadata from a native CAE file.

``CaeInfo.exe`` takes a model file and an *optional* separate results file
(``CaeInfo <model_file> [results_file]`` — needed for solvers like Fluent that split
``.cas`` model + ``.dat`` results) and prints a nested XML tree to stdout::

    <node name="VMoveCAE">
      <node name="{model}">
        <attribute key="Model file" value="..."/>
        <node name="Results"|"Datasets"> ... per-result <node> ... </node>
        <node name="Association Metadata"> ... count attributes ... </node>
        <node name="Face Zones"|"Cell Zones"|"Constraints"|...> ... group items ... </node>
      </node>
    </node>

Two things make this tricky and are handled generically here:

* attributes use ``key=``/``value=`` (CAX uses ``name=``);
* the section that holds results is named ``Results`` for Fluent/LS-DYNA but ``Datasets``
  for Ansys, and the remaining section names differ per solver — so every non-results
  section is captured generically rather than hard-coded.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pydantic import BaseModel, Field

from ...paths import PathPolicy
from ...process import run_executable
from ...settings import Settings

_RESULT_SECTION_NAMES = {"results", "datasets"}
_ASSOCIATION_SECTION_NAME = "association metadata"


class CaeResult(BaseModel):
    """A single result/dataset available in the CAE file."""

    name: str = Field(description="Raw node name, e.g. 'PRES.E:1 : 146'.")
    contents: str | None = Field(default=None, description="Human label, e.g. 'Pressure'.")
    data_type: str | None = Field(default=None, description="'Scalar', 'Vector', 'SixDof', etc.")
    entity_type: str | None = Field(default=None, description="'node' or 'element'.")
    dataset_name: str | None = None
    data_source: str | None = None
    result_type: str | None = None
    num_entities: int | None = Field(
        default=None, description="Number of elements or nodes the result covers."
    )
    attributes: dict[str, str] = Field(
        default_factory=dict, description="All raw attributes for this result."
    )


class CaeItem(BaseModel):
    """A named item inside a non-results section (a part, zone, constraint, material, ...)."""

    name: str
    attributes: dict[str, str] = Field(default_factory=dict)


class CaeSection(BaseModel):
    """A non-results section of the CAE metadata tree (name varies by solver)."""

    name: str
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Section-level attributes, e.g. Association Metadata counts.",
    )
    item_count: int = 0
    items: list[CaeItem] = Field(default_factory=list)


class CaeInfoResult(BaseModel):
    """Structured metadata extracted from a native CAE file."""

    file: str = Field(description="The model file that was inspected.")
    results_file: str | None = Field(default=None, description="Separate results file, if any.")
    model_name: str | None = None
    model_file: str | None = None
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Model-level attributes (Model file, Results file, ...)."
    )
    summary: dict[str, str] = Field(
        default_factory=dict, description="Headline counts promoted from 'Association Metadata'."
    )
    num_results: int = 0
    results: list[CaeResult] = Field(default_factory=list)
    sections: list[CaeSection] = Field(
        default_factory=list, description="All non-results sections, captured generically."
    )


def caeinfo(
    input_path: str,
    results_path: str = "",
    *,
    settings: Settings,
    paths: PathPolicy,
) -> CaeInfoResult:
    """Run ``CaeInfo.exe`` on a native CAE file and return typed metadata.

    Args:
        input_path: The model file (e.g. 'beam.rst', 'd3plot', 'model.cas').
        results_path: Optional separate results file (e.g. Fluent '.dat' paired with a '.cas').
    """
    resolved = paths.resolve_input(input_path)
    args = [str(resolved)]
    resolved_results = paths.resolve_input(results_path) if results_path else None
    if resolved_results is not None:
        args.append(str(resolved_results))
    exe = settings.resolve_executable("caeinfo")
    result = run_executable(
        exe,
        args,
        timeout=settings.timeout_for("caeinfo"),
        env=settings.subprocess_env(),
    )
    return parse_caeinfo(
        result.stdout,
        file_name=resolved.name,
        results_file=resolved_results.name if resolved_results else None,
    )


def parse_caeinfo(
    raw: str,
    *,
    file_name: str,
    results_file: str | None = None,
) -> CaeInfoResult:
    """Parse raw ``CaeInfo.exe`` stdout into a :class:`CaeInfoResult`. Pure, no I/O."""
    model_node = _find_model_node(raw)
    if model_node is None:
        return CaeInfoResult(file=file_name, results_file=results_file)

    model_attrs = _attrs(model_node)
    results: list[CaeResult] = []
    sections: list[CaeSection] = []
    summary: dict[str, str] = {}

    for section in model_node.findall("node"):
        sec_name = section.get("name", "")
        sec_attrs = _attrs(section)
        item_nodes = section.findall("node")

        if sec_name.lower() in _RESULT_SECTION_NAMES:
            results.extend(_parse_result(item) for item in item_nodes)
            continue

        items = [CaeItem(name=i.get("name", ""), attributes=_attrs(i)) for i in item_nodes]
        sections.append(
            CaeSection(name=sec_name, attributes=sec_attrs, item_count=len(items), items=items)
        )
        if sec_name.lower() == _ASSOCIATION_SECTION_NAME:
            summary = sec_attrs

    return CaeInfoResult(
        file=file_name,
        results_file=results_file or model_attrs.get("Results file"),
        model_name=model_node.get("name"),
        model_file=model_attrs.get("Model file"),
        metadata=model_attrs,
        summary=summary,
        num_results=len(results),
        results=results,
        sections=sections,
    )


def _find_model_node(raw: str) -> ET.Element | None:
    """Return the model node under <VMoveCAE>, tolerating junk around the XML.

    CaeInfo.exe wraps the XML in non-XML chatter — a log line *before* and progress lines
    *after* (e.g. "Deleting temporary files ..."). We slice from the opening ``<node`` to the
    final ``</node>`` so ``ElementTree`` does not choke on "junk after document element".
    """
    start = raw.find("<node")
    if start == -1:
        start = raw.find("<")
    if start == -1:
        return None
    close = raw.rfind("</node>")
    xml_text = raw[start : close + len("</node>")] if close != -1 else raw[start:]
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    # root is <node name="VMoveCAE">; the model is its first child <node>.
    return root.find("node")


def _attrs(node: ET.Element) -> dict[str, str]:
    return {a.get("key", ""): a.get("value", "") for a in node.findall("attribute")}


def _parse_result(node: ET.Element) -> CaeResult:
    a = _attrs(node)
    num = a.get("Number of Elements") or a.get("Number of Nodes")
    return CaeResult(
        name=node.get("name", ""),
        contents=a.get("Contents"),
        data_type=a.get("DataType"),
        entity_type=a.get("Entity Type"),
        dataset_name=a.get("Dataset Name"),
        data_source=a.get("DataSource"),
        result_type=a.get("Result Type"),
        num_entities=_as_int_or_none(num),
        attributes=a,
    )


def _as_int_or_none(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None
