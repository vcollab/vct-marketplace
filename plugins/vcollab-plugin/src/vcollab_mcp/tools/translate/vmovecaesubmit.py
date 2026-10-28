"""``vmovecaesubmit`` — run a VMoveCAE *command file* (declarative job spec) to produce CAX.

``VMoveCAESubmit.exe`` (``VMoveCAESubmit <input_file>``, in ``VMoveCAE64``) executes a prepared
``.txt`` command file describing a translation job, using the same engine as ``VMoveCAEBatch``
(the :mod:`vmovecae` tool) but driven declaratively instead of by direct CLI flags.

Verified against the real exe:

* the single argument is the command file; all the input/output files are named *inside* it;
* it is run with the command file's own folder as the working directory, so relative file names in
  the command file resolve next to it; every referenced path is checked against the allowed-roots
  policy — a command file referencing a path outside the allowed roots is rejected before the exe
  runs;
* unlike most VCollab batch tools, the exit code is reliable here — 0 on success, non-zero (9) on
  a bad/invalid command file or a missing referenced input — failures surface as ``ProcessError``;
* on success it prints "Translated Successfully." Outputs (the ``.cax``, plus any ``.his``/``.log``
  the command file declares) are detected by diffing the workspace before/after the run.

The output path is chosen by the command file (not this tool), so :func:`produce_output` is not
used here.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ...paths import PathPolicy
from ...process import run_executable
from ...settings import Settings
from .._command_file import check_referenced_paths

_SUCCESS_MARKER = "translated successfully"
_OUTPUT_SUFFIXES = (".cax", ".his", ".log")


class VMoveCaeSubmitResult(BaseModel):
    """Outcome of a VMoveCAESubmit command-file run."""

    command_file: str = Field(description="The command file that was executed.")
    outputs: list[str] = Field(
        default_factory=list,
        description="Files (.cax/.his/.log) created or updated next to the command file.",
    )
    num_outputs: int = 0
    translated: bool = Field(description="Whether the exe reported a successful translation.")
    message: str


def vmovecaesubmit(
    command_path: str,
    *,
    settings: Settings,
    paths: PathPolicy,
) -> VMoveCaeSubmitResult:
    """Execute a prepared VMoveCAE command file.

    Args:
        command_path: Path to the ``.txt`` command file (e.g. 'inputs.txt'). Files it references
            with relative names are resolved next to it.

    Raises:
        FileNotFoundError: if the command file does not exist.
        PathError: if the command file references a path outside the allowed roots.
        ProcessError: if the command file is invalid or a referenced input is missing (the exe
            exits non-zero), or it otherwise fails.
    """
    resolved = paths.resolve_input(command_path)
    command_name = resolved.name
    # Run in the command file's own folder so its relative file names resolve next to it; detect
    # outputs by diffing that folder before/after.
    work_dir = resolved.parent
    # The command file's PATH is checked, but its CONTENTS are LLM/user-authored. Validate every
    # file it references (inputs, output, FOLDER) against the policy so a job spec can't read/write
    # outside the configured allowed roots.
    check_referenced_paths(
        resolved.read_text(encoding="utf-8", errors="replace"), paths, work_dir
    )
    before = _snapshot(work_dir)
    exe = settings.resolve_executable("vmovecaesubmit")
    result = run_executable(
        exe,
        [str(resolved)],
        timeout=settings.timeout_for("vmovecaesubmit"),
        cwd=work_dir,
        env=settings.subprocess_env(),
    )
    after = _snapshot(work_dir)

    outputs = sorted(name for name, sig in after.items() if before.get(name) != sig)
    translated = _SUCCESS_MARKER in result.stdout.lower()
    if outputs and translated:
        message = f"Translated {command_name}; produced/updated: {', '.join(outputs)}."
    elif outputs:
        message = (
            f"Ran {command_name}; produced/updated {', '.join(outputs)}, but the completion "
            "marker was not found -- the output may be incomplete."
        )
    else:
        message = (
            f"Ran {command_name} but produced no .cax/.his/.log next to it -- the command file "
            "may declare no output, or the run did not complete."
        )
    return VMoveCaeSubmitResult(
        command_file=command_name,
        outputs=outputs,
        num_outputs=len(outputs),
        translated=translated,
        message=message,
    )


def _snapshot(work_dir: Path) -> dict[str, tuple[int, int]]:
    """Map output-type files (recursively) to their (size, mtime_ns) signature."""
    snap: dict[str, tuple[int, int]] = {}
    for p in work_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in _OUTPUT_SUFFIXES:
            st = p.stat()
            snap[str(p.relative_to(work_dir))] = (st.st_size, st.st_mtime_ns)
    return snap
