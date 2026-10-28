"""``vmovecaevalidate`` — validate a VMoveCAE command file without translating (pre-flight check).

``VMoveCAEValidate.exe`` (``VMoveCAEValidate <input_file>``, in ``VMoveCAE64``) checks a
:mod:`vmovecaesubmit` command file: it confirms the required sections are present, identifies each
declared file's type/content, and warns about referenced files that are missing — **without**
running a translation and **without** producing a ``.cax``. It is the cheap dry-run/lint to run
before :mod:`vmovecaesubmit` on a hand-authored or complex command file.

Verified against the real exe:

* the verdict is printed to stderr ("Validation successful." / "Validation failed."), ANSI-wrapped;
* the exit code is **always 0**, so the verdict must be read from the text, not the return code;
* a missing referenced input is a WARNING, not a failure (the file can still validate "successful");
* structural problems (e.g. no mandatory FILES section) yield "Validation failed.";
* an invalid command file is a normal result here (``valid=False``), not an error.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ...paths import PathError, PathPolicy
from ...process import run_executable
from ...settings import Settings
from .._command_file import check_referenced_paths

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


class VMoveCaeValidateResult(BaseModel):
    """Outcome of validating a VMoveCAE command file."""

    command_file: str = Field(description="The command file that was validated.")
    valid: bool = Field(description="True if the exe reported 'Validation successful.'")
    warnings: list[str] = Field(
        default_factory=list,
        description="Advisory messages (e.g. a referenced file that does not exist).",
    )
    report: str = Field(description="The full validation output (ANSI codes stripped).")


def vmovecaevalidate(
    command_path: str,
    *,
    settings: Settings,
    paths: PathPolicy,
) -> VMoveCaeValidateResult:
    """Validate a prepared VMoveCAE command file (no translation).

    Args:
        command_path: Path to the ``.txt`` command file (e.g. 'inputs.txt').

    Raises:
        FileNotFoundError: if the command file does not exist.
        ProcessError: if the validator executable cannot be run.
    """
    resolved = paths.resolve_input(command_path)
    command_name = resolved.name
    try:
        check_referenced_paths(
            resolved.read_text(encoding="utf-8", errors="replace"), paths, resolved.parent
        )
    except PathError as exc:
        # validate is read-only and never runs the exe on an out-of-policy reference, so report it
        # as an invalid command file (valid=False) rather than erroring — matching the validator
        # contract. (vmovecaesubmit, which WRITES output, hard-blocks instead.)
        return VMoveCaeValidateResult(
            command_file=command_name,
            valid=False,
            warnings=[str(exc)],
            report=f"Command file references a path outside the allowed roots: {exc}",
        )

    exe = settings.resolve_executable("vmovecaevalidate")
    result = run_executable(
        exe,
        [str(resolved)],
        timeout=settings.timeout_for("vmovecaevalidate"),
        cwd=resolved.parent,  # so relative names in the command file resolve next to it
        env=settings.subprocess_env(),
    )

    # VMoveCAEValidate prints its verdict to stderr (not stdout); read both to be safe.
    combined = f"{result.stdout}\n{result.stderr}".strip()
    clean = _ANSI_RE.sub("", combined)
    lower = clean.lower()
    # Exit code is always 0; the verdict is the printed text.
    valid = "validation successful" in lower and "validation failed" not in lower
    warnings = [
        line.strip()
        for line in clean.splitlines()
        if "doesn't exist" in line.lower() or "warning" in line.lower()
    ]
    message = "Command file is valid." if valid else "Command file is INVALID."
    return VMoveCaeValidateResult(
        command_file=command_name,
        valid=valid,
        warnings=warnings,
        report=clean.strip() or message,
    )
