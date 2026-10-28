"""``caxmerge`` — merge multiple CAX files (or a CAX + viewpoint file) into one CAX.

``CaxMerge.exe`` (``CaxMerge <files_to_merge...> <output_file>``, in ``VMoveCAE64``) combines the
data from several input files and writes a single output CAX. Typical uses:

* merge several result CAX files into one multi-model CAX
  (``CaxMerge bracket.cax beam.cax cylinder.cax merged.cax``);
* bake a ``.vpt`` viewpoint file into a CAX
  (``CaxMerge bracket.cax bracket.vpt bracket-with-views.cax``).

This is an action tool (it writes a file), not a metadata reader. Two robustness notes learned
from the real exe:

* ``CaxMerge``'s exit code is an unreliable success signal (it can fail without a clear non-zero
  code, or produce no output), so success is verified by a non-empty output file actually being
  produced — ``produce_output`` writes to a temp file and only promotes it on success.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...paths import PathPolicy
from ...process import run_executable
from ...settings import Settings
from .._output import produce_output


class CaxMergeResult(BaseModel):
    """Outcome of a CAX merge."""

    output_file: str = Field(description="Name of the merged output file.")
    output_path: str = Field(description="Absolute path of the merged output file.")
    size_bytes: int
    inputs: list[str] = Field(description="The input files that were merged, in order.")
    num_inputs: int
    message: str


def caxmerge(
    input_paths: list[str],
    output_path: str,
    *,
    settings: Settings,
    paths: PathPolicy,
) -> CaxMergeResult:
    """Merge ``input_paths`` (CAX/VPT files) into ``output_path``.

    Args:
        input_paths: Two or more files to merge (CAX files, or a CAX plus a ``.vpt`` viewpoint
            file). Order is preserved.
        output_path: Path of the merged CAX to write.

    Raises:
        ValueError: if fewer than two input files are given.
        PathError: if a path is outside the allowed roots.
        FileNotFoundError: if an input file does not exist.
        ProcessError: if the merge runs but produces no output file.
    """
    if len(input_paths) < 2:
        raise ValueError("CaxMerge needs at least two input files to merge.")

    resolved_inputs = [paths.resolve_input(p) for p in input_paths]
    resolved_output = paths.resolve_output(output_path)

    # Guard against destroying an input: an output that resolves to one of the inputs would be
    # unlinked below, deleting already-validated input data. (Path equality is case-insensitive
    # on Windows, so 'A.CAX' vs 'a.cax' is caught too.)
    if resolved_output in resolved_inputs:
        raise ValueError("output_path must differ from every input file.")

    # Resolve the exe BEFORE producing output so a broken install can't damage existing data.
    # The exit code is an unreliable success signal, so produce_output writes to a temp file and
    # only replaces the real output once a non-empty result is verified (a prior output survives).
    exe = settings.resolve_executable("caxmerge")
    produce_output(
        resolved_output,
        lambda out: run_executable(
            exe,
            [*(str(p) for p in resolved_inputs), str(out)],
            timeout=settings.timeout_for("caxmerge"),
            env=settings.subprocess_env(),
        ),
        error_message=(
            "CaxMerge produced no output file. Check that the inputs are valid, compatible "
            "CAX/VPT files."
        ),
    )

    return CaxMergeResult(
        output_file=resolved_output.name,
        output_path=str(resolved_output),
        size_bytes=resolved_output.stat().st_size,
        inputs=list(input_paths),
        num_inputs=len(input_paths),
        message=f"Merged {len(input_paths)} files into {resolved_output.name}.",
    )
