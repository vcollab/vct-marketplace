"""``cadinfo`` — extract typed metadata from a native CAD file.

``CadInfo.exe`` (``CadInfo [options] <cad_file>``, in ``VMoveCAD64``) reads a CAD geometry file
(CATIA ``.CATPart``/``.CATProduct``, Pro/E, STEP, IGES, ...) and prints a nested XML tree to
stdout, wrapped in non-XML chatter (``Setting Log file ...``/``Reading file ...`` before,
``Meta data extracted successfully!!!`` after)::

    <node name="VMoveCAD">
      <node name="{model}">
        <attribute key="modelFile" value="..."/>
        <node name="modelParameters"> CAD package / units / part number / source / ... </node>
        <node name="massProperties"> Density, Volume, Mass, Surface, CoG, inertia tensor </node>
        ... more such nodes for an assembly ...
      </node>
    </node>

Like CaeInfo (and unlike CaxInfo) attributes use ``key=``/``value=``, so the parser strips the
surrounding junk and walks the node tree. Each child of the model node that is not the
parameters node is treated as a part with mass properties. Attribute-key casing differs across
VCollab versions (26.1 lowercases ``modelFile``/``cadPackageName``/``units``; older builds used
``ModelFile``/``CadPackageName``/``Units``), so those fields are matched case-insensitively.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from pydantic import BaseModel, Field

from ...paths import PathPolicy
from ...process import run_executable
from ...settings import Settings

_PARAMETERS_NODE = "modelparameters"
_INERTIA_KEYS = ("Ixx", "Iyx", "Izx", "Ixy", "Iyy", "Izy", "Ixz", "Iyz", "Izz")


class CadPart(BaseModel):
    """Mass properties of a single CAD part."""

    name: str
    density: str | None = None
    volume: str | None = None
    mass: str | None = None
    weight: str | None = None
    surface: str | None = None
    cog_x: str | None = Field(default=None, description="X center of gravity.")
    cog_y: str | None = Field(default=None, description="Y center of gravity.")
    cog_z: str | None = Field(default=None, description="Z center of gravity.")
    inertia: dict[str, str] = Field(
        default_factory=dict, description="Inertia tensor components Ixx..Izz."
    )
    attributes: dict[str, str] = Field(
        default_factory=dict, description="All raw attributes for this part."
    )


class CadInfoResult(BaseModel):
    """Structured metadata extracted from a native CAD file."""

    file: str = Field(description="The CAD file that was inspected.")
    model_name: str | None = None
    model_file: str | None = Field(default=None, description="Source model file path/name.")
    cad_package: str | None = Field(
        default=None, description="Authoring CAD system, e.g. 'Catia V5'."
    )
    cad_package_version: str | None = None
    author: str | None = None
    creation_date: str | None = None
    units: str | None = None
    num_parts: int = 0
    parts: list[CadPart] = Field(default_factory=list)
    parameters: dict[str, str] = Field(
        default_factory=dict, description="Raw ModelParameters attributes."
    )
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Model-level attributes (ModelFile, ...)."
    )


def cadinfo(input_path: str, *, settings: Settings, paths: PathPolicy) -> CadInfoResult:
    """Run ``CadInfo.exe`` on a native CAD file and return typed metadata."""
    resolved = paths.resolve_input(input_path)
    exe = settings.resolve_executable("cadinfo")
    result = run_executable(
        exe,
        [str(resolved)],
        timeout=settings.timeout_for("cadinfo"),
        env=settings.subprocess_env(),
    )
    return parse_cadinfo(result.stdout, file_name=resolved.name)


def parse_cadinfo(raw: str, *, file_name: str) -> CadInfoResult:
    """Parse raw ``CadInfo.exe`` stdout into a :class:`CadInfoResult`. Pure, no I/O."""
    model_node = _find_model_node(raw)
    if model_node is None:
        return CadInfoResult(file=file_name)

    model_attrs = _attrs(model_node)
    parameters: dict[str, str] = {}
    parts: list[CadPart] = []

    for child in model_node.findall("node"):
        if child.get("name", "").lower() == _PARAMETERS_NODE:
            parameters = _attrs(child)
        else:
            parts.append(_parse_part(child))

    return CadInfoResult(
        file=file_name,
        model_name=model_node.get("name"),
        # Attribute-key casing differs across VCollab versions (e.g. 26.1 emits 'modelFile',
        # 'cadPackageName', 'units'; older builds used 'ModelFile', 'CadPackageName', 'Units'),
        # so promote these case-insensitively. Mass-property keys are stable across versions.
        model_file=_get_ci(model_attrs, "modelFile"),
        cad_package=_get_ci(parameters, "cadPackageName"),
        cad_package_version=_get_ci(parameters, "cadPackageVersion"),
        author=_get_ci(parameters, "authorName"),
        creation_date=_get_ci(parameters, "creationDate"),
        units=_get_ci(parameters, "units"),
        num_parts=len(parts),
        parts=parts,
        parameters=parameters,
        metadata=model_attrs,
    )


def _find_model_node(raw: str) -> ET.Element | None:
    """Return the model node under <VMoveCAD>, tolerating junk before and after the XML."""
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
    return root.find("node")


def _parse_part(node: ET.Element) -> CadPart:
    a = _attrs(node)
    return CadPart(
        name=node.get("name", ""),
        density=a.get("Density"),
        volume=a.get("Volume"),
        mass=a.get("Mass"),
        weight=a.get("Weight"),
        surface=a.get("Surface"),
        cog_x=a.get("xCenterOfGravity"),
        cog_y=a.get("yCenterOfGravity"),
        cog_z=a.get("zCenterOfGravity"),
        inertia={k: a[k] for k in _INERTIA_KEYS if k in a},
        attributes=a,
    )


def _attrs(node: ET.Element) -> dict[str, str]:
    return {a.get("key", ""): a.get("value", "") for a in node.findall("attribute")}


def _get_ci(attrs: dict[str, str], name: str) -> str | None:
    """Case-insensitive attribute lookup (key casing varies across VCollab versions)."""
    target = name.lower()
    for key, value in attrs.items():
        if key.lower() == target:
            return value
    return None
