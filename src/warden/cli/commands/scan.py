import asyncio
import typer
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
from rich.console import Console
from rich.table import Table

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
        from warden.shared.utils.prompt_sanitizer import PromptSanitizer
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

        # 3. Prepare Context (Sampled) - SANITIZED to prevent prompt injection
        context_parts = [
            f"Scan Failed.",
            f"Stats: {critical_count} critical issues, {frames_failed} failed frames.",
            "",
            "Top Issue Categories:"
        ]

        for cat, items in list(categories.items())[:5]: # Top 5 categories
            check = items[0]
            # Sanitize all user-controlled strings (category, message, file_path)
            # Fail-safe: If sanitizer fails, redact entirely
            try:
                safe_cat = PromptSanitizer.escape_prompt_injection(str(cat))
            except Exception:
                safe_cat = "[REDACTED_CATEGORY]"

            try:
                safe_msg = PromptSanitizer.escape_prompt_injection(str(check.get('message', '')))
            except Exception:
                safe_msg = "[REDACTED_MESSAGE]"

            try:
                safe_path = PromptSanitizer.escape_prompt_injection(str(check.get('file_path', '')))
            except Exception:
                safe_path = "[REDACTED_PATH]"

            line_num = check.get('line_number', 0)

            context_parts.append(f"\n- {safe_cat} ({len(items)} occurrences)")
            context_parts.append(f"  Example: {safe_msg} at {safe_path}:{line_num}")

        summary_context = "\n".join(context_parts)

        # 4. Ask LLM with strict Timeout - Use safe prompt structure
        prompt = f"""
        Analyze this security scan failure and provide a concise EXECUTIVE SUMMARY (max 3 sentences).
        Explain WHY the build failed and WHAT is the most important action to take.
        Do not list all issues. Focus on patterns.

        <scan_results>
        {summary_context}
        </scan_results>
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
    format: str = typer.Option("text", "--format", help="Output format: text, json, sarif, junit, html, pdf, shield/badge"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed logs"),
    level: str = typer.Option("standard", "--level", help="Analysis level: basic, standard, deep"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Shorthand for --level basic"),
    memory_profile: bool = typer.Option(False, "--memory-profile", help="Enable memory profiling and leak detection"),
    ci: bool = typer.Option(False, "--ci", help="CI mode: read-only, optimized for CI/CD pipelines"),
    diff: bool = typer.Option(False, "--diff", help="Scan only files changed relative to base branch"),
    base: str = typer.Option("main", "--base", help="Base branch for diff comparison (default: main)"),
    update_baseline: bool = typer.Option(True, "--update-baseline/--no-update-baseline", help="Update baseline after scan (default: enabled, use --no-update-baseline for CI/PR)"),
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

                    # Show risk distribution for changed files in diff mode
                    if diff and paths:
                        risk_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
                        for p in paths:
                            risk = intel_loader.get_risk_for_file(p)
                            risk_counts[risk.value] = risk_counts.get(risk.value, 0) + 1
                        critical = risk_counts["P0"] + risk_counts["P1"]
                        low_risk = risk_counts["P3"]
                        if critical > 0:
                            console.print(f"[dim]   ⚠️  {critical} critical (P0/P1) + {low_risk} low-risk (P3) files changed[/dim]")
                else:
                    console.print("[yellow]⚠️  No pre-computed intelligence found. Run 'warden init' first for optimal CI performance.[/yellow]")
            except ImportError:
                console.print("[dim]Intelligence loader not available[/dim]")
            except Exception as e:
                console.print(f"[yellow]⚠️  Intelligence load failed: {e}[/yellow]")

        exit_code = asyncio.run(_run_scan_async(
            paths, frames, format, output, verbose, level,
            memory_profile, ci, baseline_fingerprints, intelligence_context,
            update_baseline=update_baseline
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
    intelligence_context: Optional[Dict] = None,
    update_baseline: bool = False
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

    processed_units = 0
    total_units = 0
    current_phase = "Initializing..."

    try:
        with console.status(f"[bold blue]🛡️  Scanning...[/bold blue]", spinner="dots") as status:
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

                    if verbose:
                        console.print(f"[dim]Progress Event: {evt} - {data}[/dim]")

                    if evt == "discovery_complete":
                        total_units = data.get('total_files', 0)
                        status.update(f"[bold blue]🛡️  Scanning...[/bold blue] [dim]Discovered {total_units} files[/dim] (0/{total_units})")
                    
                    elif evt == "pipeline_started":
                        # Use file_count as baseline if total_units not yet initialized
                        if total_units <= 0:
                            total_units = data.get('file_count', 0)
                        status.update(f"[bold blue]🛡️  Scanning...[/bold blue] [dim]Starting pipeline...[/dim] (0/{total_units})")

                    elif evt == "progress_init":
                        new_total = data.get('total_units', 0)
                        if new_total > 0:
                            total_units = new_total
                        status.update(f"[bold blue]🛡️  Scanning...[/bold blue] [dim]{current_phase}[/dim] ({processed_units}/{total_units})")
                    
                    elif evt == "progress_update":
                        increment = data.get('increment', 0)

                        # Only increment if we have a valid increment value
                        if increment > 0:
                            processed_units += increment
                        elif "frame_id" in data:
                            # If no increment but frame_id present, count as 1 unit
                            processed_units += 1

                        # Update current phase/status
                        new_status = data.get('status', data.get('phase'))
                        if new_status:
                            current_phase = new_status

                        # Clamp processed_units to never exceed total_units
                        if total_units > 0 and processed_units > total_units:
                            processed_units = total_units

                        # Update the sticky status line
                        status.update(f"[bold blue]🛡️  Scanning...[/bold blue] [dim]{current_phase}[/dim] ({processed_units}/{total_units})")
                    
                    elif evt == "phase_started":
                        current_phase = data.get('phase', current_phase)
                        status.update(f"[bold blue]🛡️  Scanning...[/bold blue] [dim]{current_phase}[/dim] ({processed_units}/{total_units})")
                        if verbose:
                            console.print(f"[bold blue]▶ Phase:[/bold blue] {current_phase}")

                    elif evt == "frame_completed":
                        # Fallback: if we didn't get a progress_update for this frame, increment here
                        # But be careful not to double count. Most frames send progress_update.
                        stats["total"] += 1
                        name = data.get('frame_name', data.get('frame_id'))
                        frame_status = data.get('status', 'unknown')
                        icon = "✅" if frame_status == "passed" else "❌" if frame_status == "failed" else "⚠️" 
                        style = "green" if frame_status == "passed" else "red" if frame_status == "failed" else "yellow"
                        findings_count = data.get('findings', data.get('issues_found', 0))

                        if frame_status == "passed":
                            stats["passed"] += 1
                        elif frame_status == "failed":
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
                        # Get findings - try different possible fields for validated findings after verification
                        # The pipeline summary shows "Issues Found: 4", so we need to find where this is stored
                        all_findings = []
                        
                        # Try multiple possible sources for findings after verification
                        if 'validated_issues' in res and res['validated_issues']:
                            all_findings = res['validated_issues']
                        elif 'findings' in res and res['findings']:
                            all_findings = res['findings']
                        elif 'true_positives' in res and res['true_positives']:  # Common field for verified findings
                            all_findings = res['true_positives']
                        elif 'verified_findings' in res and res['verified_findings']:  # Another possible field
                            all_findings = res['verified_findings']
                        else:
                            # If no specific validated field exists, use the raw findings
                            all_findings = []
                        
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

                        # Calculate additional metrics for enhanced reporting
                        total_findings = len(all_findings)
                        security_issues = sum(1 for f in all_findings if f.get('category', '').lower() in ['security', 'authentication', 'authorization', 'encryption', 'secrets'])
                        quality_issues = total_findings - security_issues
                        
                        # Count blocker issues (isBlocker: true)
                        blocker_issues = sum(1 for f in all_findings if f.get('isBlocker', False) is True)
                        critical_blockers = sum(1 for f in all_findings if f.get('isBlocker', False) is True and str(f.get('severity')).lower() == 'critical')
                        
                        # Get file count from results if available - use discovery results
                        total_files_scanned = res.get('file_count', res.get('total_files_scanned', total_units if total_units > 0 else len(set(f.get('file_path') for f in all_findings if f.get('file_path')))))
                        
                        # Get technical debt information from baseline update if available
                        baseline_info = res.get('baseline_update', {})
                        technical_debt = baseline_info.get('total_debt', total_findings)  # fallback to total findings
                        new_debt_added = baseline_info.get('new_debt', total_findings)  # fallback to total findings
                        
                        # If we still have 0 findings but the pipeline summary shows issues were found,
                        # try to get the issue count from other fields in the result
                        if total_findings == 0:
                            # Check if there's a field that contains the final count from the pipeline
                            if 'total_issues_found' in res:
                                total_findings = res['total_issues_found']
                            elif 'final_issue_count' in res:
                                total_findings = res['final_issue_count']
                            elif 'issues_found' in res:
                                total_findings = res['issues_found']
                            elif 'pipeline_summary' in res and isinstance(res['pipeline_summary'], dict):
                                # Look for issues found in pipeline summary
                                pipeline_summary = res['pipeline_summary']
                                if 'issues_found' in pipeline_summary:
                                    total_findings = pipeline_summary['issues_found']
                                elif 'findings_count' in pipeline_summary:
                                    total_findings = pipeline_summary['findings_count']

                        # Also update the individual metrics based on the actual findings list
                        # Use the validated/verified findings after verification phase
                        validated_findings = res.get('validated_issues', []) or res.get('true_positives', []) or res.get('verified_findings', []) or res.get('verified_issues', []) or res.get('validated_findings', []) or all_findings
                        if validated_findings and validated_findings != all_findings:
                            total_findings = len(validated_findings)
                            security_issues = sum(1 for f in validated_findings if f.get('category', '').lower() in ['security', 'authentication', 'authorization', 'encryption', 'secrets'])
                            quality_issues = total_findings - security_issues
                            blocker_issues = sum(1 for f in validated_findings if f.get('isBlocker', False) is True)
                            critical_blockers = sum(1 for f in validated_findings if f.get('isBlocker', False) is True and str(f.get('severity')).lower() == 'critical')
                        else:
                            # If validated findings are the same as all findings, use the original findings
                            validated_findings = all_findings
                            
                        # Final fallback: Check for specific fields that might contain the final validated count
                        # Based on the logs, the verification phase shows "total_verified=4", so look for that
                        if total_findings == 0:
                            # Try to get the verified count from the verification results
                            verified_count = res.get('verified_count', res.get('total_verified', res.get('final_findings_count', res.get('issues_found', 0))))
                            if verified_count > 0:
                                total_findings = verified_count
                                # Since we don't have the actual findings objects, we can't categorize them
                                # But we can at least show the correct total
                                security_issues = res.get('security_issues_count', res.get('security_findings', 0))
                                quality_issues = total_findings - security_issues
                                blocker_issues = res.get('blocker_issues_count', res.get('blocker_findings', 0))
                                critical_blockers = res.get('critical_blocker_count', res.get('critical_findings', 0))

                        table = Table(title="Scan Results")
                        table.add_column("Metric", style="cyan")
                        table.add_column("Value", style="magenta")

                        # Scanning Overview Section
                        table.add_row("Total Files Scanned", str(total_files_scanned))
                        table.add_row("Total Frames", str(res.get('total_frames', 0)))
                        table.add_row("Passed", f"[green]{res.get('frames_passed', 0)}[/green]")
                        table.add_row("Failed", f"[red]{res.get('frames_failed', 0)}[/red]")

                        # Findings Overview Section
                        table.add_section()
                        table.add_row("Total Findings", str(total_findings))
                        table.add_row("Security Issues", str(security_issues))
                        table.add_row("Quality Issues", str(quality_issues))

                        # Priority Issues Section
                        table.add_section()
                        table.add_row("Blocker Issues", str(blocker_issues))
                        table.add_row("Critical Issues", f"[{'red' if critical_blockers > 0 else 'green'}]{critical_blockers}[/]")

                        # Technical Debt Section
                        table.add_section()
                        table.add_row("Technical Debt", str(technical_debt))
                        table.add_row("New Debt Added", str(new_debt_added))

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
                                    elif fmt == 'shield':
                                        generator.generate_shield_report(final_result_data, out_path)
                                        console.print(f"  ✅ [cyan]SHIELD (JSON)[/cyan]: {path_str}")
                                    elif fmt == 'badge':
                                        generator.generate_svg_badge(final_result_data, out_path)
                                        console.print(f"  ✅ [cyan]BADGE (SVG)[/cyan]: {path_str}")
                                        
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
            out_path.parent.mkdir(parents=True, exist_ok=True)

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
            elif format == "shield":
                generator.generate_shield_report(final_result_data, out_path)
            elif format == "badge":
                generator.generate_svg_badge(final_result_data, out_path)
            
            console.print("[bold green]Report saved![/bold green]")

        # Save lightweight AI status file (Token-optimized)
        try:
            warden_dir = Path(".warden")
            if warden_dir.exists() and final_result_data:
                status_file = warden_dir / "ai_status.md"

                # Status check (COMPLETED=2) - must match other status checks in this file
                status_raw = final_result_data.get('status')
                is_success = str(status_raw).upper() in ["2", "SUCCESS", "COMPLETED", "PIPELINESTATUS.COMPLETED"]
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

        # Update baseline if requested (Phase 4.2)
        if update_baseline and final_result_data:
            try:
                from warden.cli.commands.helpers.baseline_manager import BaselineManager
                console.print("\n[bold blue]📉 Updating Baseline...[/bold blue]")

                baseline_mgr = BaselineManager(Path.cwd())

                # Load module map from intelligence if available
                module_map = None
                if intelligence_context and intelligence_context.get("modules"):
                    module_map = intelligence_context["modules"]

                # Ensure we're using module-based structure
                if not baseline_mgr.is_module_based():
                    console.print("[dim]Migrating to module-based baseline structure...[/dim]")
                    baseline_mgr.migrate_from_legacy(module_map)

                # Update baseline with scan results
                stats = baseline_mgr.update_baseline_for_modules(
                    scan_results=final_result_data,
                    module_map=module_map
                )

                # Display update statistics
                console.print(f"[green]✓ Baseline updated![/green]")
                console.print(f"[dim]   Modules updated: {stats['modules_updated']}[/dim]")

                if stats['total_new_debt'] > 0:
                    console.print(f"[yellow]   New debt items: {stats['total_new_debt']}[/yellow]")
                if stats['total_resolved_debt'] > 0:
                    console.print(f"[green]   Resolved debt: {stats['total_resolved_debt']}[/green]")

                # Check for debt warnings
                debt_report = baseline_mgr.get_debt_report()
                for warning in debt_report.get("warnings", []):
                    level_color = {
                        "critical": "red",
                        "warning": "yellow",
                        "info": "dim"
                    }.get(warning.get("level"), "dim")
                    console.print(f"[{level_color}]   ⚠️  {warning['message']}[/{level_color}]")

            except Exception as e:
                console.print(f"[yellow]⚠️  Baseline update failed: {e}[/yellow]")
                if verbose:
                    import traceback
                    traceback.print_exc()

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
