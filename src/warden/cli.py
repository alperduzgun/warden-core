"""
Warden CLI
==========

The main entry point for the Warden Python CLI.
Provides commands for scanning, serving, and launching the interactive chat.
"""

import asyncio
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Optional, List
from datetime import datetime

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

# Internal imports
from warden.cli_bridge.bridge import WardenBridge
from warden.services.ipc_entry import main as ipc_main
from warden.services.grpc_entry import main as grpc_main

# Initialize Typer app
app = typer.Typer(
    name="warden",
    help="AI Code Guardian - Secure your code before production",
    add_completion=False,
    no_args_is_help=True
)

# Sub-app for server commands
serve_app = typer.Typer(name="serve", help="Start Warden backend services")
app.add_typer(serve_app, name="serve")

# Sub-app for spec commands
spec_app = typer.Typer(name="spec", help="API Contract specification analysis")
app.add_typer(spec_app, name="spec")

console = Console()


def _check_node_cli_installed() -> bool:
    """Check if warden-cli (Node.js) is installed and available."""
    # check for global executable
    if shutil.which("warden-cli"):
        return True
    
    # check if we are in dev environment where ../cli might exist
    # (This is a heuristic for local dev)
    dev_cli_path = Path(__file__).parents[2] / "cli"
    if dev_cli_path.exists() and (dev_cli_path / "package.json").exists():
        return True
        
    return False


@app.command()
def version():
    """Show Warden version info."""
    # from warden.config.config_manager import ConfigManager
    # Try to get version from package metadata if possible, else hardcode for now
    version = "0.1.0" 
    
    table = Table(show_header=False, box=None)
    table.add_row("Warden Core", f"[bold green]v{version}[/bold green]")
    table.add_row("Python", sys.version.split()[0])
    table.add_row("Platform", sys.platform)
    
    console.print(Panel(table, title="[bold blue]Warden[/bold blue]", expand=False))


@app.command()
def chat(
    ctx: typer.Context,
    dev: bool = typer.Option(False, "--dev", help="Run in dev mode (npm run start:raw)")
):
    """
    Launch the interactive AI Chat interface (Node.js required).
    
    This delegates to the 'warden-cli' executable or local dev script.
    """
    console.print("[bold blue]🚀 Launching Warden AI Chat...[/bold blue]")

    # 1. Check for local dev environment
    # This logic assumes we are running from src/warden/cli.py
    # so project root is 3 levels up -> warden-core/
    repo_root = Path(__file__).parents[2] 
    cli_dir = repo_root / "cli"

    if dev and cli_dir.exists():
        console.print("[dim]Using local dev version...[/dim]")
        try:
            # We need to install dependencies first if not node_modules
            if not (cli_dir / "node_modules").exists():
                console.print("[yellow]📦 Installing CLI dependencies...[/yellow]")
                subprocess.run(["npm", "install"], cwd=cli_dir, check=True)

            cmd = ["npm", "run", "start:raw"]
            subprocess.run(cmd, cwd=cli_dir)
            return
        except Exception as e:
            console.print(f"[bold red]Failed to launch dev CLI:[/bold red] {e}")
            raise typer.Exit(1)

    # 2. Check for globally installed binary
    if shutil.which("warden-cli"):
        try:
            subprocess.run(["warden-cli"] + ctx.args)
            return
        except KeyboardInterrupt:
            return
    
    # 3. Check for npx
    if shutil.which("npx"):
        try:
            console.print("[dim]warden-cli not found, trying npx @warden/cli...[/dim]")
            # Note: This assumes package is published as @warden/cli
            subprocess.run(["npx", "-y", "@warden/cli"] + ctx.args)
            return
        except KeyboardInterrupt:
            return

    console.print("[bold red]❌ Error:[/bold red] Warden Interactive CLI (Node.js) not found.")
    console.print("Please install it running: [green]npm install -g @warden/cli[/green]")
    raise typer.Exit(1)


@app.command()
def scan(
    path: str = typer.Argument(".", help="Path to scan (file or directory)"),
    frames: Optional[List[str]] = typer.Option(None, "--frame", "-f", help="Specific frames to run"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed logs"),
):
    """
    Run the full Warden pipeline on a file or directory.
    """
    # We defer import to avoid slow startup for other commands
    from warden.shared.infrastructure.logging import get_logger
    
    # Run async scan function
    try:
        exit_code = asyncio.run(_run_scan_async(path, frames, verbose))
        if exit_code != 0:
            raise typer.Exit(exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Scan interrupted by user[/yellow]")
        raise typer.Exit(130)


async def _run_scan_async(path: str, frames: Optional[List[str]], verbose: bool) -> int:
    """Async implementation of scan command."""
    
    console.print(f"[bold cyan]🛡️  Warden Scanner[/bold cyan]")
    console.print(f"[dim]Scanning: {path}[/dim]\n")

    # Initialize bridge
    bridge = WardenBridge(project_root=Path.cwd())
    
    # Setup stats tracking
    stats = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "total": 0
    }

    try:
        # Execute pipeline with streaming
        async for event in bridge.execute_pipeline_stream(
            file_path=path,
            frames=frames,
            verbose=verbose
        ):
            event_type = event.get("type")
            
            if event_type == "progress":
                evt = event['event']
                data = event.get('data', {})

                if evt == "phase_started":
                    console.print(f"[bold blue]▶ Phase:[/bold blue] {data.get('phase')}")
                
                elif evt == "frame_completed":
                    stats["total"] += 1
                    status = data.get('status', 'unknown')
                    name = data.get('frame_name', 'Unknown')
                    
                    if status == "passed":
                        stats["passed"] += 1
                        icon = "✅"
                        style = "green"
                    elif status == "failed":
                        stats["failed"] += 1
                        icon = "❌"
                        style = "red"
                    else:
                        stats["skipped"] += 1
                        icon = "⏭️"
                        style = "yellow"
                        
                    console.print(f"  {icon} [{style}]{name}[/{style}] ({data.get('duration', 0):.2f}s) - {data.get('issues_found', 0)} issues")

            elif event_type == "result":
                # Final results
                res = event['data']
                
                # Check critical findings
                critical = res.get('critical_findings', 0)
                
                table = Table(title="Scan Results")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="magenta")
                
                table.add_row("Total Frames", str(res.get('total_frames', 0)))
                table.add_row("Passed", f"[green]{res.get('frames_passed', 0)}[/green]")
                table.add_row("Failed", f"[red]{res.get('frames_failed', 0)}[/red]")
                table.add_row("Total Issues", str(res.get('total_findings', 0)))
                table.add_row("Critical Issues", f"[{'red' if critical > 0 else 'green'}]{critical}[/]")
                
                console.print("\n", table)
                
                if res.get('status') == 'success':
                    console.print(f"\n[bold green]✨ Scan Succeeded![/bold green]")
                    return 0
                else:
                    console.print(f"\n[bold red]💥 Scan Failed![/bold red]")
                    return 1

        return 0
        
    except Exception as e:
        console.print(f"[bold red]Error during scan:[/bold red] {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return 1


@serve_app.command("ipc")
def serve_ipc():
    """Start the IPC server (used by CLI/GUI integration)."""
    try:
        asyncio.run(ipc_main())
    except KeyboardInterrupt:
        pass


@serve_app.command("grpc")
def serve_grpc(port: int = typer.Option(50051, help="Port to listen on")):
    """Start the gRPC server (for C#/.NET integration)."""
    try:
        asyncio.run(grpc_main(port))
    except KeyboardInterrupt:
        pass


# =============================================================================
# Spec Commands - API Contract Analysis
# =============================================================================

@spec_app.callback(invoke_without_command=True)
def spec_default(ctx: typer.Context):
    """
    API Contract Specification Analysis.

    Extract and compare API contracts between frontend/backend platforms.
    Run 'warden spec --help' to see available subcommands.
    """
    if ctx.invoked_subcommand is None:
        # Default behavior: run analysis
        console.print("[bold blue]🔍 Warden Spec - API Contract Analysis[/bold blue]")
        console.print("[dim]Use 'warden spec --help' to see available commands[/dim]\n")
        console.print("Available commands:")
        console.print("  [cyan]analyze[/cyan]   - Run full gap analysis between platforms")
        console.print("  [cyan]extract[/cyan]   - Extract contract from a single platform")
        console.print("  [cyan]compare[/cyan]   - Compare two contract files")
        console.print("  [cyan]list[/cyan]      - List configured platforms")


@spec_app.command("analyze")
def spec_analyze(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to warden config file"),
    consumer: Optional[str] = typer.Option(None, "--consumer", help="Consumer platform name"),
    provider: Optional[str] = typer.Option(None, "--provider", help="Provider platform name"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file (json/yaml/sarif)"),
    sarif: bool = typer.Option(False, "--sarif", help="Output in SARIF format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """
    Run gap analysis between consumer and provider platforms.

    Examples:
        warden spec analyze
        warden spec analyze --consumer mobile --provider backend
        warden spec analyze -o gaps.json
        warden spec analyze --sarif -o report.sarif
    """
    try:
        exit_code = asyncio.run(_run_spec_analyze(config, consumer, provider, output, sarif, verbose))
        if exit_code != 0:
            raise typer.Exit(exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Analysis interrupted[/yellow]")
        raise typer.Exit(130)


async def _run_spec_analyze(
    config_path: Optional[str],
    consumer_name: Optional[str],
    provider_name: Optional[str],
    output_path: Optional[str],
    sarif_format: bool,
    verbose: bool,
) -> int:
    """Async implementation of spec analyze."""
    from warden.validation.frames.spec import (
        SpecFrame,
        GapAnalyzer,
        GapSeverity,
        PlatformConfig,
        PlatformRole,
        generate_sarif_report,
    )
    from warden.validation.frames.spec.extractors.base import get_extractor
    import yaml
    import json

    console.print("[bold cyan]🔍 Warden Spec Analysis[/bold cyan]\n")

    # Load config
    config_file = Path(config_path) if config_path else Path.cwd() / ".warden" / "config.yaml"

    if not config_file.exists():
        console.print(f"[red]❌ Config file not found:[/red] {config_file}")
        console.print("[dim]Create .warden/config.yaml with platforms configuration[/dim]")
        return 1

    try:
        with open(config_file) as f:
            config = yaml.safe_load(f) or {}
    except Exception as e:
        console.print(f"[red]❌ Failed to load config:[/red] {e}")
        return 1

    # Get spec frame config
    frame_config = config.get("frames", {}).get("spec", {})
    platforms_data = frame_config.get("platforms", [])

    if not platforms_data:
        console.print("[red]❌ No platforms configured[/red]")
        console.print("[dim]Add 'platforms' to frames.spec in .warden/config.yaml[/dim]")
        return 1

    # Parse platforms
    platforms = []
    for p in platforms_data:
        try:
            platforms.append(PlatformConfig.from_dict(p))
        except Exception as e:
            console.print(f"[yellow]⚠️  Invalid platform config:[/yellow] {e}")

    # Filter platforms if specified
    consumers = [p for p in platforms if p.role == PlatformRole.CONSUMER]
    providers = [p for p in platforms if p.role == PlatformRole.PROVIDER]

    if consumer_name:
        consumers = [p for p in consumers if p.name == consumer_name]
    if provider_name:
        providers = [p for p in providers if p.name == provider_name]

    if not consumers:
        console.print("[red]❌ No consumer platform found[/red]")
        return 1
    if not providers:
        console.print("[red]❌ No provider platform found[/red]")
        return 1

    # Show platforms
    table = Table(title="Configured Platforms")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Role", style="green")
    table.add_column("Path")

    for p in consumers + providers:
        role_style = "blue" if p.role == PlatformRole.CONSUMER else "yellow"
        table.add_row(p.name, p.platform_type.value, f"[{role_style}]{p.role.value}[/]", p.path)

    console.print(table)
    console.print()

    # Extract contracts
    all_gaps = []
    all_results = []

    for consumer in consumers:
        console.print(f"[bold]Extracting from consumer:[/bold] {consumer.name}")

        consumer_path = Path(consumer.path)
        if not consumer_path.is_absolute():
            consumer_path = Path.cwd() / consumer.path

        consumer_extractor = get_extractor(consumer.platform_type, consumer_path, consumer.role)
        if not consumer_extractor:
            console.print(f"[yellow]  ⚠️  No extractor for {consumer.platform_type.value}[/yellow]")
            continue

        try:
            consumer_contract = await consumer_extractor.extract()
            consumer_contract.name = consumer.name
            console.print(f"  [green]✓[/green] Extracted {len(consumer_contract.operations)} operations, {len(consumer_contract.models)} models")
        except Exception as e:
            console.print(f"  [red]✗[/red] Extraction failed: {e}")
            continue

        for provider in providers:
            console.print(f"[bold]Extracting from provider:[/bold] {provider.name}")

            provider_path = Path(provider.path)
            if not provider_path.is_absolute():
                provider_path = Path.cwd() / provider.path

            provider_extractor = get_extractor(provider.platform_type, provider_path, provider.role)
            if not provider_extractor:
                console.print(f"[yellow]  ⚠️  No extractor for {provider.platform_type.value}[/yellow]")
                continue

            try:
                provider_contract = await provider_extractor.extract()
                provider_contract.name = provider.name
                console.print(f"  [green]✓[/green] Extracted {len(provider_contract.operations)} operations, {len(provider_contract.models)} models")
            except Exception as e:
                console.print(f"  [red]✗[/red] Extraction failed: {e}")
                continue

            # Analyze gaps
            console.print(f"\n[bold]Analyzing gaps:[/bold] {consumer.name} ↔ {provider.name}")

            analyzer = GapAnalyzer()
            result = analyzer.analyze(
                consumer_contract,
                provider_contract,
                consumer.name,
                provider.name,
            )

            all_results.append(result)
            all_gaps.extend(result.gaps)

            # Show summary
            console.print(f"  Matched: [green]{result.matched_operations}[/green]")
            console.print(f"  Missing: [red]{result.missing_operations}[/red]")
            console.print(f"  Unused:  [yellow]{result.unused_operations}[/yellow]")
            console.print(f"  Type mismatches: [magenta]{result.type_mismatches}[/magenta]")

    # Show gaps
    if all_gaps:
        console.print(f"\n[bold red]Found {len(all_gaps)} gaps:[/bold red]\n")

        # Group by severity
        critical = [g for g in all_gaps if g.severity == GapSeverity.CRITICAL]
        high = [g for g in all_gaps if g.severity == GapSeverity.HIGH]
        medium = [g for g in all_gaps if g.severity == GapSeverity.MEDIUM]
        low = [g for g in all_gaps if g.severity == GapSeverity.LOW]

        for severity, gaps, style in [
            ("CRITICAL", critical, "red"),
            ("HIGH", high, "yellow"),
            ("MEDIUM", medium, "magenta"),
            ("LOW", low, "dim"),
        ]:
            if gaps:
                console.print(f"[bold {style}]{severity} ({len(gaps)}):[/bold {style}]")
                for gap in gaps[:10 if not verbose else None]:  # Limit if not verbose
                    console.print(f"  [{style}]•[/{style}] {gap.message}")
                    if gap.detail and verbose:
                        console.print(f"    [dim]{gap.detail}[/dim]")
                if len(gaps) > 10 and not verbose:
                    console.print(f"  [dim]... and {len(gaps) - 10} more[/dim]")
                console.print()
    else:
        console.print("\n[bold green]✨ No gaps found! Contracts are in sync.[/bold green]")

    # Output to file
    if output_path:
        output_file = Path(output_path)

        # SARIF format
        if sarif_format or output_file.suffix == ".sarif":
            # Generate SARIF for each result
            if all_results:
                sarif_data = generate_sarif_report(
                    all_results[0],  # Primary result
                    project_root=Path.cwd(),
                )
                with open(output_file, "w") as f:
                    json.dump(sarif_data, f, indent=2)
                console.print(f"\n[green]📄 SARIF report saved to {output_path}[/green]")
            else:
                console.print("[yellow]⚠️  No results to generate SARIF report[/yellow]")
        # YAML format
        elif output_file.suffix in [".yaml", ".yml"]:
            output_data = {
                "timestamp": datetime.now().isoformat(),
                "summary": {
                    "total_gaps": len(all_gaps),
                    "critical": len([g for g in all_gaps if g.severity == GapSeverity.CRITICAL]),
                    "high": len([g for g in all_gaps if g.severity == GapSeverity.HIGH]),
                    "medium": len([g for g in all_gaps if g.severity == GapSeverity.MEDIUM]),
                    "low": len([g for g in all_gaps if g.severity == GapSeverity.LOW]),
                },
                "gaps": [g.to_finding_dict() for g in all_gaps],
            }
            with open(output_file, "w") as f:
                yaml.dump(output_data, f, default_flow_style=False)
            console.print(f"\n[green]📄 Results saved to {output_path}[/green]")
        # JSON format (default)
        else:
            output_data = {
                "timestamp": datetime.now().isoformat(),
                "summary": {
                    "total_gaps": len(all_gaps),
                    "critical": len([g for g in all_gaps if g.severity == GapSeverity.CRITICAL]),
                    "high": len([g for g in all_gaps if g.severity == GapSeverity.HIGH]),
                    "medium": len([g for g in all_gaps if g.severity == GapSeverity.MEDIUM]),
                    "low": len([g for g in all_gaps if g.severity == GapSeverity.LOW]),
                },
                "gaps": [g.to_finding_dict() for g in all_gaps],
            }
            with open(output_file, "w") as f:
                json.dump(output_data, f, indent=2)
            console.print(f"\n[green]📄 Results saved to {output_path}[/green]")

    # Return exit code
    if any(g.severity == GapSeverity.CRITICAL for g in all_gaps):
        return 1
    return 0


@spec_app.command("extract")
def spec_extract(
    path: str = typer.Argument(".", help="Path to project to extract from"),
    platform: str = typer.Option(..., "--platform", "-p", help="Platform type (flutter, react, express, etc.)"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file (json/yaml)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
):
    """
    Extract API contract from a single platform/project.

    Examples:
        warden spec extract ./mobile-app --platform flutter
        warden spec extract ./backend --platform express -o contract.json
    """
    try:
        exit_code = asyncio.run(_run_spec_extract(path, platform, output, verbose))
        if exit_code != 0:
            raise typer.Exit(exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Extraction interrupted[/yellow]")
        raise typer.Exit(130)


async def _run_spec_extract(
    path: str,
    platform: str,
    output_path: Optional[str],
    verbose: bool,
) -> int:
    """Async implementation of spec extract."""
    from warden.validation.frames.spec import PlatformType, PlatformRole
    from warden.validation.frames.spec.extractors.base import get_extractor
    import yaml
    import json

    console.print("[bold cyan]📦 Warden Contract Extraction[/bold cyan]\n")

    project_path = Path(path).resolve()
    if not project_path.exists():
        console.print(f"[red]❌ Path not found:[/red] {project_path}")
        return 1

    # Parse platform type
    try:
        platform_type = PlatformType(platform.lower())
    except ValueError:
        console.print(f"[red]❌ Unknown platform:[/red] {platform}")
        console.print(f"[dim]Available: {', '.join(p.value for p in PlatformType)}[/dim]")
        return 1

    console.print(f"Platform: [cyan]{platform_type.value}[/cyan]")
    console.print(f"Path: [dim]{project_path}[/dim]\n")

    # Determine role based on platform type
    consumer_platforms = {"flutter", "react", "react-native", "angular", "vue", "swift", "kotlin"}
    role = PlatformRole.CONSUMER if platform_type.value in consumer_platforms else PlatformRole.PROVIDER

    # Get extractor
    extractor = get_extractor(platform_type, project_path, role)
    if not extractor:
        console.print(f"[red]❌ No extractor available for {platform_type.value}[/red]")
        return 1

    # Extract
    console.print("[bold]Extracting contract...[/bold]")

    try:
        contract = await extractor.extract()
        contract.name = project_path.name
    except Exception as e:
        console.print(f"[red]❌ Extraction failed:[/red] {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return 1

    # Show results
    console.print(f"\n[green]✓ Extraction complete[/green]")
    console.print(f"  Operations: [cyan]{len(contract.operations)}[/cyan]")
    console.print(f"  Models: [cyan]{len(contract.models)}[/cyan]")
    console.print(f"  Enums: [cyan]{len(contract.enums)}[/cyan]")

    if verbose:
        if contract.operations:
            console.print("\n[bold]Operations:[/bold]")
            for op in contract.operations:
                op_type = f"[blue]{op.operation_type.value}[/blue]"
                console.print(f"  • {op.name} ({op_type})")
                if op.description:
                    console.print(f"    [dim]{op.description}[/dim]")

        if contract.models:
            console.print("\n[bold]Models:[/bold]")
            for model in contract.models:
                console.print(f"  • {model.name} ({len(model.fields)} fields)")

    # Output to file
    if output_path:
        output_data = contract.to_dict()
        output_data["_meta"] = {
            "name": contract.name,
            "platform": platform_type.value,
            "extracted_at": datetime.now().isoformat(),
        }

        output_file = Path(output_path)
        if output_file.suffix in [".yaml", ".yml"]:
            with open(output_file, "w") as f:
                yaml.dump(output_data, f, default_flow_style=False)
        else:
            with open(output_file, "w") as f:
                json.dump(output_data, f, indent=2)

        console.print(f"\n[green]📄 Contract saved to {output_path}[/green]")

    return 0


@spec_app.command("list")
def spec_list(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to warden config file"),
):
    """
    List configured platforms from .warden/config.yaml.

    Examples:
        warden spec list
        warden spec list --config ./custom-config.yaml
    """
    import yaml
    from warden.validation.frames.spec import PlatformConfig, PlatformRole

    # Load config
    config_file = Path(config) if config else Path.cwd() / ".warden" / "config.yaml"

    if not config_file.exists():
        console.print(f"[red]❌ Config file not found:[/red] {config_file}")
        console.print("\n[dim]Create .warden/config.yaml with the following structure:[/dim]")
        console.print("""
[cyan]frames:
  spec:
    platforms:
      - name: mobile
        path: ../mobile-app
        type: flutter
        role: consumer
      - name: backend
        path: ../backend-api
        type: express
        role: provider[/cyan]
""")
        raise typer.Exit(1)

    try:
        with open(config_file) as f:
            config_data = yaml.safe_load(f) or {}
    except Exception as e:
        console.print(f"[red]❌ Failed to load config:[/red] {e}")
        raise typer.Exit(1)

    # Get platforms
    frame_config = config_data.get("frames", {}).get("spec", {})
    platforms_data = frame_config.get("platforms", [])

    if not platforms_data:
        console.print("[yellow]⚠️  No platforms configured[/yellow]")
        console.print("[dim]Add 'platforms' to frames.spec in .warden/config.yaml[/dim]")
        raise typer.Exit(0)

    # Show table
    table = Table(title="Configured Platforms")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Role")
    table.add_column("Path")
    table.add_column("Status")

    for p in platforms_data:
        try:
            platform = PlatformConfig.from_dict(p)
            role_style = "blue" if platform.role == PlatformRole.CONSUMER else "yellow"

            # Check if path exists
            platform_path = Path(platform.path)
            if not platform_path.is_absolute():
                platform_path = Path.cwd() / platform.path

            status = "[green]✓[/green]" if platform_path.exists() else "[red]✗ not found[/red]"

            table.add_row(
                platform.name,
                platform.platform_type.value,
                f"[{role_style}]{platform.role.value}[/]",
                platform.path,
                status,
            )
        except Exception as e:
            table.add_row(
                p.get("name", "?"),
                p.get("type", "?"),
                p.get("role", "?"),
                p.get("path", "?"),
                f"[red]✗ {e}[/red]",
            )

    console.print(table)

    # Show supported platforms
    from warden.validation.frames.spec import PlatformType
    console.print("\n[dim]Supported platform types:[/dim]")
    console.print(f"[dim]{', '.join(p.value for p in PlatformType)}[/dim]")


def main():
    """Entry point for setuptools."""
    app()


if __name__ == "__main__":
    app()
