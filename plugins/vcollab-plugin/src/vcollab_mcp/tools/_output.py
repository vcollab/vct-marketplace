"""Shared output handling for action tools that write a file via an exit-code-unreliable exe.

VCollab batch executables have inconsistent exit codes on failure — some exit non-zero, some exit 0
with no output — so the return code is not a reliable success signal. The naive guard — delete the
stale output, run, then check it was recreated — works for success detection but **destroys a prior
good output when the run fails**.

:func:`produce_output` closes that gap: the exe writes to a fresh temporary file in the same
directory, and the real output is only replaced (atomically) once a non-empty result is verified.
A previously existing output is therefore never lost to a failed run.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from ..process import ProcessError

T = TypeVar("T")


def produce_output(
    output_path: Path,
    run: Callable[[Path], T],
    *,
    error_message: str,
) -> T:
    """Run ``run(temp_path)`` to produce ``output_path`` safely.

    ``run`` must invoke the executable with ``temp_path`` as its output. On a verified non-empty
    result the temp is atomically moved onto ``output_path`` (replacing any existing file); on
    failure ``output_path`` is left untouched and the temp is cleaned up.

    Returns whatever ``run`` returns (e.g. the ``ProcessResult``, for callers that parse stdout).

    Raises:
        ProcessError: if ``run`` produces no non-empty output file.
    """
    parent = output_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=parent, prefix=".vcollab-tmp-", suffix=output_path.suffix)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        # Give the exe a clean, non-existent path (its normal operating condition).
        tmp_path.unlink()
        result = run(tmp_path)
        if not tmp_path.is_file() or tmp_path.stat().st_size == 0:
            raise ProcessError(error_message)
        os.replace(tmp_path, output_path)  # atomic within the same directory
        return result
    finally:
        # Sweep the temp file and any temp-named siblings an exe may have written (e.g. a sidecar
        # derived from the temp basename) so a failed/partial run leaves no litter in the workspace.
        for leftover in parent.glob(f"{tmp_path.stem}*"):
            leftover.unlink(missing_ok=True)
