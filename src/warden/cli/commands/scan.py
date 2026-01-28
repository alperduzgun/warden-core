import asyncio
import typer
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

# Internal imports
from warden.cli_bridge.bridge import WardenBridge

console = Console()


async def _generate_smart_failure_summary(critical_count: int, frames_failed: int, result_data: dict) -> None:
    """
    Generate an intelligent failure summary using Local LLM if available.
    """
    try:
        # Check if Local LLM is available (Fast Tier)
        # We can reuse the bridge check or try to instantiate a lightweight client
        from warden.llm.factory import create_client
        client = create_client()
        
        # 1. Check availability first (Fail fast)
        if not await client.is_available_async():
            # console.print("[dim]Local AI unavailable, skipping analysis.[/dim]")
            return

        console.print("\n[dim]🤔 Analyzing failure reason with Local AI (timeout: 5s)...[/dim]")
        
        # 2. Aggregate Findings
        findings = []
        frame_results = result_data.get('frame_results', result_data.get('frameResults', []))
        for frame in frame_results:
            findings.extend(frame.get('findings', []))
        categories = {}
        
        # If too many findings, limit to critical ones
        critical_findings = [f for f in findings if str(f.get('severity')).upper() == 'CRITICAL']
        if not critical_findings:
            critical_findings = findings[:50] # Fallback to top 50 if no explicit critical tag
            
        for f in critical_findings:
            cat = f.get('category', 'General')
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(f)
            
        # 3. Prepare Context (Sampled)
        summary_context = f"""
        Scan Failed.
        Stats: {critical_count} critical issues, {frames_failed} failed frames.
        
        Top Issue Categories:
        """
        
        for cat, items in list(categories.items())[:5]: # Top 5 categories
            check = items[0]
            summary_context += f"\n- {cat} ({len(items)} occurrences)\n"
            summary_context += f"  Example: {check.get('message')} at {check.get('file_path')}:{check.get('line_number')}\n"

        # 4. Ask LLM with strict Timeout
        prompt = f"""
        Analyze this security scan failure and provide a concise EXECUTIVE SUMMARY (max 3 sentences).
        Explain WHY the build failed and WHAT is the most important action to take.
        Do not list all issues. Focus on patterns.
        
        CONTEXT:
        {summary_context}
        """
        
        # Enforce 5s timeout to avoid blocking CI
        response = await asyncio.wait_for(
            client.complete_async(
                prompt, 
                system_prompt="You are a warm, helpful DevSecOps assistant. Explain failures clearly.",
                use_fast_tier=True # Force Fast Tier (Qwen)
            ),
            timeout=5.0
        )
        
        console.print("\n[bold red]🤖 Qwen Analysis:[/bold red]")
        console.print(f"[white]{response.content}[/white]")
        
    except asyncio.TimeoutError:
        console.print("\n[dim]⚠️  AI Analysis timed out (skipped)[/dim]")
    except Exception:
        # Silent fail - this is an enhancement, not a critical path
        # console.print(f"[dim]AI Analysis unavailable: {e}[/dim]")
        pass

def _display_llm_summary(metrics: dict):
    """Display LLM performance summary in CLI."""
    console.print("\n[bold cyan]🤖 LLM Performance Summary[/bold cyan]")
    
    total_time = metrics.get("totalTime", "N/A")
    total_requests = metrics.get("totalRequests", 0)
    console.print(f"  Total LLM Requests: {total_requests}")
    console.print(f"  Total LLM Time: {total_time}")
    
    if metrics.get("fastTier"):
        fast = metrics["fastTier"]
        console.print("\n  [green]⚡ Fast Tier (Qwen):[/green]")
        console.print(f"    Requests: {fast['requests']} ({fast['percentage']}%)")
        console.print(f"    Success Rate: {fast['successRate']}%")
        console.print(f"    Avg Response: {fast['avgResponseTime']}")
        console.print(f"    Total Time: {fast['totalTime']} ({fast['timePercentage']}% of total)")
        if fast.get('timeouts', 0) > 0:
            console.print(f"    [yellow]⚠️  Timeouts: {fast['timeouts']}[/yellow]")
    
    if metrics.get("smartTier"):
        smart = metrics["smartTier"]
        console.print("\n  [blue]🧠 Smart Tier (Azure):[/blue]")
        console.print(f"    Requests: {smart['requests']} ({smart['percentage']}%)")
        console.print(f"    Avg Response: {smart['avgResponseTime']}")
        console.print(f"    Total Time: {smart['totalTime']} ({smart['timePercentage']}% of total)")
    
    if metrics.get("costAnalysis"):
        cost = metrics["costAnalysis"]
        console.print("\n  [bold green]💰 Savings:[/bold green]")
        console.print(f"    Cost: {cost['estimatedCostSavings']}")
        console.print(f"    Time: {cost['estimatedTimeSavings']}")
    
    if metrics.get("issues"):
        console.print("\n  [yellow]⚠️  Performance Issues:[/yellow]")
        for issue in metrics["issues"]:
            console.print(f"    - {issue['message']}")
            if issue.get('recommendations'):
                for rec in issue['recommendations']:
                    console.print(f"      → {rec}")


def _display_memory_stats(snapshot) -> None:
    """Display memory profiling statistics."""
    console.print("\n[bold cyan]🧠 Memory Profiling Results[/bold cyan]")
    
    # Get top 10 memory consumers
    top_stats = snapshot.statistics('lineno')[:10]
    
    console.print("\n[bold]Top 10 Memory Allocations:[/bold]")
    for index, stat in enumerate(top_stats, 1):
        console.print(f"  {index}. {stat.traceback.format()[0]}")
        console.print(f"     Size: {stat.size / 1024 / 1024:.2f} MB ({stat.count} blocks)")
    
    # Total memory usage
    total = sum(stat.size for stat in snapshot.statistics('filename'))
    console.print(f"\n[bold]Total Memory Usage:[/bold] {total / 1024 / 1024:.2f} MB")
    
    # Check for potential leaks (allocations > 10MB)
    large_allocations = [s for s in top_stats if s.size > 10 * 1024 * 1024]
    if large_allocations:
        console.print(f"\n[yellow]⚠️  Potential Memory Leaks Detected:[/yellow]")
        for stat in large_allocations:
            console.print(f"  - {stat.traceback.format()[0]}: {stat.size / 1024 / 1024:.2f} MB")


def scan_command(
    ctx: typer.Context,
    paths: List[str] = typer.Argument(None, help="Paths to scan (files or directories). Defaults to ."),
    frames: Optional[List[str]] = typer.Option(None, "--frame", "-f", help="Specific frames to run"),
    format: str = typer.Option("text", "--format", help="Output format: text, json, sarif, junit, html, pdf"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed logs"),
    level: str = typer.Option("standard", "--level", help="Analysis level: basic, standard, deep"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Shorthand for --level basic"),
    memory_profile: bool = typer.Option(False, "--memory-profile", help="Enable memory profiling and leak detection"),
    ci: bool = typer.Option(False, "--ci", help="CI mode: read-only, optimized for CI/CD pipelines"),
    diff: bool = typer.Option(False, "--diff", help="Scan only files changed relative to base branch"),
    base: str = typer.Option("main", "--base", help="Base branch for diff comparison (default: main)"),
) -> None:
    """
    Run the full Warden pipeline on files or directories.
    """
    # We defer import to avoid slow startup for other commands
    
    # Start memory profiling if requested
    if memory_profile:
        import tracemalloc
        tracemalloc.start()
        console.print("[dim]🧠 Memory profiling enabled[/dim]\n")
    
    # Run async scan function
    try:
        # Handle --no-ai shorthand
        if no_ai:
            level = "basic"

        # Default to "." if no paths provided AND no diff mode
        if not paths and not diff:
            paths = ["."]

        # Incremental Scanning Logic (--diff mode)
        baseline_fingerprints = None

        if diff:
            try:
                from warden.cli.commands.helpers.git_helper import GitHelper
                console.print(f"[dim]🔍 Detecting changed files relative to '{base}'...[/dim]")
                git_helper = GitHelper(Path.cwd())
                changed_files = git_helper.get_changed_files(base_branch=base)

                if not changed_files:
                    console.print("[yellow]⚠️  No changed files detected. Scan skipped.[/yellow]")
                    return

                console.print(f"[green]✓ Found {len(changed_files)} changed files[/green]")
                paths = changed_files
            except ImportError:
                console.print("[yellow]⚠️  Git helper not available. Running full scan.[/yellow]")
            except Exception as e:
                console.print(f"[yellow]⚠️  Could not detect changes: {e}. Running full scan.[/yellow]")

        # Load baseline fingerprints if available
        try:
            from warden.cli.commands.helpers.baseline_manager import BaselineManager
            baseline_mgr = BaselineManager(Path.cwd())
            baseline_fingerprints = baseline_mgr.get_fingerprints()
            if baseline_fingerprints:
                console.print(f"[dim]📊 Baseline loaded: {len(baseline_fingerprints)} known issues[/dim]")
        except Exception:
            pass  # Baseline is optional

        # Load pre-computed intelligence in CI mode
        intelligence_context = None
        if ci:
            try:
                from warden.analysis.services.intelligence_loader import IntelligenceLoader
                intel_loader = IntelligenceLoader(Path.cwd())
                if intel_loader.load():
                    intelligence_context = intel_loader.to_context_dict()
                    quality = intel_loader.get_quality_score()
                    modules = len(intel_loader.get_module_map())
                    posture = intel_loader.get_security_posture().value
                    console.print(f"[dim]🧠 Intelligence loaded: {modules} modules, quality={quality}/100, posture={posture}[/dim]")
                else:
                    console.print("[yellow]⚠️  No pre-computed intelligence found. Run 'warden init' first for optimal CI performance.[/yellow]")
            except ImportError:
                console.print("[dim]Intelligence loader not available[/dim]")
            except Exception as e:
                console.print(f"[yellow]⚠️  Intelligence load failed: {e}[/yellow]")

        exit_code = asyncio.run(_run_scan_async(
            paths, frames, format, output, verbose, level,
            memory_profile, ci, baseline_fingerprints, intelligence_context
        ))
        
        # Display memory stats if profiling was enabled
        if memory_profile:
            import tracemalloc
            snapshot = tracemalloc.take_snapshot()
            _display_memory_stats(snapshot)
            tracemalloc.stop()
        
        if exit_code != 0:
            raise typer.Exit(exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Scan interrupted by user[/yellow]")
        raise typer.Exit(130)


async def _run_scan_async(
    paths: List[str],
    frames: Optional[List[str]],
    format: str,
    output: Optional[str],
    verbose: bool,
    level: str = "standard",
    memory_profile: bool = False,
    ci_mode: bool = False,
    baseline_fingerprints: Optional[Dict[str, str]] = None,
    intelligence_context: Optional[Dict] = None
) -> int:
    """Async implementation of scan command."""
    
    display_paths = f"{paths[0]} + {len(paths)-1} others" if len(paths) > 1 else str(paths[0])
    console.print("[bold cyan]🛡️  Warden Scanner[/bold cyan]")
    console.print(f"[dim]Scanning: {display_paths}[/dim]")

    # Show intelligence status in CI mode
    if ci_mode and intelligence_context:
        if intelligence_context.get("available"):
            quality = intelligence_context.get("quality_score", 0)
            modules = len(intelligence_context.get("modules", {}))
            console.print(f"[dim]🧠 Using pre-computed intelligence ({modules} modules, quality: {quality}/100)[/dim]")
        else:
            console.print("[yellow]⚠️  No intelligence available - consider running 'warden init'[/yellow]")

    console.print()

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

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        "[progress.percentage]{task.percentage:>3.0f}%",
        "•",
        TextColumn("[dim]{task.fields[status]}"),
        TimeElapsedColumn(),
        console=console,
        transient=True
    )

    overall_task = None
    current_phase_task = None

    try:
        with progress:
            # Execute pipeline with streaming
            async for event in bridge.execute_pipeline_stream_async(
                file_path=paths,
                frames=frames,
                verbose=verbose,
                analysis_level=level,
                ci_mode=ci_mode
            ):
                event_type = event.get("type")
                
                if event_type == "progress":
                    evt = event['event']
                    data = event.get('data', {})

                    if evt == "progress_init":
                        overall_task = progress.add_task("Overall Progress", total=data['total_units'], status="Initializing...")
                    
                    elif evt == "progress_update" and overall_task is not None:
                        increment = data.get('increment', 0)
                        status = data.get('status', data.get('phase', 'Processing...'))
                        progress.update(overall_task, advance=increment, status=status)
                        
                        # Handle dynamic unit addition (e.g. Analysis/Verification finding counts)
                        if "total_units" in data:
                            # Safe task retrieval to avoid IndexError
                            task = next((t for t in progress.tasks if t.id == overall_task), None)
                            if task:
                                progress.update(overall_task, total=task.total + data['total_units'])

                    if format == "text":
                        if evt == "phase_started":
                            phase_name = data.get('phase')
                            if not verbose:
                                if current_phase_task is not None:
                                    progress.remove_task(current_phase_task)
                                current_phase_task = progress.add_task(f"Phase: {phase_name}", total=None, status="In Progress")
                            else:
                                console.print(f"[bold blue]▶ Phase:[/bold blue] {phase_name}")
                        
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
                                
                            if verbose:
                                console.print(f"  {icon} [{style}]{name}[/{style}] ({data.get('duration', 0):.2f}s) - {findings_count} issues")

                elif event_type == "result":
                    # Final results
                    final_result_data = event['data']
                    res = final_result_data
                    
                    # Check critical findings
                    critical = res.get('critical_findings', 0)
                
                    if format == "text":
                        # Segregate Findings (Linter vs Core)
                        all_findings = res.get('findings', [])
                        linter_findings = []
                        core_findings = []
                        
                        for f in all_findings:
                            # Robust check for Linter source
                            detail = f.get('detail') or ""
                            if "(Ruff)" in detail or str(f.get('id', '')).startswith("lint_"):
                                linter_findings.append(f)
                            else:
                                core_findings.append(f)
                                
                        # Recalculate stats for cleaner report
                        core_count = len(core_findings)
                        core_critical = sum(1 for f in core_findings if str(f.get('severity')).lower() == 'critical')
                        
                        linter_count = len(linter_findings)
                        linter_critical = sum(1 for f in linter_findings if str(f.get('severity')).lower() == 'critical')

                        table = Table(title="Scan Results")
                        table.add_column("Metric", style="cyan")
                        table.add_column("Value", style="magenta")
                        
                        table.add_row("Total Frames", str(res.get('total_frames', 0)))
                        table.add_row("Passed", f"[green]{res.get('frames_passed', 0)}[/green]")
                        table.add_row("Failed", f"[red]{res.get('frames_failed', 0)}[/red]")
                        
                        # Primary focus: Core Issues (Logic, Security, Architecture from AI/Frames)
                        table.add_section()
                        table.add_row("Core Issues", str(core_count))
                        table.add_row("Critical Core Issues", f"[{'red' if core_critical > 0 else 'green'}]{core_critical}[/]")
                        
                        # Secondary focus: Linter Issues (Style, minor errors)
                        if linter_count > 0:
                            table.add_section()
                            style = "yellow" if linter_critical > 0 else "dim"
                            table.add_row("Linter Issues", f"[{style}]{linter_count}[/{style}]")
                            if linter_critical > 0:
                                table.add_row("Linter Critical", f"[red]{linter_critical}[/red]")
                        
                        # Add Manual Review if present
                        manual_review = res.get('manual_review_findings', 0)
                        if manual_review > 0:
                            table.add_row("Manual Review", f"[yellow]{manual_review}[/yellow]")
                        
                        console.print("\n", table)

                        # 🚨 NEW: Show Missing Tool Hints (Visibility Improvement)
                        # Check all frames results (if available in result_data or we need to access them differently)
                        # Wait, result_data contains 'frames_failed' but not detailed skipped info easily.
                        # Actually 'stats' object in this function tracks skipped counts, but we don't have the frame objects there locally?
                        # We need to rely on the streaming events we processed? Or the final result structure.
                        # Assuming final_result_data['results'] contains detailed frame results.
                        
                        frame_results = res.get('results', [])
                        missing_tools = []
                        for fr in frame_results:
                            meta = fr.get('metadata', {}) or {}
                            if meta.get('status') == 'skipped_tool_missing':
                                hint = meta.get('install_hint')
                                frame_name = fr.get('frame_name', 'Unknown Frame')
                                if hint:
                                    missing_tools.append((frame_name, hint))
                        
                        if missing_tools:
                            console.print("\n[bold yellow]⚠️  Missing Dependencies (Action Required):[/bold yellow]")
                            for name, hint in missing_tools:
                                console.print(f"  • [cyan]{name}[/cyan]: {hint}")
                            console.print("")

                        
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
                            console.print("\n[bold green]✨ Scan Succeeded![/bold green]")
                        else:
                            console.print("\n[bold red]💥 Scan Failed![/bold red]")

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
            
            console.print("[bold green]Report saved![/bold green]")

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
             console.print("[bold red]❌ Pipeline did not complete successfully.[/bold red]")
             return 1
             
        if critical_count > 0:
            console.print(f"[bold red]❌ Scan failed: {critical_count} critical issues found.[/bold red]")
            await _generate_smart_failure_summary(critical_count, frames_failed, final_result_data)
            return 2  # Exit code 2: Policy Failure (Findings found)
            
        if frames_failed > 0:
            console.print(f"[bold red]❌ Scan failed: {frames_failed} frames failed.[/bold red]")
            await _generate_smart_failure_summary(critical_count, frames_failed, final_result_data)
            return 2  # Exit code 2: Policy Failure (Frames failed)

        return 0
        
    except Exception as e:
        console.print("\n[bold red]💥 Scan failed unexpectedly.[/bold red]")
        console.print(f"[red]Error:[/red] {e}")

        # Suggest doctor for likely configuration errors
        if isinstance(e, (AttributeError, ValueError, KeyError, TypeError)):
            console.print("\n[yellow]💡 Tip:[/yellow] This looks like a configuration or environment issue.")
            console.print("Run [bold cyan]warden doctor[/bold cyan] to check your project setup.")

        if verbose:
            import traceback
            traceback.print_exc()
        return 1
