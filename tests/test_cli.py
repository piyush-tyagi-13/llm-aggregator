from __future__ import annotations
from typer.testing import CliRunner
from llm_apipool.cli import app

runner = CliRunner()


def test_cli_status_no_db():
    """CLI should handle missing DB gracefully."""
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0 or "error" in result.output.lower()


def test_cli_help():
    """CLI should display help."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output
