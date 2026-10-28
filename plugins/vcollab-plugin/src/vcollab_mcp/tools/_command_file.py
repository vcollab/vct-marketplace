"""Shared helpers for the VMoveCAE command-file tools (``vmovecaesubmit``, ``vmovecaevalidate``).

Both consume the same ``.txt`` command-file format, so the path-policy scan lives here to keep
them consistent.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..paths import PathPolicy

_FOLDER_RE = re.compile(r'(?i)\bFOLDER\s*=\s*"?([^,"]+)')


def check_referenced_paths(command_text: str, policy: PathPolicy, base_dir: Path) -> None:
    """Validate the file paths a command file references against the path policy.

    The command file's own path is trusted (the caller resolved it), but its CONTENTS are
    LLM/user-authored. This checks the leading file token of each ``-`` data line and any
    ``FOLDER=`` value against ``policy``. Relative values are resolved against ``base_dir`` (the
    command file's folder, which is also the run's working directory), exactly as the exe will see
    them, then policy-checked via :meth:`PathPolicy.resolve_path` — which raises ``PathError`` for
    any path outside the configured allowed roots and, unlike ``resolve_output``, creates nothing
    (``vmovecaevalidate`` is a read-only dry run). When the policy is unrestricted, all pass.
    """
    for raw in command_text.splitlines():
        line = raw.strip()
        candidates: list[str] = []
        if line.startswith("-"):
            candidates.append(line[1:].split(",", 1)[0].strip().strip('"'))
        folder = _FOLDER_RE.search(line)
        if folder:
            candidates.append(folder.group(1).strip())
        for value in candidates:
            if not value:
                continue
            p = Path(value)
            target = str(p if p.is_absolute() else (base_dir / value))
            policy.resolve_path(target)  # raises PathError if outside the allowed roots
