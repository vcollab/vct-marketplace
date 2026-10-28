"""Safe subprocess execution for VCollab command-line executables.

The two non-obvious requirements, learned from the POC, are preserved here:

* ``stdin=DEVNULL`` — VCollab tools (notably ``VCollabPro.exe``) inherit and block on the
  MCP server's stdio pipes otherwise, hanging the whole server.
* ``CREATE_NO_WINDOW`` — keeps the GUI executables from flashing console windows.

All failure modes are normalized to :class:`ProcessError` (or its subclasses) so callers
never have to handle raw ``subprocess`` exceptions, and nothing leaks an unhandled traceback
across the MCP boundary.
"""

from __future__ import annotations

import contextlib
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Outcome of a completed subprocess."""

    returncode: int
    stdout: str
    stderr: str


class ProcessError(RuntimeError):
    """Base class for VCollab subprocess failures."""


class ProcessExitError(ProcessError):
    """Raised when a VCollab executable exits with a non-zero status."""

    def __init__(self, returncode: int, stderr: str, stdout: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout
        detail = stderr.strip() or stdout.strip() or "(no output)"
        super().__init__(f"VCollab process exited with code {returncode}: {detail}")


class ProcessTimeout(ProcessError):
    """Raised when a VCollab executable exceeds its timeout and is terminated."""

    def __init__(self, exe_name: str, timeout: int) -> None:
        self.exe_name = exe_name
        self.timeout = timeout
        super().__init__(f"{exe_name} did not finish within {timeout}s and was terminated.")


class ProcessLaunchError(ProcessError):
    """Raised when the executable cannot be launched at all (e.g. OS-level spawn failure)."""


def run_executable(
    exe: Path,
    args: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    kill_tree: bool = False,
) -> ProcessResult:
    """Run ``exe`` with ``args`` and return its captured output.

    Args:
        exe: Absolute path to the executable.
        args: Arguments passed after the executable.
        timeout: Hard timeout in seconds.
        cwd: Working directory; defaults to the system temp dir to avoid polluting
            the workspace with stray trace/log files.
        env: Full environment for the child. ``None`` inherits the parent's. Pass a complete
            mapping (not a partial overlay) — VCollab tools need their installer-set vars
            (notably ``VCOLLAB_DIR``), so callers build this from ``Settings.subprocess_env()``.
        kill_tree: On timeout, kill the whole process *tree*, not just the direct child. Required
            for ``VCollabPro.exe`` batch mode, which can spawn helper processes that would
            otherwise be orphaned and keep running after a timeout.

    Raises:
        ProcessTimeout: if it runs longer than ``timeout``.
        ProcessExitError: if the process exits non-zero.
        ProcessLaunchError: if the process cannot be spawned.
    """
    cwd_str = str(cwd) if cwd is not None else tempfile.gettempdir()
    env_dict = dict(env) if env is not None else None
    try:
        with subprocess.Popen(
            [str(exe), *args],
            cwd=cwd_str,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=env_dict,
            creationflags=_CREATE_NO_WINDOW,
        ) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                _terminate(proc, kill_tree=kill_tree)
                raise ProcessTimeout(exe.name, timeout) from exc
            returncode = proc.returncode
    except OSError as exc:
        raise ProcessLaunchError(f"Could not launch {exe.name}: {exc}") from exc

    if returncode != 0:
        raise ProcessExitError(returncode, stderr, stdout)
    return ProcessResult(returncode=returncode, stdout=stdout, stderr=stderr)


def _terminate(proc: subprocess.Popen, *, kill_tree: bool) -> None:
    """Stop a timed-out process. With ``kill_tree`` (Windows), reap the whole child tree."""
    killed_tree = False
    if kill_tree and _CREATE_NO_WINDOW:  # _CREATE_NO_WINDOW is non-zero only on Windows
        # taskkill /T kills the process and all descendants; /F forces it.
        try:
            tk = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=15,
                creationflags=_CREATE_NO_WINDOW,
            )
            # taskkill returns non-zero (without raising) when it can't kill the tree — e.g.
            # blocked by policy. Treat that as failure and fall back to the direct-child kill.
            killed_tree = tk.returncode == 0
        except (OSError, subprocess.SubprocessError):
            killed_tree = False
    if not killed_tree:
        proc.kill()  # fall back to (or, off-Windows, only) killing the direct child
    with contextlib.suppress(subprocess.SubprocessError):
        proc.wait(timeout=10)  # reap so the handle/pipes are released
