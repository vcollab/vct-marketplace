"""Health/diagnostics shared by the ``vcollab_health`` tool and the ``doctor`` CLI command."""

from __future__ import annotations

from pydantic import BaseModel, Field

from . import __version__
from .settings import Settings


class ExecutableStatus(BaseModel):
    """Resolution status of a single VCollab executable."""

    name: str
    path: str | None = Field(default=None, description="Absolute path if found, else null.")
    found: bool


class HealthReport(BaseModel):
    """Server + VCollab installation status."""

    server_version: str
    vcollab_dir: str | None = Field(default=None, description="Resolved VCollab install root.")
    vcollab_detected: bool
    file_access: str = Field(
        description="File-path policy: 'unrestricted (any path)' or the configured allowed roots."
    )
    executables: list[ExecutableStatus]
    timeouts: dict[str, int]
    log_file: str | None = None
    all_required_present: bool = Field(
        description="True if every configured executable resolved successfully."
    )


def build_health_report(
    settings: Settings,
    *,
    log_file: str | None = None,
) -> HealthReport:
    """Probe the configured VCollab installation and return a structured status report.

    Never raises for a missing install — that is exactly the condition it reports.
    """
    executables: list[ExecutableStatus] = []
    all_present = True
    for name in settings.executables:
        try:
            path = settings.resolve_executable(name)
            executables.append(ExecutableStatus(name=name, path=str(path), found=True))
        except (OSError, ValueError, KeyError, RuntimeError):
            # Any resolution failure (missing/unknown/malformed path) is reported, not raised.
            executables.append(ExecutableStatus(name=name, path=None, found=False))
            all_present = False

    return HealthReport(
        server_version=__version__,
        vcollab_dir=str(settings.vcollab_dir) if settings.vcollab_dir else None,
        vcollab_detected=settings.vcollab_dir is not None,
        file_access=settings.path_policy().describe(),
        executables=executables,
        timeouts=settings.all_timeouts(),
        log_file=log_file,
        all_required_present=all_present,
    )
