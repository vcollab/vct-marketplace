"""``vmovex`` — convert a CFD / multi-solver file to VCollab CAX via VMoveX.

``VMoveXSubmit.exe`` (in ``VMoveX``) is VCollab's broad "X" translator covering CFD and other
formats — CGNS, EnSight, Fluent, OpenFOAM, Converge, VTK, and also ``.odb``/``.rst``/``.rth``/
``d3plot``/``.cff``/``.aedt``/``.cst``. Unlike the other batch translators it uses **flag-based**
arguments rather than positionals::

    VMoveXSubmit.exe -i <input> [-r <results>] -o <output_cax> [--odb-version <year>]

Notes (verified against the real exe):

* the ``VMoveXSubmit.bat`` launcher uses ``start /b`` (detached) and prepends ``VMoveX``/``bin`` to
  PATH; we invoke the ``.exe`` directly — it loads its DLLs from its own folder, so no PATH change
  is needed (``VCOLLAB_DIR`` is still propagated via ``subprocess_env``);
* its exit code on failure is unreliable (a bad input raises a Python traceback and exits non-zero,
  but it may also exit 0 with no output), so success is judged by a non-empty output file via
  :func:`produce_output`;
* progress lines are wrapped in ANSI color codes, which are stripped before reading the marker.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ...paths import PathPolicy
from ...process import run_executable
from ...settings import Settings
from .._output import produce_output

# Strip ANSI CSI sequences (not just SGR 'm' — also erase-line/cursor codes) before reading text.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


class VMoveXResult(BaseModel):
    """Outcome of a VMoveX (CFD / multi-solver) conversion."""

    input_file: str = Field(description="The source file that was converted.")
    output_file: str = Field(description="Name of the produced CAX file.")
    output_path: str
    size_bytes: int
    results_file: str | None = Field(default=None, description="Separate results file, if used.")
    translated: bool = Field(description="Whether the exe reported a completed translation.")
    message: str


def vmovex(
    input_path: str,
    output_path: str = "",
    *,
    results_path: str = "",
    odb_version: str = "",
    settings: Settings,
    paths: PathPolicy,
) -> VMoveXResult:
    """Convert a CFD/multi-solver file to CAX using VMoveX.

    Args:
        input_path: Source file (e.g. 'flow.cgns', 'case.foam', 'st1.vtk', a Fluent '.cas',
            or an '.odb'/'.rst'/'d3plot').
        output_path: Output .cax path; defaults to the input path with a .cax extension.
        results_path: Optional separate results file (e.g. a Fluent '.dat.h5' / CFX results).
        odb_version: Abaqus ODB reader version as a year (e.g. '2024'), for .odb inputs.

    Raises:
        ValueError: if odb_version is malformed, or the output resolves to the input/results file.
        PathError: if a path is outside the allowed roots.
        FileNotFoundError: if the input (or results) file does not exist.
        ProcessError: if the conversion produces no (non-empty) output file.
    """
    if odb_version and not re.fullmatch(r"\d{4}", odb_version):
        raise ValueError("odb_version must be a 4-digit year (e.g. '2024').")

    resolved_input = paths.resolve_input(input_path)
    input_name = resolved_input.name
    if output_path:
        resolved_output = paths.resolve_output(output_path)
    else:
        resolved_output = paths.resolve_output(str(resolved_input.with_suffix(".cax")))
    if resolved_output == resolved_input:
        raise ValueError("Output file must differ from the input file.")
    resolved_results = paths.resolve_input(results_path) if results_path else None
    if resolved_results is not None and resolved_output == resolved_results:
        raise ValueError("Output file must differ from the results file.")

    # Resolve the exe before producing output so a broken install can't damage existing data.
    exe = settings.resolve_executable("vmovexsubmit")

    def _run(out):
        args = ["-i", str(resolved_input), "-o", str(out)]
        if resolved_results is not None:
            args += ["-r", str(resolved_results)]
        if odb_version:
            args += ["--odb-version", odb_version]
        return run_executable(
            exe, args, timeout=settings.timeout_for("vmovex"), env=settings.subprocess_env()
        )

    result = produce_output(
        resolved_output,
        _run,
        error_message=(
            f"VMoveX produced no output for {input_name!r}. Check that it is a supported, readable "
            "input (CFD/CAE) file and that any results file matches."
        ),
    )

    clean = _ANSI_RE.sub("", result.stdout).lower()
    # Match the completion phrase on a SINGLE line (not the two words scattered across the log).
    translated = any(
        re.search(r"translation\b.*\bcompleted", line) for line in clean.splitlines()
    )
    message = (
        f"Converted {input_name} to {resolved_output.name}."
        if translated
        else f"Wrote {resolved_output.name} from {input_name}, but the completion marker was not "
        "found — the output may be incomplete."
    )
    return VMoveXResult(
        input_file=input_name,
        output_file=resolved_output.name,
        output_path=str(resolved_output),
        size_bytes=resolved_output.stat().st_size,
        results_file=resolved_results.name if resolved_results else None,
        translated=translated,
        message=message,
    )
