"""Command-line interface for M1: process discovery and read-only region inspection.

Every command is a one-shot, user-initiated action; nothing keeps running in the background.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from aoe2mr import __version__
from aoe2mr.app_logging import configure_logging
from aoe2mr.backends import create_default_backend
from aoe2mr.backends.base import ProcessBackend
from aoe2mr.config import AppConfig, ConfigError, load_config
from aoe2mr.errors import ResearchError
from aoe2mr.memory_research.models import RegionReport
from aoe2mr.memory_research.regions import RegionInspector
from aoe2mr.persistence.json_store import ResultStore, to_jsonable
from aoe2mr.process_discovery.discovery import ProcessDiscovery
from aoe2mr.process_discovery.models import ProcessDetails

BackendFactory = Callable[[], ProcessBackend]


def _fmt_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def _print_details(d: ProcessDetails, out: TextIO) -> None:
    out.write(f"PID:           {d.pid}\n")
    out.write(f"Name:          {d.name}{'  [target]' if d.is_target else ''}\n")
    out.write(f"Executable:    {d.executable_path or 'UNKNOWN'}\n")
    out.write(f"Architecture:  {d.architecture.value}\n")
    out.write(f"Access:        {d.access.value}\n")
    if d.access_error:
        out.write(f"Access note:   {d.access_error}\n")


def _print_report(report: RegionReport, limit: int, out: TextIO) -> None:
    s = report.summary
    out.write(f"Regions:       {s.region_count} kept, {report.skipped_regions} skipped"
              f"{' (TRUNCATED at cap)' if report.truncated else ''}\n")
    out.write(f"Total size:    {_fmt_bytes(s.total_bytes)}\n")
    out.write(f"Readable:      {s.readable_count} regions, {_fmt_bytes(s.readable_bytes)} "
              f"({_fmt_bytes(s.writable_readable_bytes)} writable by the target)\n")
    out.write("By type:       " + ", ".join(f"{k}={_fmt_bytes(v)}"
                                          for k, v in s.bytes_by_type.items()) + "\n")
    out.write("By protection: " + ", ".join(f"{k}={_fmt_bytes(v)}"
                                          for k, v in s.bytes_by_protection.items()) + "\n")
    if limit <= 0:
        return
    out.write(f"\n{'Base':>18} {'Size':>10} {'State':<8} {'Type':<8} {'Protect':<10} Read\n")
    for r in report.regions[:limit]:
        out.write(f"{r.base_address:#018x} {_fmt_bytes(r.size):>10} {r.state.value:<8} "
                  f"{r.type.value:<8} {r.protect.label:<10} {'yes' if r.is_readable else 'no'}\n")
    if len(report.regions) > limit:
        out.write(f"... {len(report.regions) - limit} more (use --limit or --save)\n")


def _cmd_info(cfg: AppConfig, factory: BackendFactory, args: argparse.Namespace,
              out: TextIO) -> int:
    out.write(f"aoe2mr {__version__}\n")
    out.write(f"Python:        {platform.python_version()} "
              f"({ctypes.sizeof(ctypes.c_void_p) * 8}-bit)\n")
    out.write(f"Platform:      {platform.platform()}\n")
    out.write(f"Targets:       {', '.join(cfg.discovery.target_executables)}\n")
    try:
        elevated = factory().is_elevated()
    except ResearchError:
        elevated = None
    out.write(f"Elevated:      {'UNKNOWN' if elevated is None else elevated}\n")
    return 0


def _cmd_processes(cfg: AppConfig, factory: BackendFactory, args: argparse.Namespace,
                   out: TextIO) -> int:
    discovery = ProcessDiscovery(factory(), cfg.discovery)
    if args.all or args.filter:
        entries = discovery.list_processes(args.filter)
        if args.json:
            out.write(json.dumps(to_jsonable(entries), indent=2) + "\n")
            return 0
        out.write(f"{'PID':>7} {'PPID':>7} {'Thr':>4}  Name\n")
        for e in entries:
            mark = "  [target]" if discovery.is_target_name(e.name) else ""
            out.write(f"{e.pid:>7} {e.parent_pid:>7} {e.thread_count:>4}  {e.name}{mark}\n")
        return 0

    targets = discovery.find_targets()
    if args.json:
        out.write(json.dumps(to_jsonable(targets), indent=2) + "\n")
        return 0 if targets else 2
    if not targets:
        out.write("No Age of Empires II: DE process found "
                  f"(looked for {', '.join(cfg.discovery.target_executables)}).\n")
        return 2
    for i, d in enumerate(targets):
        if i:
            out.write("\n")
        _print_details(d, out)
    return 0


def _cmd_inspect(cfg: AppConfig, factory: BackendFactory, args: argparse.Namespace,
                 out: TextIO) -> int:
    backend = factory()
    discovery = ProcessDiscovery(backend, cfg.discovery)
    if args.pid is not None:
        details = discovery.describe(args.pid)
    else:
        targets = discovery.find_targets()
        if not targets:
            out.write("No Age of Empires II: DE process found; pass --pid to inspect another "
                      "process (e.g. the synthetic target).\n")
            return 2
        details = targets[0]
    _print_details(details, out)
    out.write("\n")
    report = RegionInspector(backend, cfg.regions).inspect(
        details.pid, readable_only=args.readable_only
    )
    _print_report(report, args.limit, out)
    if args.save:
        path = ResultStore(cfg.persistence.data_dir).save(
            "region_report", {"process": details, "report": report}
        )
        out.write(f"\nSaved: {path}\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aoe2mr",
        description="Read-only AoE2 DE process research tool (milestone M1).",
    )
    parser.add_argument("--config", type=Path, help="user TOML config overriding defaults")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="show environment and privilege information")

    p = sub.add_parser("processes", help="find AoE2 DE (default) or list processes")
    p.add_argument("--all", action="store_true", help="list all processes")
    p.add_argument("--filter", help="case-insensitive substring filter on process name")
    p.add_argument("--json", action="store_true", help="print JSON")

    i = sub.add_parser("inspect", help="enumerate memory regions (read-only)")
    i.add_argument("--pid", type=int, help="process ID (default: the AoE2 DE process)")
    i.add_argument("--readable-only", action="store_true", help="only readable regions")
    i.add_argument("--limit", type=int, default=40, help="regions to print (0 = none)")
    i.add_argument("--save", action="store_true", help="save the report as JSON")
    return parser


_COMMANDS = {"info": _cmd_info, "processes": _cmd_processes, "inspect": _cmd_inspect}


def main(
    argv: Sequence[str] | None = None,
    *,
    backend_factory: BackendFactory = create_default_backend,
    out: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        sys.stderr.write(f"Configuration error: {exc}\n")
        return 1
    configure_logging(cfg.logging, cfg.persistence.data_dir / "logs")
    try:
        return _COMMANDS[args.command](cfg, backend_factory, args, out)
    except ResearchError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
