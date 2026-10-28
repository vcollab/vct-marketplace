"""``vmoveadams`` — convert an MSC Adams multibody-dynamics result to VCollab CAX.

``VMoveAdams.exe`` (``VMoveAdams.exe <adm_file> <res_file> <cax_file>``, in ``VMoveAdams64``)
translates an Adams model (``.adm``) plus its results (``.res``) into a ``.cax`` file.

Important constraints (verified against the real exe):

* **External MSC Adams Solver license required.** Beyond VCollab's own license, VMoveAdams acquires
  an MSC Adams Solver license via ``MSC_LICENSE_FILE`` (set by a separate MSC Adams installation).
  Without it the exe prints "Adams Solver license is not available", exits non-zero, and writes
  nothing — surfaced here as a clear error that names the license + staging requirement.
* **Adams runtime environment.** The exe needs ``MDI_USER_PLUGIN_DIR`` / ``MDI_AVIEW_MESSAGES`` and
  ``VMoveAdams64`` on PATH to load the aview engine; this tool sets them (it cannot set the external
  ``MSC_LICENSE_FILE``).
* **Folder-coupled inputs.** The ``.adm`` references sibling files (``.mtx``/``.mnf``/``.shl``/
  ``.xmt_txt``) that must be staged in the workspace alongside it.
* **Sidecar.** VMoveAdams may also emit a ``.json.gz`` animation sidecar; this tool returns the
  ``.cax`` and does not manage that sidecar (it could not be verified without an Adams license).

Its exit code on failure is unreliable (a license error exits non-zero; other failures may exit 0
with no output), so success is judged by a non-empty output file via :func:`produce_output`, which
also preserves a prior good output if the run fails.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from ...paths import PathPolicy
from ...process import ProcessError, run_executable
from ...settings import Settings
from .._output import produce_output


class VMoveAdamsResult(BaseModel):
    """Outcome of an Adams -> CAX conversion."""

    adm_file: str = Field(description="The source Adams model (.adm) file.")
    res_file: str = Field(description="The source Adams results (.res) file.")
    output_file: str = Field(description="Name of the produced CAX file.")
    output_path: str
    size_bytes: int
    message: str


def _adams_env(settings: Settings, exe_dir) -> dict[str, str]:
    """Build the Adams runtime environment the bat sets (minus the external MSC license)."""
    env = settings.subprocess_env()  # inherits os.environ + VCOLLAB_DIR
    env["MDI_USER_PLUGIN_DIR"] = str(exe_dir)
    env["MDI_AVIEW_MESSAGES"] = str(exe_dir / "aview.msg")
    if settings.vcollab_dir is not None:
        # setdefault: a host/installer-provided license path wins over our computed default.
        env.setdefault("VE3D_LICENSE_FILE", str(settings.vcollab_dir / "License"))
    env["PATH"] = str(exe_dir) + os.pathsep + env.get("PATH", "")
    return env


def vmoveadams(
    adm_path: str,
    res_path: str,
    output_path: str = "",
    *,
    settings: Settings,
    paths: PathPolicy,
) -> VMoveAdamsResult:
    """Convert an Adams model (.adm) + results (.res) to CAX.

    The ``.adm`` and its sibling ``.mtx``/``.mnf``/``.shl`` files must sit together in the same
    folder.

    Args:
        adm_path: Source Adams model file (e.g. 'crankshaft.adm').
        res_path: Source Adams results file (e.g. 'crankshaft.res').
        output_path: Output .cax path; defaults to the .adm path with a .cax extension.

    Raises:
        ValueError: if the output resolves to an input.
        PathError: if a path is outside the allowed roots.
        FileNotFoundError: if an input file does not exist.
        ProcessError: if the conversion produces no output (e.g. missing MSC Adams license or
            missing sibling .mtx files).
    """
    resolved_adm = paths.resolve_input(adm_path)
    resolved_res = paths.resolve_input(res_path)
    adm_name, res_name = resolved_adm.name, resolved_res.name
    if output_path:
        resolved_output = paths.resolve_output(output_path)
    else:
        resolved_output = paths.resolve_output(str(resolved_adm.with_suffix(".cax")))
    if resolved_output in (resolved_adm, resolved_res):
        raise ValueError("Output file must differ from the input files.")

    # Resolve the exe before producing output so a broken install can't damage existing data.
    exe = settings.resolve_executable("vmoveadams")
    env = _adams_env(settings, exe.parent)
    try:
        produce_output(
            resolved_output,
            lambda out: run_executable(
                exe,
                [str(resolved_adm), str(resolved_res), str(out)],
                timeout=settings.timeout_for("vmoveadams"),
                env=env,
            ),
            error_message=f"VMoveAdams produced no output for {adm_name!r}.",
        )
    except ProcessError as exc:
        # On a missing MSC license the exe exits non-zero, so run_executable raises before
        # produce_output's own message can fire. Attach the actionable guidance to every failure
        # mode here so the caller always sees the license + staging requirement.
        raise ProcessError(
            f"{exc} -- VMoveAdams needs the .adm's sibling .mtx/.mnf/.shl files alongside it AND "
            "an MSC Adams Solver license (MSC_LICENSE_FILE, from a separate MSC Adams "
            "installation)."
        ) from exc

    return VMoveAdamsResult(
        adm_file=adm_name,
        res_file=res_name,
        output_file=resolved_output.name,
        output_path=str(resolved_output),
        size_bytes=resolved_output.stat().st_size,
        message=f"Converted {adm_name} (+ {res_name}) to {resolved_output.name}.",
    )
