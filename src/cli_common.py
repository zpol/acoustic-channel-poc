"""Shared CLI helpers for acoustic-channel tools."""

from __future__ import annotations

import argparse
from typing import Any, Optional, Sequence

from src.modulation import PROFILES


def add_profile_argument(parser: argparse.ArgumentParser) -> None:
    """Add ``--profile`` with reliable/fast/turbo presets."""
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES.keys()),
        default=None,
        help=(
            "Speed/reliability preset: "
            "reliable=200ms 4/6kHz, "
            "fast=120ms 3.5/7.5kHz (default params), "
            "turbo=80ms 3/8kHz experimental"
        ),
    )


def _explicit_dests(argv: Sequence[str]) -> set[str]:
    """Return argparse dest names the user set on the command line."""
    found: set[str] = set()
    for arg in argv:
        if not arg.startswith("--") or arg == "--profile":
            continue
        name = arg[2:].split("=", 1)[0].replace("-", "_")
        found.add(name)
    return found


def apply_profile(
    args: argparse.Namespace,
    argv: Optional[Sequence[str]] = None,
) -> argparse.Namespace:
    """Overlay profile defaults without clobbering explicit CLI flags."""
    if not getattr(args, "profile", None):
        return args
    import sys

    preset: dict[str, Any] = PROFILES[args.profile]
    cli_argv = list(argv) if argv is not None else sys.argv[1:]
    explicit = _explicit_dests(cli_argv)
    for key, value in preset.items():
        if key not in explicit:
            setattr(args, key, value)
    return args
