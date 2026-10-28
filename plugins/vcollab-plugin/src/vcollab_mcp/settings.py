"""Configuration for the VCollab MCP server.

Settings are loaded from environment variables (prefixed ``VCOLLAB_``) and an optional
``.env`` file. The VCollab installation directory can be auto-discovered when not set.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import PathPolicy

# Per-tool subprocess timeouts (seconds). VCollabPro/VMoveCAE runs on large models can be slow,
# so conversion/scripting get much longer budgets than a metadata probe.
DEFAULT_TOOL_TIMEOUTS: dict[str, int] = {
    "caxinfo": 60,
    "caeinfo": 120,
    "cadinfo": 300,
    "caxmerge": 300,
    "vmovecae": 600,
    "vmovecad": 600,
    "vmovejt": 600,
    "vmovex": 900,
    "vmovecst": 600,
    "vmoveadams": 900,
    "vmovecaesubmit": 900,
    "vmovecaevalidate": 120,
    "image_generator": 300,
    "vcollabpro": 600,
}

# Relative paths of the VCollab executables within the install directory.
# Stable across 26.x installs; override individually via env if a layout differs.
DEFAULT_EXECUTABLES: dict[str, str] = {
    "caxinfo": "VMoveCAE64/CaxInfo.exe",
    "caeinfo": "VMoveCAE64/CaeInfo.exe",
    "cadinfo": "VMoveCAD64/CadInfo.exe",
    "caxmerge": "VMoveCAE64/CaxMerge.exe",
    "vmovecaebatch": "VMoveCAE64/VMoveCAEBatch.exe",
    "vmovecadbatch": "VMoveCAD64/VMoveCADBatch.exe",
    "vmovejtbatch": "VMoveJT64/VMoveJTBatch.exe",
    "vmovexsubmit": "VMoveX/VMoveXSubmit.exe",
    "vmovecst": "VMoveCST64/VMoveCST.exe",
    "vmoveadams": "VMoveAdams64/VMoveAdams.exe",
    "vmovecaesubmit": "VMoveCAE64/VMoveCAESubmit.exe",
    "vmovecaevalidate": "VMoveCAE64/VMoveCAEValidate.exe",
    # Batch mode (-b) requires the VCollabPro64 build; the VCollabProX variant rejects XML batch
    # inputs with "Unsupported Format!!!" (Python batch works on both, so 64 is the safe choice).
    "vcollabpro": "VCollabPro64/VCollabPro.exe",
    "vcollabimggen": "VCollabProX/VCollabImageGenerator.exe",
}

# Where VCollab installs by default on Windows.
_PROGRAM_FILES_VCOLLAB = Path("C:/Program Files/VCollab")


class UnknownExecutableError(KeyError):
    """An executable key missing from the configured map (e.g. a partial VCOLLAB_EXECUTABLES).

    A ``KeyError`` subclass for compatibility, but ``str()`` returns the plain message rather than
    KeyError's quoted repr, so it reads cleanly when surfaced to the client as a ``ToolError``.
    """

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else super().__str__()


def discover_vcollab_dir() -> Path | None:
    """Return the newest ``C:/Program Files/VCollab/<version>`` that looks like an install.

    Returns ``None`` when nothing is found (e.g. on a client-only machine).
    """
    if not _PROGRAM_FILES_VCOLLAB.is_dir():
        return None
    candidates = [
        d
        for d in _PROGRAM_FILES_VCOLLAB.iterdir()
        if d.is_dir() and (d / "VMoveCAE64").is_dir()
    ]
    if not candidates:
        return None
    # Sort by version-like name descending so "26.1" wins over "25.2".
    candidates.sort(key=lambda p: _version_key(p.name), reverse=True)
    return candidates[0]


def _version_key(name: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in name.replace("-", ".").split("."):
        parts.append(int(chunk) if chunk.isdigit() else 0)
    return tuple(parts) or (0,)


class Settings(BaseSettings):
    """Runtime configuration for the VCollab MCP server."""

    model_config = SettingsConfigDict(
        env_prefix="VCOLLAB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    vcollab_dir: Path | None = Field(
        default=None,
        # The field name already starts with "vcollab", so the VCOLLAB_ prefix alone would
        # bind to VCOLLAB_VCOLLAB_DIR. Accept the documented VCOLLAB_DIR (and the field name
        # for kwargs / programmatic construction).
        validation_alias=AliasChoices("vcollab_dir", "VCOLLAB_DIR", "VCOLLAB_VCOLLAB_DIR"),
        description="VCollab installation root. Auto-discovered from Program Files if unset.",
    )
    allowed_roots: str = Field(
        default="",
        description="Optional ';'-separated list of directories that file paths must stay within "
        "(VCOLLAB_ALLOWED_ROOTS). Empty = unrestricted. On the HTTP transport, an empty value "
        "requires VCOLLAB_ALLOW_ANY_PATH=1 or the server refuses to start.",
    )
    allow_any_path: bool = Field(
        default=False,
        description="Explicitly permit unrestricted file access on the HTTP transport when no "
        "allowed_roots are set (VCOLLAB_ALLOW_ANY_PATH). Local/stdio is unrestricted by default.",
    )
    executables: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_EXECUTABLES))
    process_timeout: int = Field(
        default=120,
        ge=1,
        description="Fallback subprocess timeout (seconds) for tools without a specific entry.",
    )
    tool_timeouts: dict[str, int] = Field(
        default_factory=lambda: dict(DEFAULT_TOOL_TIMEOUTS),
        description="Per-tool subprocess timeouts (seconds); overrides process_timeout.",
    )
    enable_vcollabpro_script: bool = Field(
        default=False,
        description="Allow the Python-script path of vcollab_vcollabpro (arbitrary _VCollabAPI "
        "code run inside VCollabPro). Off by default; set VCOLLAB_ENABLE_VCOLLABPRO_SCRIPT=1 to "
        "enable. The safe XML-batch path is always available regardless of this flag.",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level (VCOLLAB_LOG_LEVEL): DEBUG, INFO, WARNING, ERROR.",
    )
    log_dir: Path | None = Field(
        default=None,
        description="Directory for rotating log files (VCOLLAB_LOG_DIR). "
        "Defaults to %LOCALAPPDATA%/VCollab/mcp/logs.",
    )

    @field_validator("vcollab_dir", mode="before")
    @classmethod
    def _blank_vcollab_dir_is_unset(cls, value: object) -> object:
        # Plugin/extension hosts pass an optional, unfilled setting as VCOLLAB_DIR="". Treat that
        # as "not set" so auto-discovery runs, instead of letting it become Path(".").
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("vcollab_dir", mode="after")
    @classmethod
    def _resolve_vcollab_dir(cls, value: Path | None) -> Path | None:
        return value if value is not None else discover_vcollab_dir()

    @field_validator("log_level", mode="after")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def _finalize_tool_timeouts(self) -> Settings:
        # An env override (VCOLLAB_TOOL_TIMEOUTS='{"caxinfo": 5}') replaces the field wholesale,
        # which would silently drop every other tool to the fallback. Merge onto the defaults so
        # a partial override only changes the tools it names, then validate every value.
        merged = {**DEFAULT_TOOL_TIMEOUTS, **self.tool_timeouts}
        for name, value in merged.items():
            if value < 1:
                raise ValueError(f"tool_timeouts[{name!r}] must be >= 1 second, got {value}")
        self.tool_timeouts = merged
        return self

    def allowed_root_list(self) -> list[str]:
        """Parse ``allowed_roots`` (';'-separated) into a list of directory strings."""
        return [r.strip() for r in self.allowed_roots.split(";") if r.strip()]

    def path_policy(self) -> PathPolicy:
        """Build the :class:`PathPolicy` from ``allowed_roots`` (empty = unrestricted)."""
        roots = self.allowed_root_list()
        return PathPolicy(roots or None)

    def http_access_blocked(self) -> bool:
        """True if starting on HTTP would be unsafe: no allowed_roots and no explicit opt-in."""
        return not self.allowed_root_list() and not self.allow_any_path

    def timeout_for(self, tool: str) -> int:
        """Return the configured timeout for ``tool``, falling back to ``process_timeout``."""
        return self.tool_timeouts.get(tool, self.process_timeout)

    def all_timeouts(self) -> dict[str, int]:
        """Return the per-tool timeout map (for diagnostics)."""
        return dict(self.tool_timeouts)

    def resolved_log_dir(self) -> Path:
        """Return the directory for log files, defaulting to a stable per-user location."""
        if self.log_dir is not None:
            return self.log_dir
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "VCollab" / "mcp" / "logs"

    def log_file(self) -> Path:
        """Return the full rotating-log file path."""
        return self.resolved_log_dir() / "vcollab-mcp.log"

    def subprocess_env(self) -> dict[str, str]:
        """Environment for VCollab subprocesses: inherit the parent's, then ensure VCOLLAB_DIR.

        VCollab executables (CaeInfo, VCollabPro, ...) read ``VCOLLAB_DIR`` at runtime to locate
        their resources and crash without it. The installer normally sets it system-wide, but we
        set it explicitly from the resolved install dir so the tools also work when the server is
        launched in a sanitized environment (some MCP clients spawn with a minimal env).
        """
        env = dict(os.environ)
        if self.vcollab_dir is not None:
            env["VCOLLAB_DIR"] = str(self.vcollab_dir)
        return env

    def resolve_executable(self, name: str) -> Path:
        """Return the absolute path to a named VCollab executable.

        Raises:
            UnknownExecutableError: (a ``KeyError``) if the name is not a known executable.
            FileNotFoundError: if VCollab is not installed or the exe is missing.
        """
        rel = self.executables.get(name)
        if rel is None:
            raise UnknownExecutableError(
                f"Unknown VCollab executable: {name!r}. If you set VCOLLAB_EXECUTABLES, note it "
                "replaces the whole executable map, so it must list every executable."
            )
        if self.vcollab_dir is None:
            raise FileNotFoundError(
                "VCollab installation not found. Set VCOLLAB_DIR to your install path "
                "(e.g. 'C:/Program Files/VCollab/26.1')."
            )
        exe = (self.vcollab_dir / rel).resolve()
        if not exe.is_file():
            raise FileNotFoundError(f"VCollab executable not found: {exe}")
        return exe


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, loaded once from the environment."""
    return Settings()
