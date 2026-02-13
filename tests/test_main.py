from typer.testing import CliRunner
from warden.main import app

def test_main_cli_help():
    """Verify that the main CLI entry point shows help."""
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "AI Code Guardian" in result.stdout
    assert "scan" in result.stdout
    assert "status" in result.stdout

def test_status_command_help():
     """Verify status command is registered."""
     runner = CliRunner()
     result = runner.invoke(app, ["status", "--help"])
     assert result.exit_code == 0
     assert "Check the current security status" in result.stdout
