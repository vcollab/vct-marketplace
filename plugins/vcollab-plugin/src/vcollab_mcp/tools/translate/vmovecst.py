"""``vmovecst`` — convert a CST (electromagnetics) result to VCollab CAX.

``VMoveCST.exe`` (``VMoveCST.exe <gex_file_path> [cax_file_path]``, in ``VMoveCST64``) translates a
CST Studio result into a ``.cax`` file.

Two things to know (verified against the real exe):

* **Folder-coupled inputs.** The ``.gex`` references many sibling result files in the same folder
  (``.m3t``/``.rex``/``.slim``/``.tet`` plus ``DS/``, ``IBOFlow/`` subfolders). The whole CST
  ``Result`` folder must be staged into the workspace alongside the ``.gex`` — uploading only the
  ``.gex`` will fail or produce an incomplete CAX. Only tetrahedral-mesh data is exported.
* Its exit code on failure is unreliable (a missing input exits non-zero, but it may also exit 0
  with no output), so success is judged by a non-empty output file via :func:`produce_output`. A
  CST translation license is required at run time.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...paths import PathPolicy
from ...process import run_executable
from ...settings import Settings
from .._output import produce_output

_SUCCESS_MARKER = "translation completed"


class VMoveCstResult(BaseModel):
    """Outcome of a CST -> CAX conversion."""

    input_file: str = Field(description="The source .gex file that was converted.")
    output_file: str = Field(description="Name of the produced CAX file.")
    output_path: str
    size_bytes: int
    translated: bool = Field(description="Whether the exe reported a completed translation.")
    message: str


def vmovecst(
    input_path: str,
    output_path: str = "",
    *,
    settings: Settings,
    paths: PathPolicy,
) -> VMoveCstResult:
    """Convert a CST ``.gex`` result to CAX.

    The ``.gex`` and all its sibling result files must sit together in the same folder.

    Args:
        input_path: Source ``.gex`` file (e.g. 'model.gex').
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
    # (the exit code is unreliable, so a non-empty output is the only dependable success signal).
    exe = settings.resolve_executable("vmovecst")
    result = produce_output(
        resolved_output,
        lambda out: run_executable(
            exe,
            [str(resolved_input), str(out)],
            timeout=settings.timeout_for("vmovecst"),
            env=settings.subprocess_env(),
        ),
        error_message=(
            f"VMoveCST produced no output for {input_name!r}. Check that it is a readable .gex "
            "with its sibling result files alongside it, and that a CST license is available."
        ),
    )

    translated = _SUCCESS_MARKER in result.stdout.lower()
    message = (
        f"Converted {input_name} to {resolved_output.name}."
        if translated
        else f"Wrote {resolved_output.name} from {input_name}, but the completion marker was not "
        "found — the output may be incomplete."
    )
    return VMoveCstResult(
        input_file=input_name,
        output_file=resolved_output.name,
        output_path=str(resolved_output),
        size_bytes=resolved_output.stat().st_size,
        translated=translated,
        message=message,
    )
