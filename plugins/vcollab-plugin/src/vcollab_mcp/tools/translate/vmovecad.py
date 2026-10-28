"""``vmovecad`` — convert a native CAD file to VCollab CAX format.

``VMoveCADBatch.exe`` (``VMoveCAD_Batch.exe [option=value] <input_CAD_file> <output_CAX_file>``,
in ``VMoveCAD64``) translates a CAD geometry file (CATIA ``.CATPart``/``.CATProduct``, Pro/E,
STEP, IGES, ...) into a ``.cax`` file — the CAD counterpart of :mod:`vmovecae`.

Robustness note (verified against the real exe): like the other batch translators, VMoveCADBatch
**exits 0 even on failure** (a missing input raises a boost::filesystem exception and still returns
0), so success is judged by a non-empty output file via :func:`produce_output`, which also keeps a
previously good output intact if the run fails.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...paths import PathPolicy
from ...process import run_executable
from ...settings import Settings
from .._output import produce_output

_SUCCESS_MARKER = "translated successfully"


class VMoveCadResult(BaseModel):
    """Outcome of a CAD -> CAX conversion."""

    input_file: str = Field(description="The source CAD file that was converted.")
    output_file: str = Field(description="Name of the produced CAX file.")
    output_path: str
    size_bytes: int
    translated: bool = Field(description="Whether the exe reported a successful translation.")
    message: str


def vmovecad(
    input_path: str,
    output_path: str = "",
    *,
    settings: Settings,
    paths: PathPolicy,
) -> VMoveCadResult:
    """Convert a native CAD file to CAX.

    Args:
        input_path: Source CAD file (e.g. 'Part2.CATPart', 'model.stp').
        output_path: Output .cax path; defaults to the input path with a .cax extension.

    Raises:
        ValueError: if the output resolves to the input.
        PathError: if a path is outside the allowed roots.
        FileNotFoundError: if the input file does not exist.
        ProcessError: if the conversion produces no (non-empty) output file.
    """
    resolved_input = paths.resolve_input(input_path)
    input_name = resolved_input.name
    if output_path:
        resolved_output = paths.resolve_output(output_path)
    else:
        resolved_output = paths.resolve_output(str(resolved_input.with_suffix(".cax")))
    if resolved_output == resolved_input:
        raise ValueError("Output file must differ from the input file.")

    # Resolve the exe before producing output so a broken install can't damage existing data.
    # produce_output writes to a temp file and only replaces the real output on verified success
    # (the exe exits 0 even on failure, so a non-empty output is the only reliable signal).
    exe = settings.resolve_executable("vmovecadbatch")
    result = produce_output(
        resolved_output,
        lambda out: run_executable(
            exe,
            [str(resolved_input), str(out)],
            timeout=settings.timeout_for("vmovecad"),
            env=settings.subprocess_env(),
        ),
        error_message=(
            f"VMoveCADBatch produced no output for {input_name!r}. Check that it is a supported, "
            "readable CAD file."
        ),
    )

    translated = _SUCCESS_MARKER in result.stdout.lower()
    message = (
        f"Converted {input_name} to {resolved_output.name}."
        if translated
        else f"Wrote {resolved_output.name} from {input_name}, but the success marker was not "
        "found — the output may be incomplete."
    )
    return VMoveCadResult(
        input_file=input_name,
        output_file=resolved_output.name,
        output_path=str(resolved_output),
        size_bytes=resolved_output.stat().st_size,
        translated=translated,
        message=message,
    )
