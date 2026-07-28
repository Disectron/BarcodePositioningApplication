"""Headless command-line interface.

Exists so the entire output path can be driven and tested without a GUI - which
also makes AOPS usable from a build server or a commissioning script.

    aops export --project strip.aops --out ./out
    aops info    --project strip.aops
    aops symbol  010500
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aops import __version__
from aops.core.config import AopsConfig
from aops.core.enums import Severity
from aops.core.errors import AopsError
from aops.core.project_io import config_fingerprint, dump_project, load_project
from aops.core.rules import ALL_RULES
from aops.core.stats import derive
from aops.core.validation import run_rules
from aops.symbols.cache import SymbolCache, probe_matrix_cols
from aops.symbols.registry import build_registry


def _load(path: str | None) -> AopsConfig:
    if path is None:
        return AopsConfig()
    return load_project(Path(path).read_text(encoding="utf-8")).config


def _derive(cfg: AopsConfig) -> tuple:
    cache = SymbolCache(build_registry(cfg.symbol))
    sample = cfg.payload.prefix + "0" * cfg.payload.digits + cfg.payload.suffix
    cols = probe_matrix_cols(cache, cfg.symbol.symbology, sample)
    return derive(cfg, matrix_cols=cols), cache


def _report(cfg: AopsConfig, derived, *, verbose: bool) -> bool:
    """Print validation findings. Returns False if export is blocked."""
    report = run_rules(ALL_RULES, cfg, derived)
    for finding in report.sorted():
        if not verbose and finding.severity < Severity.WARNING:
            continue
        print(f"  [{finding.rule_id}] {finding.severity.label:<7} {finding.message}")
        if finding.hint and finding.severity >= Severity.WARNING:
            print(f"           -> {finding.hint}")
    return not report.blocks_export


def cmd_info(args: argparse.Namespace) -> int:
    cfg = _load(args.project)
    derived, _ = _derive(cfg)
    c = derived.cell
    print(f"AOPS {__version__}  fingerprint {config_fingerprint(cfg)}")
    print(f"  symbology       {cfg.symbol.symbology.display_name}")
    print(f"  codes           {derived.code_count}")
    print(f"  pitch/symbol    {c.pitch_mm:.3f} / {c.symbol_mm:.3f} mm")
    print(f"  module          {derived.scanner.module_size_mm:.4f} mm "
          f"({derived.accuracy.module_dots:.1f} dots @ {cfg.printer.dpi} dpi)")
    print(f"  total length    {derived.total_length_mm:.1f} mm "
          f"({derived.total_length_mm / 1000:.3f} m)")
    print(f"  sheets          {len(derived.pages)}")
    print(f"  formula         {derived.position_formula}")
    print(f"  required FOV    {derived.scanner.fov_continuous_mm:.1f} mm "
          f"({cfg.scanner.min_codes_in_view} code(s) in view)")
    print(f"  splice error    {derived.accuracy.cumulative_error_mm:.1f} mm cumulative vs "
          f"{derived.accuracy.bounded_error_mm:.2f} mm datum-aligned")
    print("validation:")
    _report(cfg, derived, verbose=args.verbose)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from aops.render.pdf.export import export_all

    cfg = _load(args.project)
    derived, cache = _derive(cfg)

    print("validation:")
    if not _report(cfg, derived, verbose=args.verbose):
        print("Export blocked by errors above.", file=sys.stderr)
        return 2

    def progress(done: int, total: int, phase: str) -> None:
        if args.quiet:
            return
        print(f"\r  {phase:<10} {done}/{total}", end="", flush=True)
        if done == total:
            print()

    results = export_all(cfg, derived, cache, args.out, basename=args.basename, progress=progress)
    for result in results:
        for path in result.paths:
            print(f"wrote {path}  ({path.stat().st_size / 1024:.0f} KB)")
        if result.verified_count:
            print(f"  {result.verified_count} symbols decode-verified")
    return 0


def cmd_symbol(args: argparse.Namespace) -> int:
    cfg = _load(args.project)
    cache = SymbolCache(build_registry(cfg.symbol))
    matrix = cache.get(cfg.symbol.symbology, args.payload)
    print(f"{cfg.symbol.symbology.display_name}  payload {matrix.payload!r}  "
          f"{matrix.rows}x{matrix.cols} modules  quiet zone {matrix.quiet_modules}")
    print(matrix.to_ascii())
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    path = Path(args.out)
    path.write_text(dump_project(AopsConfig(), app_version=__version__), encoding="utf-8")
    print(f"wrote {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aops",
        description="Absolute Optical Position Strip Generator - headless interface.",
    )
    parser.add_argument("--version", action="version", version=f"AOPS {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", "-p", help="Path to a .aops project file.")
    common.add_argument("--verbose", "-v", action="store_true", help="Show INFO findings too.")

    p_info = sub.add_parser("info", parents=[common], help="Summarise a configuration.")
    p_info.set_defaults(func=cmd_info)

    p_exp = sub.add_parser("export", parents=[common], help="Export PDFs.")
    p_exp.add_argument("--out", "-o", default="out", help="Output directory.")
    p_exp.add_argument("--basename", default="barcode_strip", help="Output file stem.")
    p_exp.add_argument("--quiet", "-q", action="store_true", help="Suppress progress output.")
    p_exp.set_defaults(func=cmd_export)

    p_sym = sub.add_parser("symbol", parents=[common], help="Print one symbol as ASCII.")
    p_sym.add_argument("payload", help="Payload to encode.")
    p_sym.set_defaults(func=cmd_symbol)

    p_new = sub.add_parser("new", help="Write a default project file.")
    p_new.add_argument("--out", "-o", default="untitled.aops")
    p_new.set_defaults(func=cmd_new)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except AopsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ncancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
