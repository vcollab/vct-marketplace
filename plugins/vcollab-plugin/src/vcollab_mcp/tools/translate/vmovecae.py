"""``vmovecae`` — convert a native CAE file to VCollab CAX format.

``VMoveCAEBatch.exe`` (``VMoveCAEBatch [options] <model_file> [results_file] <cax_file>``, in
``VMoveCAE64``) translates a solver result file (Ansys ``.rst``, Nastran ``.op2``, LS-DYNA
``d3plot``, Abaqus ``.odb``, Fluent ``.cas``/``.dat``, ...) into a ``.cax`` file. It is the ingest
gateway for the rest of the toolchain.

A native solver file can be translated whole, or trimmed/augmented with the options below (all
straight from the VMoveCAE batch reference). Comma-separated list options accept Python lists here
and are joined back into the ``--flag=a, b`` form the exe expects:

* result selection — ``--results`` / ``--filter-results`` (and the nodal/elemental/section
  controls ``--nodal-results``, ``--element-results``, ``--default-element-results``,
  ``--sections``);
* part selection — ``--parts`` / ``--filter-parts`` / ``--part-ids`` / ``--filter-part-ids``,
  plus ``--part-grouping`` for how elements are grouped into parts;
* instance (load-step/frame) selection — ``--instances`` / ``--filter-instances``;
* embedded geometry features — ``--cut-sections``, ``--iso-surfaces``, ``--flow-lines``;
* load/translation toggles — ``--enable-mid-nodes``, ``--enable-input-files-caching``,
  ``--enable-odb-fast-load``, ``--enable-odb-load-zero-frames``,
  ``--no-averaging-across-materials``;
* set sources — ``--abaqus-input-file`` (an ``.inp`` for element/face sets) and
  ``--ansys-input-commands`` (a ``ds.dat`` for named selections);
* format override — ``--model-file-format`` (and ``--odb-version`` for the Abaqus ODB reader).

A separate ``results_file`` (e.g. a Fluent ``.dat`` paired with a ``.cas``) is passed positionally
between the model file and the output, matching the exe's argument order.

Robustness note (verified against the real exe): VMoveCAEBatch's exit code on failure is unreliable
(a missing input exits non-zero, but it can also exit 0 with no output), so success is judged by a
non-empty output file, not the return code. Conversion goes through ``produce_output`` (write to a
temp file, then atomically replace the target only on success) so a failed run never destroys a
previously good output.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ...paths import PathPolicy
from ...process import run_executable
from ...settings import Settings
from .._output import produce_output

_COUNT_RE = re.compile(r"Number of (Parts|Results|Instances):\s*(\d+)")
_SUCCESS_MARKER = "Translated Successfully"

# Closed enums the exe documents — validated up front so a typo fails with a clear message rather
# than silently producing a default grouping / dropping a section.
_PART_GROUPINGS = {
    "default",
    "property-id",
    "material-id",
    "element-set",
    "face-set",
    "element-and-face-sets",
    "element-type-number",
    "no-parts",
    "ansa-parts",
    "hypermesh-components",
}
_SECTION_VALUES = {"top", "bottom", "mid", "maximum", "minimum", "average"}


class VMoveCaeResult(BaseModel):
    """Outcome of a CAE -> CAX conversion."""

    input_file: str = Field(description="The source CAE file that was converted.")
    output_file: str = Field(description="Name of the produced CAX file.")
    output_path: str
    size_bytes: int
    num_parts: int | None = Field(default=None, description="Parts in the source, as reported.")
    num_results: int | None = Field(
        default=None, description="Results in the source, as reported."
    )
    num_instances: int | None = Field(
        default=None, description="Instances in the source, as reported."
    )
    translated: bool = Field(description="Whether the exe reported a successful translation.")
    message: str


def vmovecae(
    input_path: str,
    output_path: str = "",
    *,
    results_path: str = "",
    results: list[str] | None = None,
    filter_results: list[str] | None = None,
    nodal_results: list[str] | None = None,
    element_results: list[str] | None = None,
    default_element_results: bool = False,
    sections: list[str] | None = None,
    parts: list[str] | None = None,
    filter_parts: list[str] | None = None,
    part_ids: list[str] | None = None,
    filter_part_ids: list[str] | None = None,
    instances: list[str] | None = None,
    filter_instances: list[str] | None = None,
    cut_sections: list[str] | None = None,
    iso_surfaces: list[str] | None = None,
    flow_lines: list[str] | None = None,
    part_grouping: str = "",
    model_file_format: str = "",
    enable_mid_nodes: bool = False,
    enable_input_files_caching: bool = False,
    enable_odb_fast_load: bool = False,
    enable_odb_load_zero_frames: bool = False,
    no_averaging_across_materials: bool = False,
    abaqus_input_file: str = "",
    ansys_input_commands: str = "",
    odb_version: str = "",
    settings: Settings,
    paths: PathPolicy,
) -> VMoveCaeResult:
    """Convert a native CAE file to CAX.

    Args:
        input_path: The source CAE file (e.g. 'beam.rst', 'model.op2', 'd3plot').
        output_path: Output .cax path; defaults to the input path with a '.cax' extension.
        results_path: Optional separate results file (e.g. a Fluent '.dat' paired with a '.cas').
        results: Only translate these result names (others skipped).
        filter_results: Exclude these result names (ignored if ``results`` is given).
        nodal_results: Force these results to be written as nodal values.
        element_results: Force these results to be written as elemental values.
        default_element_results: Write all element/element-location results as elemental.
        sections: Shell sections to export (Top, Bottom, Mid, Maximum, Minimum, Average).
        parts: Only translate these part names.
        filter_parts: Exclude these part names (ignored if ``parts``/``part_ids`` is given).
        part_ids: Only translate parts with these IDs (ranges allowed, e.g. ['1', '30-35']).
        filter_part_ids: Exclude parts with these IDs (ignored if ``parts``/``part_ids`` is given).
        instances: Only translate these instances/ranges (e.g. ['1-6', '8-12']).
        filter_instances: Exclude these instances/ranges.
        cut_sections: Plane equations 'AX+BY+CZ=D' to embed as cut-sections.
        iso_surfaces: Result names (optionally with a derived type) to embed as ISO-surfaces.
        flow_lines: Flow-line specs '[result, seed_part_or_point, n_lines]' (CFD).
        part_grouping: How elements are grouped into parts (one of ``_PART_GROUPINGS``).
        model_file_format: Override the auto-detected input format (e.g. 'nastran_bdf').
        enable_mid_nodes: Include mid-nodes of higher-order elements.
        enable_input_files_caching: Cache remote inputs locally before processing.
        enable_odb_fast_load: ODB fast load (assume same result list per step).
        enable_odb_load_zero_frames: Include frame 0 (initial conditions) from ODB files.
        no_averaging_across_materials: Do not average nodal values across material interfaces.
        abaqus_input_file: An Abaqus '.inp' to read element/face sets from (for an .odb input).
        ansys_input_commands: An Ansys 'ds.dat' to read named element selections from.
        odb_version: Abaqus ODB reader version (a year, e.g. '2024') for .odb inputs.

    Raises:
        ValueError: if the output resolves to an input, or an enum argument is invalid.
        PathError: if a path is outside the allowed roots.
        FileNotFoundError: if an input file does not exist.
        ProcessError: if the conversion produces no (non-empty) output file.
    """
    if odb_version and not re.fullmatch(r"\d{4}", odb_version):
        raise ValueError("odb_version must be a 4-digit year (e.g. '2024').")
    if part_grouping and part_grouping.lower() not in _PART_GROUPINGS:
        raise ValueError(
            f"Invalid part_grouping {part_grouping!r}. Choose one of: "
            f"{', '.join(sorted(_PART_GROUPINGS))}."
        )
    if sections:
        bad = [s for s in sections if s.strip().lower() not in _SECTION_VALUES]
        if bad:
            raise ValueError(
                f"Invalid section(s) {', '.join(bad)}. Choose from: Top, Bottom, Mid, "
                "Maximum, Minimum, Average."
            )

    resolved_input = paths.resolve_input(input_path)
    input_name = resolved_input.name
    resolved_results = paths.resolve_input(results_path) if results_path else None
    # Set-source files are referenced inputs: resolve + policy-check (and confirm they exist).
    resolved_abaqus_inp = paths.resolve_input(abaqus_input_file) if abaqus_input_file else None
    resolved_ansys_cmds = (
        paths.resolve_input(ansys_input_commands) if ansys_input_commands else None
    )

    # Default output sits next to the input (with_suffix keeps the input's directory).
    if output_path:
        resolved_output = paths.resolve_output(output_path)
    else:
        resolved_output = paths.resolve_output(str(resolved_input.with_suffix(".cax")))
    if resolved_output in (resolved_input, resolved_results):
        raise ValueError("Output file must differ from the input/results files.")

    options: list[str] = []
    # Comma-joined list flags (the exe takes "--flag=a, b"; one argv entry, no shell quoting).
    for flag, values in (
        ("results", results),
        ("filter-results", filter_results),
        ("nodal-results", nodal_results),
        ("element-results", element_results),
        ("sections", sections),
        ("parts", parts),
        ("filter-parts", filter_parts),
        ("part-ids", part_ids),
        ("filter-part-ids", filter_part_ids),
        ("instances", instances),
        ("filter-instances", filter_instances),
        ("cut-sections", cut_sections),
        ("iso-surfaces", iso_surfaces),
        ("flow-lines", flow_lines),
    ):
        if values:
            options.append(f"--{flag}={', '.join(values)}")
    # Bare boolean toggles.
    for flag, enabled in (
        ("default-element-results", default_element_results),
        ("enable-mid-nodes", enable_mid_nodes),
        ("enable-input-files-caching", enable_input_files_caching),
        ("enable-odb-fast-load", enable_odb_fast_load),
        ("enable-odb-load-zero-frames", enable_odb_load_zero_frames),
        ("no-averaging-across-materials", no_averaging_across_materials),
    ):
        if enabled:
            options.append(f"--{flag}")
    # Scalar/value flags.
    if part_grouping:
        options.append(f"--part-grouping={part_grouping}")
    if model_file_format:
        options.append(f"--model-file-format={model_file_format}")
    if odb_version:
        options.append(f"--odb-version={odb_version}")
    if resolved_abaqus_inp is not None:
        options.append(f"--abaqus-input-file={resolved_abaqus_inp}")
    if resolved_ansys_cmds is not None:
        options.append(f"--ansys-input-commands={resolved_ansys_cmds}")

    # Positional tail: <model_file> [results_file] <cax_file>. The results file (if any) sits
    # between the model and the output, matching the exe's argument order.
    middle = [str(resolved_results)] if resolved_results is not None else []

    # Resolve the exe BEFORE producing output so a broken install can't damage existing data.
    # produce_output writes to a temp file and only replaces the real output on verified success
    # (the exit code is unreliable, so a non-empty output is the only dependable success signal).
    exe = settings.resolve_executable("vmovecaebatch")
    result = produce_output(
        resolved_output,
        lambda out: run_executable(
            exe,
            [*options, str(resolved_input), *middle, str(out)],
            timeout=settings.timeout_for("vmovecae"),
            env=settings.subprocess_env(),
        ),
        error_message=(
            f"VMoveCAEBatch produced no output for {input_name!r}. Check that it is a supported, "
            "readable CAE file (and that any filter names match)."
        ),
    )

    counts = {key: int(val) for key, val in _COUNT_RE.findall(result.stdout)}
    translated = _SUCCESS_MARKER in result.stdout
    message = (
        f"Converted {input_name} to {resolved_output.name}."
        if translated
        else f"Wrote {resolved_output.name} from {input_name}, but the success marker was not "
        "found — the output may be incomplete."
    )
    return VMoveCaeResult(
        input_file=input_name,
        output_file=resolved_output.name,
        output_path=str(resolved_output),
        size_bytes=resolved_output.stat().st_size,
        num_parts=counts.get("Parts"),
        num_results=counts.get("Results"),
        num_instances=counts.get("Instances"),
        translated=translated,
        message=message,
    )
