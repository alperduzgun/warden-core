import asyncio
import sys
import typer
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Internal imports
from warden.cli_bridge.bridge import WardenBridge

console = Console()


def _display_llm_summary(metrics: dict):
    """Display LLM performance summary in CLI."""
    console.print("\n[bold cyan]🤖 LLM Performance Summary[/bold cyan]")
    
    total_time = metrics.get("totalTime", "N/A")
    total_requests = metrics.get("totalRequests", 0)
    console.print(f"  Total LLM Requests: {total_requests}")
    console.print(f"  Total LLM Time: {total_time}")
    
    if metrics.get("fastTier"):
        fast = metrics["fastTier"]
        console.print(f"\n  [green]⚡ Fast Tier (Qwen):[/green]")
        console.print(f"    Requests: {fast['requests']} ({fast['percentage']}%)")
        console.print(f"    Success Rate: {fast['successRate']}%")
        console.print(f"    Avg Response: {fast['avgResponseTime']}")
        console.print(f"    Total Time: {fast['totalTime']} ({fast['timePercentage']}% of total)")
        if fast.get('timeouts', 0) > 0:
            console.print(f"    [yellow]⚠️  Timeouts: {fast['timeouts']}[/yellow]")
    
    if metrics.get("smartTier"):
        smart = metrics["smartTier"]
        console.print(f"\n  [blue]🧠 Smart Tier (Azure):[/blue]")
        console.print(f"    Requests: {smart['requests']} ({smart['percentage']}%)")
        console.print(f"    Avg Response: {smart['avgResponseTime']}")
        console.print(f"    Total Time: {smart['totalTime']} ({smart['timePercentage']}% of total)")
    
    if metrics.get("costAnalysis"):
        cost = metrics["costAnalysis"]
        console.print(f"\n  [bold green]💰 Savings:[/bold green]")
        console.print(f"    Cost: {cost['estimatedCostSavings']}")
        console.print(f"    Time: {cost['estimatedTimeSavings']}")
    
    if metrics.get("issues"):
        console.print("\n  [yellow]⚠️  Performance Issues:[/yellow]")
        for issue in metrics["issues"]:
            console.print(f"    - {issue['message']}")
            if issue.get('recommendations'):
                for rec in issue['recommendations']:
                    console.print(f"      → {rec}")


def scan_command(
    ctx: typer.Context,
    paths: List[str] = typer.Argument(None, help="Paths to scan (files or directories). Defaults to ."),
    frames: Optional[List[str]] = typer.Option(None, "--frame", "-f", help="Specific frames to run"),
    format: str = typer.Option("text", "--format", help="Output format: text, json, sarif, junit, html, pdf"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed logs"),
    level: str = typer.Option("standard", "--level", help="Analysis level: basic, standard, deep"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Shorthand for --level basic"),
) -> None:
    """
    Run the full Warden pipeline on files or directories.
    """
    # We defer import to avoid slow startup for other commands
    from warden.shared.infrastructure.logging import get_logger
    
    # Run async scan function
    try:
        # Handle --no-ai shorthand
        if no_ai:
            level = "basic"
            
        # Default to "." if no paths provided
        if not paths:
            paths = ["."]

        exit_code = asyncio.run(_run_scan_async(paths, frames, format, output, verbose, level))
        if exit_code != 0:
            raise typer.Exit(exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Scan interrupted by user[/yellow]")
        raise typer.Exit(130)


async def _run_scan_async(paths: List[str], frames: Optional[List[str]], format: str, output: Optional[str], verbose: bool, level: str = "standard") -> int:
    """Async implementation of scan command."""
    
    display_paths = f"{paths[0]} + {len(paths)-1} others" if len(paths) > 1 else str(paths[0])
    console.print(f"[bold cyan]🛡️  Warden Scanner[/bold cyan]")
    console.print(f"[dim]Scanning: {display_paths}[/dim]\n")

    # Initialize bridge
    bridge = WardenBridge(project_root=Path.cwd())
    
    # Setup stats tracking
    stats = {
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "total": 0
    }

    final_result_data = None

    try:
        # Execute pipeline with streaming
        async for event in bridge.execute_pipeline_stream_async(
            file_path=paths,
            frames=frames,
            verbose=verbose,
            analysis_level=level
        ):
            event_type = event.get("type")
            
            if event_type == "progress":
                evt = event['event']
                data = event.get('data', {})

                if format == "text":
                    if evt == "phase_started":
                        console.print(f"[bold blue]▶ Phase:[/bold blue] {data.get('phase')}")
                    
                    elif evt == "frame_completed":
                        stats["total"] += 1
                        name = data.get('frame_name', data.get('frame_id'))
                        status = data.get('status', 'unknown')
                        icon = "✅" if status == "passed" else "❌" if status == "failed" else "⚠️" 
                        style = "green" if status == "passed" else "red" if status == "failed" else "yellow"
                        findings_count = data.get('findings', data.get('issues_found', 0))

                        if status == "passed":
                            stats["passed"] += 1
                        elif status == "failed":
                            stats["failed"] += 1
                        else:
                            stats["skipped"] += 1
                            
                        console.print(f"  {icon} [{style}]{name}[/{style}] ({data.get('duration', 0):.2f}s) - {findings_count} issues")

            elif event_type == "result":
                # Final results
                final_result_data = event['data']
                res = final_result_data
                
                # Check critical findings
                critical = res.get('critical_findings', 0)
                
                if format == "text":
                    table = Table(title="Scan Results")
                    table.add_column("Metric", style="cyan")
                    table.add_column("Value", style="magenta")
                    
                    table.add_row("Total Frames", str(res.get('total_frames', 0)))
                    table.add_row("Passed", f"[green]{res.get('frames_passed', 0)}[/green]")
                    table.add_row("Failed", f"[red]{res.get('frames_failed', 0)}[/red]")
                    table.add_row("Total Issues", str(res.get('total_findings', 0)))
                    table.add_row("Critical Issues", f"[{'red' if critical > 0 else 'green'}]{critical}[/]")
                    
                    console.print("\n", table)
                    
                    # Display LLM Performance Metrics
                    llm_metrics = res.get('llmMetrics', {})
                    if llm_metrics:
                        _display_llm_summary(llm_metrics)
                    
                    # Status check (COMPLETED=2)
                    status_raw = res.get('status')
                    # Handle both integer and string statuses (Enums are often serialized to name or value)
                    is_success = str(status_raw).upper() in ["2", "SUCCESS", "COMPLETED", "PIPELINESTATUS.COMPLETED"]
                    
                    if verbose:
                        console.print(f"[dim]Debug: status={status_raw} ({type(status_raw).__name__}), is_success={is_success}[/dim]")
                    
                    if is_success:
                        console.print(f"\n[bold green]✨ Scan Succeeded![/bold green]")
                    else:
                        console.print(f"\n[bold red]💥 Scan Failed![/bold red]")

            # Report Generation from Config
            if final_result_data:
                try:
                    import yaml
                    from warden.reports.generator import ReportGenerator
                    
                    root_manifest = Path.cwd() / "warden.yaml"
                    legacy_config = Path.cwd() / ".warden" / "config.yaml"
                    config_path = root_manifest if root_manifest.exists() else legacy_config
                    if config_path.exists():
                        with open(config_path) as f:
                            config = yaml.safe_load(f)
                        
                        ci_config = config.get('ci', {})
                        outputs = ci_config.get('output', [])
                        
                        if outputs:
                            console.print("\n[bold]📝 Generating Reports:[/bold]")
                            generator = ReportGenerator()
                            
                            for out in outputs:
                                fmt = out.get('format')
                                path_str = out.get('path')
                                if not fmt or not path_str:
                                    continue
                                    
                                out_path = Path.cwd() / path_str
                                out_path.parent.mkdir(parents=True, exist_ok=True)
                                
                                try:
                                    if fmt == 'json':
                                        generator.generate_json_report(final_result_data, out_path)
                                        console.print(f"  ✅ [cyan]JSON[/cyan]: {path_str}")
                                    elif fmt == 'markdown' or fmt == 'md':
                                        pass
                                    elif fmt == 'sarif':
                                        generator.generate_sarif_report(final_result_data, out_path)
                                        console.print(f"  ✅ [cyan]SARIF[/cyan]: {path_str}")
                                    elif fmt == 'junit':
                                        generator.generate_junit_report(final_result_data, out_path)
                                        console.print(f"  ✅ [cyan]JUnit[/cyan]: {path_str}")
                                    elif fmt == 'html':
                                        generator.generate_html_report(final_result_data, out_path)
                                        console.print(f"  ✅ [cyan]HTML[/cyan]: {path_str}")
                                    elif fmt == 'pdf':
                                        generator.generate_pdf_report(final_result_data, out_path)
                                        console.print(f"  ✅ [cyan]PDF[/cyan]: {path_str}")
                                        
                                except Exception as e:
                                    console.print(f"  ❌ [red]{fmt.upper()}[/red]: Failed - {e}")
                                    if verbose:
                                        console.print(f"     {str(e)}")

                except Exception as e:
                    console.print(f"\n[red]⚠️  Report generation failed: {e}[/red]")
                    if verbose:
                        import traceback
                        traceback.print_exc()

        # Generate report if requested
        if output and final_result_data:
            from warden.reports.generator import ReportGenerator
            generator = ReportGenerator()
            out_path = Path(output)
            
            console.print(f"\n[dim]Generating {format.upper()} report to {output}...[/dim]")
            
            if format == "json":
                generator.generate_json_report(final_result_data, out_path)
            elif format == "sarif":
                generator.generate_sarif_report(final_result_data, out_path)
            elif format == "junit":
                generator.generate_junit_report(final_result_data, out_path)
            elif format == "html":
                generator.generate_html_report(final_result_data, out_path)
            elif format == "pdf":
                generator.generate_pdf_report(final_result_data, out_path)
            
            console.print(f"[bold green]Report saved![/bold green]")

        # Save lightweight AI status file (Token-optimized)
        try:
            warden_dir = Path(".warden")
            if warden_dir.exists():
                status_file = warden_dir / "ai_status.md"
                
                # Status check (COMPLETED=2)
                status_raw = final_result_data.get('status')
                is_success = str(status_raw).upper() in ["2", "SUCCESS", "COMPLETED"]
                status_icon = "✅ PASS" if is_success else "❌ FAIL"
                critical_count = final_result_data.get('critical_findings', 0)
                total_count = final_result_data.get('total_findings', 0)
                scan_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                status_content = f"""# Warden Security Status
Updated: {scan_time}

**Status**: {status_icon}
**Critical Issues**: {critical_count}
**Total Issues**: {total_count}

> [!NOTE]
> If status is FAIL, please check the full report or run `warden scan` for details.
> Do not analyze full code unless you are resolving these specific issues.
"""
                with open(status_file, "w") as f:
                    f.write(status_content)
        except Exception:
            pass # Silent fail for aux file

        # Final exit code decision
        # 1. Check pipeline status (must be valid and completed)
        status_val = final_result_data.get('status')
        pipeline_ok = final_result_data and str(status_val).upper() in ["2", "SUCCESS", "COMPLETED", "PIPELINESTATUS.COMPLETED"]
        
        # 2. Check for critical issues or frame failures
        critical_count = final_result_data.get('critical_findings', 0)
        frames_failed = final_result_data.get('frames_failed', 0)
        
        if not pipeline_ok:
             console.print(f"[bold red]❌ Pipeline did not complete successfully.[/bold red]")
             return 1
             
        if critical_count > 0:
            console.print(f"[bold red]❌ Scan failed: {critical_count} critical issues found.[/bold red]")
            return 1
            
        if frames_failed > 0:
            console.print(f"[bold red]❌ Scan failed: {frames_failed} frames failed.[/bold red]")
            return 1

        return 0
        
    except Exception as e:
        console.print(f"\n[bold red]💥 Scan failed unexpectedly.[/bold red]")
        console.print(f"[red]Error:[/red] {e}")

        # Suggest doctor for likely configuration errors
        if isinstance(e, (AttributeError, ValueError, KeyError, TypeError)):
            console.print("\n[yellow]💡 Tip:[/yellow] This looks like a configuration or environment issue.")
            console.print("Run [bold cyan]warden doctor[/bold cyan] to check your project setup.")

        if verbose:
            import traceback
            traceback.print_exc()
        return 1
