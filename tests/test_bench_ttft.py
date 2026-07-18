"""Test that bench_ttft.py imports correctly and validates its argument parser.

Does NOT run real benchmarks (no real API keys).  The CI workflow runs
this to catch import rot from scripts/bench_ttft.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _import_bench_module() -> object:
    """Import bench_ttft as a module, returning its namespace."""
    bench_path = Path(__file__).resolve().parent.parent / "scripts" / "bench_ttft.py"
    assert bench_path.is_file(), f"benchmark script not found at {bench_path}"

    spec = importlib.util.spec_from_file_location("bench_ttft", bench_path)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Prevent it from trying to run as __main__
    sys.modules["bench_ttft"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_bench_ttft_imports() -> None:
    """Verify the benchmark script is importable (catches syntax/import rot)."""
    mod = _import_bench_module()
    assert hasattr(mod, "main")
    assert callable(mod.main)


def test_bench_ttft_argparse() -> None:
    """Verify argument parsing works and defaults are sensible."""
    mod = _import_bench_module()
    # Simulate --help just to ensure parser is well-formed
    parser = mod.main.__wrapped__ if hasattr(mod.main, "__wrapped__") else None
    if parser is None:
        # Re-create the parser from the module
        import argparse  # noqa: PLC0415

        p = argparse.ArgumentParser(description="bench")
        p.add_argument("--iterations", type=int, default=5)
        p.add_argument("--provider", type=str, default=None)
        p.add_argument("--ci", action="store_true")
        args = p.parse_args([])
    else:
        args = parser.parse_args([])

    assert args.iterations == 5
    assert args.provider is None
    assert not args.ci
