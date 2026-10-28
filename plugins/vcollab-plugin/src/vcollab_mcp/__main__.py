"""Command-line entry point: ``vcollab-mcp`` / ``python -m vcollab_mcp``.

Subcommands:
    (default)   run the MCP server (stdio, or --transport http)
    doctor      print VCollab installation diagnostics and exit
"""

from __future__ import annotations

import argparse
import contextlib
import sys

import fastmcp

from . import __version__
from .diagnostics import build_health_report
from .logging_config import configure_logging, get_logger
from .server import EDITIONS, create_server
from .settings import Settings, get_settings

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vcollab-mcp",
        description="VCollab MCP server (CAE/CAX tools over the Model Context Protocol).",
    )
    parser.add_argument("--version", action="version", version=f"vcollab-mcp {__version__}")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio (local, default) or http (Streamable HTTP for remote clients).",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host for http transport.")
    parser.add_argument("--port", type=int, default=8080, help="Bind port for http transport.")
    parser.add_argument(
        "--edition",
        choices=list(EDITIONS),
        default="full",
        help="Tool set: full (default) or plugin (the Claude directory build: XML-only "
        "vcollab_vcollabpro, no knowledge tools).",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity. Overrides VCOLLAB_LOG_LEVEL.",
    )

    sub = parser.add_subparsers(dest="command")
    doctor = sub.add_parser("doctor", help="Print VCollab installation diagnostics and exit.")
    doctor.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    return parser


def run_doctor(settings: Settings, *, as_json: bool) -> int:
    """Print a diagnostics report; return process exit code (0 ok, 1 problems)."""
    # Defend against strict OEM consoles (cp850/cp437): a non-ASCII char (e.g. a CJK Windows
    # username in the log path) would otherwise raise UnicodeEncodeError mid-report.
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        with contextlib.suppress(ValueError, OSError):
            reconfigure(errors="backslashreplace")

    report = build_health_report(settings, log_file=str(settings.log_file()))

    if as_json:
        print(report.model_dump_json(indent=2))
        return 0 if report.all_required_present else 1

    detected = "detected" if report.vcollab_detected else "NOT FOUND"
    print(f"VCollab MCP doctor - vcollab-mcp {report.server_version}\n")
    print(f"  VCollab dir : {report.vcollab_dir or '(none)'}  ({detected})")
    print(f"  File access : {report.file_access}")
    print(f"  Log file    : {report.log_file}\n")
    print("  Executables:")
    for exe in report.executables:
        if exe.found:
            print(f"    [OK]      {exe.name:<14} {exe.path}")
        else:
            print(f"    [MISSING] {exe.name}")
    timeouts = " ".join(f"{k}={v}s" for k, v in report.timeouts.items())
    print(f"\n  Timeouts: {timeouts}")

    if report.all_required_present:
        print("\n  Status: OK")
        return 0
    print(
        "\n  Status: PROBLEMS FOUND - set VCOLLAB_DIR to your VCollab install "
        "(e.g. 'C:/Program Files/VCollab/26.1')."
    )
    return 1


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = get_settings()

    if args.command == "doctor":
        configure_logging(level="WARNING")
        sys.exit(run_doctor(settings, as_json=args.json))

    level = args.log_level or settings.log_level
    configure_logging(level=level, log_file=settings.log_file())
    logger.info("vcollab-mcp %s starting (log file: %s)", __version__, settings.log_file())

    if args.transport == "http" and settings.http_access_blocked():
        # Fail closed: never expose an unrestricted file server on the network by accident.
        logger.error(
            "Refusing to start the HTTP server with unrestricted file access. "
            "Set VCOLLAB_ALLOWED_ROOTS to bound file access (e.g. 'D:/shared'), or set "
            "VCOLLAB_ALLOW_ANY_PATH=1 to explicitly accept unrestricted access."
        )
        sys.exit(2)

    server = create_server(settings, edition=args.edition)

    # FastMCP's startup banner advertises a hosted service and, while showing it, queries PyPI for
    # a newer FastMCP. This server promises no network access of its own, so turn both off.
    fastmcp.settings.check_for_updates = "off"
    if args.transport == "http":
        logger.info("Serving on http://%s:%d/mcp", args.host, args.port)
        server.run(transport="http", host=args.host, port=args.port, show_banner=False)
    else:
        server.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
