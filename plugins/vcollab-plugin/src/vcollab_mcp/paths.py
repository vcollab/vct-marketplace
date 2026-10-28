"""Path policy: resolve and optionally bound the file paths the tools operate on.

This replaces the old single-workspace confinement. Tools now take **explicit input/output paths**
(absolute, or relative to the server's working directory). A :class:`PathPolicy` then:

* resolves each path to an absolute path, and
* if **allowed roots** are configured (``VCOLLAB_ALLOWED_ROOTS``), requires every path to live
  under one of them — otherwise it is rejected. With no roots configured, paths are
  **unrestricted** (the trusted-local default).

On the HTTP transport, unrestricted access is only permitted when the operator explicitly opts in
(``VCOLLAB_ALLOW_ANY_PATH``); that is enforced as a startup guard in ``__main__`` so a network
server is never accidentally left wide open.

Existence checks and output-parent creation live here. Crash-safe writes (temp-then-rename) live in
:mod:`vcollab_mcp.tools._output`.
"""

from __future__ import annotations

from pathlib import Path


class PathError(ValueError):
    """Raised for an empty path or one outside the configured allowed roots."""


class PathPolicy:
    """Resolves file paths and enforces optional allowed-root containment."""

    def __init__(self, allowed_roots: list[Path | str] | None = None) -> None:
        # None / empty => unrestricted. Otherwise, resolved root directories.
        self._roots: list[Path] | None = (
            [Path(r).expanduser().resolve() for r in allowed_roots] if allowed_roots else None
        )

    @property
    def restricted(self) -> bool:
        """True if file access is bounded to allowed roots."""
        return self._roots is not None

    @property
    def roots(self) -> list[Path]:
        return list(self._roots) if self._roots is not None else []

    def describe(self) -> str:
        """Human-readable summary for diagnostics."""
        if not self._roots:
            return "unrestricted (any path)"
        return "allowed roots: " + "; ".join(str(r) for r in self._roots)

    def resolve_path(self, path: str) -> Path:
        """Resolve any path and enforce the policy, without touching the filesystem.

        Used to vet paths that a job file *references* (the exe reads/writes them later), so a
        read-only check never creates directories as a side effect.

        Raises:
            PathError: if the path is empty or outside the allowed roots.
        """
        if not path or not str(path).strip():
            raise PathError("Empty path.")
        resolved = Path(path).expanduser().resolve()
        if self._roots is not None and not any(
            resolved == root or root in resolved.parents for root in self._roots
        ):
            raise PathError(f"Path is outside the allowed roots ({self.describe()}): {path}")
        return resolved

    def resolve_input(self, path: str) -> Path:
        """Resolve an existing input file, enforcing the policy.

        Raises:
            PathError: if the path is empty or outside the allowed roots.
            FileNotFoundError: if the file does not exist.
        """
        resolved = self.resolve_path(path)
        if not resolved.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        return resolved

    def resolve_output(self, path: str) -> Path:
        """Resolve a (possibly not-yet-existing) output path, enforcing the policy.

        Creates the parent directory if needed.

        Raises:
            PathError: if the path is empty or outside the allowed roots.
            OSError: if the parent directory cannot be created.
        """
        resolved = self.resolve_path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved
