"""``vcollabpro`` — drive VCollab Pro in batch mode (``VCollabPro.exe -b``), Python **or** XML.

VCollab Pro's ``-b`` flag is overloaded and accepts EITHER kind of input file:

* **XML batch** — a declarative ``<VCollabBatch>`` document describing a fixed operation
  (image generation, CAX merge, viewpoint import, viewpoint→PowerPoint, compare/merge). Safe and
  always available.
* **Python script** — arbitrary ``_VCollabAPI`` Python 3 code executed inside VCollab Pro
  (open/save, parts, views, CAE results/probes/hotspots, viewpoints, report automation — the full
  1,178-function API). Powerful but it is arbitrary code execution, so it is **opt-in**
  (``Settings.enable_vcollabpro_script``).

Verified against the real exe (``VCollabPro64/VCollabPro.exe``):

* both paths run **headless** — no window pops, ``xMessageBox`` is suppressed in batch
  (``xIsGUIMode()`` returns False);
* inputs auto-load: ``-b script.py file1.cax file2.cax`` opens file1, merges file2 (Python mode);
* the exit code is **always 0** regardless of success/failure (a syntax error, an uncaught
  exception, and a clean run all exit 0), and the Python traceback is NOT printed to stdout — so
  success is detected from produced output files / the script's JSON write-back, never the return
  code (the same philosophy as :func:`produce_output`);
* the ``VCollabProX`` build rejects XML batch with "Unsupported Format!!!"; the ``VCollabPro64``
  build runs both — hence the executable mapping points at ``VCollabPro64``.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...paths import PathError, PathPolicy
from ...process import ProcessError, run_executable
from ...settings import Settings

MODE_PYTHON = "python"
MODE_XML = "xml"
_MODES = (MODE_PYTHON, MODE_XML, "auto")

# A value looks like a filesystem path (vs. a viewpoint name like "Std.Views") if it has a path
# separator, a drive/UNC prefix, or a known data-file extension.
_DATA_EXT_RE = re.compile(
    r"\.(cax|vpt|jpg|jpeg|png|bmp|tif|tiff|pdf|jt|wcax|ppt|pptx|pot|potx|csv|txt|xml)$",
    re.IGNORECASE,
)
_DRIVE_OR_UNC_RE = re.compile(r"^(?:[A-Za-z]:|\\\\)")
_DOCTYPE_RE = re.compile(r"<!DOCTYPE|<!ENTITY", re.IGNORECASE)

# Private marker key for wrapper-generated errors, so a user script that legitimately returns a
# dict keyed "error" is never mistaken for a failure.
_ERROR_MARKER = "__vcollabpro_error__"

# Module-level preamble prepended to BOTH inline and command-file Python: it defines the
# write_output() helper (the only way a batch script returns data), reading its target from the env
# var the tool sets (avoids any path-escaping in baked source). It is prepended at MODULE level —
# never wrapped in a function — so it can't break a complete script's own top-level constructs
# (e.g. ``from x import *``, which is illegal inside a function).
_PY_PREAMBLE = '''import json as _vc_json, os as _vc_os
_VC_OUTPUT_PATH = _vc_os.environ["VCOLLAB_SCRIPT_OUTPUT"]


def write_output(data):
    """Return structured data to the caller (writes JSON to the tool's output file)."""
    with open(_VC_OUTPUT_PATH, "w", encoding="utf-8") as _vc_f:
        _vc_json.dump(data, _vc_f, default=str)
'''

# Inline snippets are additionally wrapped: redraws are suspended for the run, and an uncaught
# exception is converted to a marked JSON error so the caller always learns what failed (the exit
# code never does). Complete command-file scripts run as-is (after the preamble) and own their
# error handling; a crash there is still surfaced via missing expected outputs.
#
# The wrapper makes its OWN VCollab calls through a private alias (`_vc_api`), NOT the bare
# `_VCollabAPI` name. The user snippet runs inside `_vc_main()`, and real VCollab scripts begin
# with `import _VCollabAPI`; Python would then treat `_VCollabAPI` as a function-local for the
# whole body, so the wrapper's lock call at the top would raise UnboundLocalError before the user's
# import line ran. The bare `import _VCollabAPI` is kept too, so a snippet that relies on it being
# pre-imported (no explicit import) still finds it as a module global.
_PY_INLINE_WRAPPER = '''import _VCollabAPI
import _VCollabAPI as _vc_api
import traceback as _vc_tb


def _vc_main():
    _vc_api.xLockRefresh(True)
    try:
{indented_user_script}
    finally:
        _vc_api.xLockRefresh(False)


try:
    _vc_main()
except Exception:
    write_output({{"__vcollabpro_error__": _vc_tb.format_exc()}})
'''


class ProducedFile(BaseModel):
    """An output file the batch run produced."""

    name: str
    size_bytes: int


class VCollabProResult(BaseModel):
    """Outcome of a VCollab Pro batch run."""

    mode: str = Field(description="Which batch path ran: 'python' or 'xml'.")
    produced_files: list[ProducedFile] = Field(
        default_factory=list,
        description="Output files the run created (verified non-empty).",
    )
    output: dict[str, Any] | None = Field(
        default=None,
        description="Structured data a Python script returned via write_output() (None for XML "
        "or when the script returned nothing).",
    )
    stdout_tail: str = Field(
        default="", description="Last lines of VCollab Pro's console output (for diagnostics)."
    )
    message: str


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    if "/" in value or "\\" in value:
        return True
    if _DRIVE_OR_UNC_RE.match(value):
        return True
    return bool(_DATA_EXT_RE.search(value))


def _resolve_against(base: Path, value: str) -> str:
    """Make ``value`` absolute, resolving a relative value against ``base``."""
    p = Path(value)
    return str(p if p.is_absolute() else (base / value))


def _check_xml_paths(xml_text: str, policy: PathPolicy, base_dir: Path) -> list[Path]:
    """Validate every path-like attribute in the XML against the policy; return the OUTPUT paths.

    The XML is LLM/user-authored and the XML path runs without the opt-in gate, so — like the
    VMoveCAE command-file tools — any path it references must satisfy the allowed-roots policy.
    Relative values are resolved against ``base_dir``. Output attributes (name contains 'out') are
    returned so the run's success can be verified by their existence (the exit code can't be
    trusted).

    The document is parsed with a real XML parser and the *decoded* values are checked, so
    single-quoted attributes and character references (``&#47;`` for ``/``) can't hide a path from
    the check. DOCTYPE/ENTITY declarations are refused outright: entity expansion is another way
    to build a value the check never sees, and nothing in a VCollab batch needs one.
    """
    if _DOCTYPE_RE.search(xml_text):
        raise ValueError("XML batch must not contain DOCTYPE or ENTITY declarations.")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"XML batch is not well-formed XML: {exc}") from exc

    outputs: list[Path] = []
    violations: list[str] = []
    for elem in root.iter():
        candidates = list(elem.attrib.items())
        if elem.text and elem.text.strip():
            candidates.append((elem.tag, elem.text))
        for name, raw in candidates:
            value = raw.strip()  # VCollabPro trims attribute values; match that before checking
            if not _looks_like_path(value):
                continue
            is_output = "out" in name.lower()
            target = _resolve_against(base_dir, value)
            try:
                # Outputs get their parent folder created (the exe expects it); inputs are only
                # vetted.
                resolved = (
                    policy.resolve_output(target) if is_output else policy.resolve_path(target)
                )
            except PathError:
                violations.append(f"{name}={value!r}")
                continue
            if is_output:
                outputs.append(resolved)
    if violations:
        raise PathError(
            "XML batch references path(s) outside the allowed roots: " + ", ".join(violations)
        )
    return outputs


def _detect_mode(*, explicit: str, content: str, source_name: str) -> str:
    if explicit in (MODE_PYTHON, MODE_XML):
        return explicit
    if explicit != "auto":
        raise ValueError(f"mode must be one of {_MODES}, got {explicit!r}.")
    if source_name.lower().endswith(".xml"):
        return MODE_XML
    if source_name.lower().endswith(".py"):
        return MODE_PYTHON
    # Sniff inline content: an XML batch starts with '<' (declaration or <VCollabBatch>).
    return MODE_XML if content.lstrip().startswith("<") else MODE_PYTHON


def vcollabpro(
    script: str = "",
    command_path: str = "",
    *,
    mode: str = "auto",
    input_paths: list[str] | None = None,
    output_paths: list[str] | None = None,
    description: str = "",
    settings: Settings,
    paths: PathPolicy,
) -> VCollabProResult:
    """Run a VCollab Pro batch job (Python script or XML) — see the registered tool for full docs.

    Exactly one of ``script`` (inline content) or ``command_path`` (a .py/.xml file) must be given.
    ``mode`` is auto-detected from the extension/content unless set explicitly.
    """
    if bool(script) == bool(command_path):
        raise ValueError("Provide exactly one of 'script' (inline) or 'command_path'.")
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, got {mode!r}.")

    input_paths = input_paths or []
    output_paths = output_paths or []
    if len(input_paths) > 2:
        raise ValueError("VCollab Pro loads at most two CAX files via the command line.")
    resolved_inputs = [paths.resolve_input(p) for p in input_paths]
    declared_outputs = [paths.resolve_output(p) for p in output_paths]

    # Resolve the batch content + its mode.
    if command_path:
        batch_path = paths.resolve_input(command_path)
        content = batch_path.read_text(encoding="utf-8", errors="replace")
        resolved_mode = _detect_mode(explicit=mode, content=content, source_name=command_path)
    else:
        batch_path = None
        content = script
        resolved_mode = _detect_mode(explicit=mode, content=content, source_name="")

    # VCollabPro picks Python vs XML from the batch file's EXTENSION, not from our mode. A forced
    # mode='xml' on a '.py' command file would therefore run Python while skipping the opt-in
    # gate below — so an XML job must actually be a .xml file.
    if (
        resolved_mode == MODE_XML
        and batch_path is not None
        and batch_path.suffix.lower() != ".xml"
    ):
        raise ValueError(
            f"An XML batch command file must have a .xml extension (got {batch_path.name!r})."
        )

    if resolved_mode == MODE_PYTHON and not settings.enable_vcollabpro_script:
        raise PermissionError(
            "The Python-script path of vcollab_vcollabpro is disabled. It runs arbitrary code "
            "inside VCollab Pro; enable it by setting VCOLLAB_ENABLE_VCOLLABPRO_SCRIPT=1. The XML "
            "batch path is always available."
        )

    # Working directory: relative paths in the job (XML sInputFile, a script's own file ops) resolve
    # against this. Anchor it to the user's declared output/input/command, else the process CWD.
    if declared_outputs:
        work_dir = declared_outputs[0].parent
    elif resolved_inputs:
        work_dir = resolved_inputs[0].parent
    elif batch_path is not None:
        work_dir = batch_path.parent
    else:
        work_dir = Path.cwd()

    exe = settings.resolve_executable("vcollabpro")
    timeout = settings.timeout_for("vcollabpro")
    env = settings.subprocess_env()

    # Internal temp files (transient, passed by absolute path) go in the system temp dir, NOT a
    # user/policy path. The JSON path is where a Python script's write_output() lands.
    # NB: prefix has NO leading dot — VCollabPro misparses a dotfile's extension (e.g.
    # '.vcollabpro-x.py' is not recognized as Python), so the script would never run.
    tmp_dir = Path(tempfile.gettempdir())
    json_fd, json_name = tempfile.mkstemp(dir=tmp_dir, prefix="vcollabpro-out-", suffix=".json")
    os.close(json_fd)
    json_path = Path(json_name)
    json_path.unlink(missing_ok=True)  # give the script a clean, non-existent path
    env["VCOLLAB_SCRIPT_OUTPUT"] = str(json_path)

    temp_script: Path | None = None
    xml_outputs: list[Path] = []
    try:
        if resolved_mode == MODE_XML:
            xml_outputs = _check_xml_paths(content, paths, work_dir)
            if batch_path is not None:
                run_target = batch_path
            else:
                fd, name = tempfile.mkstemp(dir=tmp_dir, prefix="vcollabpro-", suffix=".xml")
                os.close(fd)
                temp_script = Path(name)
                temp_script.write_text(content, encoding="utf-8")
                run_target = temp_script
            # -b is the batch flag; XML self-declares its input, so no positional CAX args.
            run_args = ["-b", str(run_target)]
        else:  # MODE_PYTHON
            # Both inline and command-file get the write_output() preamble (so the documented helper
            # is always available). Inline snippets are additionally wrapped for error capture;
            # a complete command-file program runs as-is after the preamble.
            if batch_path is not None:
                wrapped = _PY_PREAMBLE + "\n" + content
            else:
                indented = "\n".join("        " + line for line in content.splitlines())
                wrapped = _PY_PREAMBLE + "\n" + _PY_INLINE_WRAPPER.format(
                    indented_user_script=indented or "        pass"
                )
            fd, name = tempfile.mkstemp(dir=tmp_dir, prefix="vcollabpro-", suffix=".py")
            os.close(fd)
            temp_script = Path(name)
            temp_script.write_text(wrapped, encoding="utf-8")
            run_target = temp_script
            # -b runs the script; positional CAX args after it auto-load (first opened, rest merged)
            run_args = ["-b", str(run_target), *(str(p) for p in resolved_inputs)]

        result = run_executable(
            exe, run_args, timeout=timeout, cwd=work_dir, env=env, kill_tree=True
        )
        # Redact our internal temp paths from diagnostics returned to the client.
        stdout_tail = _tail(result.stdout, result.stderr).replace(str(tmp_dir), "[temp]")

        # Parse a Python script's JSON write-back, if any. Only the wrapper's private marker key
        # signals failure — a user dict that happens to contain "error" is passed through normally.
        output: dict[str, Any] | None = None
        if json_path.is_file() and json_path.stat().st_size > 0:
            output = _load_json_object(json_path)
            if output is not None and _ERROR_MARKER in output:
                raise ProcessError(f"VCollab Pro script raised an error:\n{output[_ERROR_MARKER]}")

        # Verify produced output files (the only reliable success signal). Stat each once and keep
        # the size, so a file vanishing between checks can't raise mid-result-build.
        verify = _dedupe(declared_outputs + xml_outputs)
        produced: list[tuple[Path, int]] = []
        for path in verify:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > 0:
                produced.append((path, size))
        if verify and not produced:
            raise ProcessError(
                "VCollab Pro batch produced none of the expected output files. Check the job and "
                f"its inputs. Console tail:\n{stdout_tail}"
            )

        return VCollabProResult(
            mode=resolved_mode,
            produced_files=[ProducedFile(name=p.name, size_bytes=size) for p, size in produced],
            output=output,
            stdout_tail=stdout_tail,
            message=_summary(resolved_mode, [p for p, _ in produced], output, description),
        )
    finally:
        if temp_script is not None:
            temp_script.unlink(missing_ok=True)
        json_path.unlink(missing_ok=True)


def _tail(stdout: str, stderr: str, *, limit: int = 1500) -> str:
    combined = "\n".join(s for s in (stdout, stderr) if s).strip()
    return combined[-limit:]


def _load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else {"value": data}


def _dedupe(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _summary(
    mode: str, produced: list[Path], output: dict[str, Any] | None, description: str
) -> str:
    prefix = f"{description}: " if description else ""
    files = ", ".join(p.name for p in produced) if produced else "no files"
    has_output = " (returned structured output)" if output else ""
    return f"{prefix}VCollab Pro {mode} batch completed — produced {files}{has_output}."
