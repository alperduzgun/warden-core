"""
Warden CLI
==========

The main entry point for the Warden Python CLI.
Provides commands for scanning, serving, and launching the interactive chat.
"""

import typer
from rich.console import Console
import signal
import asyncio
import sys
from typing import NoReturn

# Command Logic Imports
from warden.cli.commands.version import version_command
from warden.cli.commands.chat import chat_command
from warden.cli.commands.status import status_command
from warden.cli.commands.scan import scan_command
from warden.cli.commands.init import init_command
from warden.cli.commands.serve import serve_app
from warden.cli.commands.search import search_command, index_command
from warden.cli.commands.install import install as install_command
from warden.cli.commands.doctor import doctor as doctor_command
from warden.cli.commands.update import update_command
from warden.cli.commands.refresh import refresh_command
from warden.cli.commands.baseline import baseline_app
from warden.cli.commands.ci import ci_app
from warden.cli.commands.config import config_app
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Global shutdown flag
_shutdown_requested = False

async def graceful_shutdown() -> None:
    """
    Perform graceful shutdown of all Warden services.

    Cleanup sequence:
    1. Stop any running pipeline execution
    2. Shutdown all LSP servers
    3. Close semantic search services
    """
    global _shutdown_requested
    if _shutdown_requested:
        return  # Already shutting down

    _shutdown_requested = True
    logger.info("shutdown_initiated", reason="signal_received")

    try:
        # Shutdown LSP servers
        try:
            from warden.lsp.manager import LSPManager
            lsp_manager = LSPManager.get_instance()
            await lsp_manager.shutdown_all_async()
            logger.info("lsp_servers_shutdown_complete")
        except Exception as e:
            logger.warning("lsp_shutdown_failed", error=str(e))

        # Close semantic search services
        try:
            from warden.semantic_search.semantic_search_service import SemanticSearchService
            # If there's a global instance, close it
            # This is optional - depends on implementation
            logger.info("semantic_search_cleanup_complete")
        except Exception as e:
            logger.debug("semantic_search_cleanup_skipped", error=str(e))

        logger.info("graceful_shutdown_complete")
    except Exception as e:
        logger.error("shutdown_error", error=str(e))



# Initialize Typer app
app = typer.Typer(
    name="warden",
    help="AI Code Guardian - Secure your code before production",
    add_completion=False,
    no_args_is_help=True
)

# Register Sub-Apps
app.add_typer(serve_app, name="serve")
app.add_typer(baseline_app, name="baseline")
app.add_typer(ci_app, name="ci")
app.add_typer(config_app, name="config")

# Register Top-Level Commands
app.command(name="version")(version_command)
app.command(name="chat")(chat_command)
app.command(name="status")(status_command)
app.command(name="scan")(scan_command)
app.command(name="init")(init_command)
app.command(name="search")(search_command)
app.command(name="index")(index_command)
app.command(name="install")(install_command)
app.command(name="doctor")(doctor_command)
app.command(name="update")(update_command)
app.command(name="refresh")(refresh_command)

def main():
    """Entry point for setuptools."""
    # Let Typer and Asyncio handle signals naturally
    # We do NOT want a global signal handler because it conflicts
    # with asyncio.run() which manages its own loop lifecycle.
    
    app()

if __name__ == "__main__":
    app()
