"""``vmovejt`` — convert a Siemens JT file to VCollab CAX format.

``VMoveJTBatch.exe`` (``VMoveJtBatch.exe [option=value] <input_JT_file> <output_CAX_file>``, in
``VMoveJT64``) translates a JT geometry file (``.jt``) into a ``.cax`` file — a sibling of
:mod:`vmovecae` / :mod:`vmovecad` for the JT format.

Note: the ``VMoveJT.bat`` launcher opens the interactive GUI; this tool targets the headless
``VMoveJTBatch.exe`` directly.

Robustness note (verified against the real exe): like the other batch translators, VMoveJTBatch
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


class VMoveJtResult(BaseModel):
    """Outcome of a JT -> CAX conversion."""

    input_file: str = Field(description="The source JT file that was converted.")
    output_file: str = Field(description="Name of the produced CAX file.")
    output_path: str
    size_bytes: int
    translated: bool = Field(description="Whether the exe reported a successful translation.")
    message: str


def vmovejt(
    input_path: str,
    output_path: str = "",
    *,
    settings: Settings,
    paths: PathPolicy,
) -> VMoveJtResult:
    """Convert a Siemens JT file to CAX.

    Args:
        input_path: Source JT file (e.g. 'NX_Speedboat.jt').
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
    exe = settings.resolve_executable("vmovejtbatch")
    result = produce_output(
        resolved_output,
        lambda out: run_executable(
            exe,
            [str(resolved_input), str(out)],
            timeout=settings.timeout_for("vmovejt"),
            env=settings.subprocess_env(),
        ),
        error_message=(
            f"VMoveJTBatch produced no output for {input_name!r}. Check that it is a supported, "
            "readable JT file."
        ),
    )

    translated = _SUCCESS_MARKER in result.stdout.lower()
    message = (
        f"Converted {input_name} to {resolved_output.name}."
        if translated
        else f"Wrote {resolved_output.name} from {input_name}, but the success marker was not "
        "found — the output may be incomplete."
    )
    return VMoveJtResult(
        input_file=input_name,
        output_file=resolved_output.name,
        output_path=str(resolved_output),
        size_bytes=resolved_output.stat().st_size,
        translated=translated,
        message=message,
    )
