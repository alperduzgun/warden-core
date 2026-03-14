from datetime import datetime
from pathlib import Path

from rich import box as rbox
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

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
        fast_provider = fast.get("provider", "Ollama").title()
        console.print(f"\n  [green]⚡ Fast Tier ({fast_provider}):[/green]")
        console.print(f"    Requests: {fast['requests']} ({fast['percentage']}%)")
        console.print(f"    Success Rate: {fast['successRate']}%")
        console.print(f"    Avg Response: {fast['avgResponseTime']}")
        console.print(f"    Total Time: {fast['totalTime']} ({fast['timePercentage']}% of total)")
        if fast.get("timeouts", 0) > 0:
            console.print(f"    [yellow]⚠️  Timeouts: {fast['timeouts']}[/yellow]")

    if metrics.get("smartTier"):
        smart = metrics["smartTier"]
        smart_provider = smart.get("provider", "LLM").title()
        console.print(f"\n  [blue]🧠 Smart Tier ({smart_provider}):[/blue]")
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
            if issue.get("type") == "rate_limit":
                console.print(f"    [bold red]- {issue['message']}[/bold red]")
            else:
                console.print(f"    - {issue['message']}")
            if issue.get("recommendations"):
                for rec in issue["recommendations"]:
                    console.print(f"      → {rec}")


def _display_frame_cost_breakdown():
    """Display per-frame LLM cost breakdown table."""
    from warden.llm.metrics import get_global_metrics_collector

    collector = get_global_metrics_collector()
    frame_metrics = collector.get_frame_metrics()

    if not frame_metrics:
        console.print("\n[dim]No per-frame metrics available.[/dim]")
        return

    table = Table(title="Per-Frame LLM Cost Breakdown")
    table.add_column("Frame", style="cyan")
    table.add_column("LLM Calls", justify="right")
    table.add_column("Input Tokens", justify="right")
    table.add_column("Output Tokens", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Est. Cost", justify="right", style="green")
    table.add_column("Errors", justify="right", style="red")

    total_cost = 0.0
    for fm in frame_metrics:
        total_cost += fm.estimated_cost_usd
        table.add_row(
            fm.frame_name,
            str(fm.llm_calls),
            f"{fm.input_tokens:,}",
            f"{fm.output_tokens:,}",
            f"{fm.total_duration_ms / 1000:.1f}s",
            f"${fm.estimated_cost_usd:.4f}",
            str(fm.errors) if fm.errors > 0 else "-",
        )

    table.add_section()
    table.add_row("TOTAL", "", "", "", "", f"${total_cost:.4f}", "")

    console.print("\n", table)


def _display_memory_stats(snapshot) -> None:
    """Display memory profiling statistics."""
    console.print("\n[bold cyan]🧠 Memory Profiling Results[/bold cyan]")

    # Get top 10 memory consumers
    top_stats = snapshot.statistics("lineno")[:10]

    console.print("\n[bold]Top 10 Memory Allocations:[/bold]")
    for index, stat in enumerate(top_stats, 1):
        console.print(f"  {index}. {stat.traceback.format()[0]}")
        console.print(f"     Size: {stat.size / 1024 / 1024:.2f} MB ({stat.count} blocks)")

    # Total memory usage
    total = sum(stat.size for stat in snapshot.statistics("filename"))
    console.print(f"\n[bold]Total Memory Usage:[/bold] {total / 1024 / 1024:.2f} MB")

    # Check for potential leaks (allocations > 10MB)
    large_allocations = [s for s in top_stats if s.size > 10 * 1024 * 1024]
    if large_allocations:
        console.print("\n[yellow]⚠️  Potential Memory Leaks Detected:[/yellow]")
        for stat in large_allocations:
            console.print(f"  - {stat.traceback.format()[0]}: {stat.size / 1024 / 1024:.2f} MB")


def _render_contract_mode_summary(res: dict) -> None:
    """
    Render a CONTRACT MODE SUMMARY panel after a contract-mode scan.

    Shows the count and severity of each contract gap type detected.
    Displayed whenever --contract-mode is active, regardless of output format.
    """
    # Collect all findings across all frames
    all_findings: list[dict] = []
    for frame in res.get("frame_results", res.get("frameResults", [])):
        findings = frame.get("findings", [])
        all_findings.extend(findings if isinstance(findings, list) else [])
    # Also check top-level findings lists
    for key in ("validated_issues", "findings", "true_positives"):
        top_level = res.get(key, [])
        if isinstance(top_level, list):
            all_findings.extend(top_level)

    # Gap type metadata: (display_name, default_severity)
    gap_type_meta: list[tuple[str, str, str]] = [
        ("DEAD_WRITE", "DEAD_WRITE", "medium"),
        ("MISSING_WRITE", "MISSING_WRITE", "high"),
        ("STALE_SYNC", "STALE_SYNC", "medium"),
        ("PROTOCOL_BREACH", "PROTOCOL_BREACH", "high"),
        ("ASYNC_RACE", "ASYNC_RACE", "medium"),
    ]

    # Count findings per gap type
    gap_counts: dict[str, int] = {gt: 0 for gt, _, _ in gap_type_meta}
    for f in all_findings:
        gt = f.get("gap_type", "")
        if gt in gap_counts:
            gap_counts[gt] += 1

    # Severity color map
    sev_colors = {"high": "orange3", "medium": "yellow3", "low": "dim"}

    table = Table(box=rbox.SIMPLE, show_header=False, padding=(0, 1), show_edge=False)
    table.add_column("Gap Type", style="bold white", min_width=22, no_wrap=True)
    table.add_column("Count", min_width=14, no_wrap=True)
    table.add_column("Severity", min_width=8, no_wrap=True)

    for gt, _display, default_sev in gap_type_meta:
        count = gap_counts[gt]
        sev_color = sev_colors.get(default_sev, "white")
        count_str = f"[bold {'red' if count > 0 else 'dim'}]{count} finding{'s' if count != 1 else ''}[/]"
        sev_str = f"[{sev_color}]{default_sev}[/]" if count > 0 else "[dim]–[/]"
        table.add_row(gt, count_str, sev_str)

    panel = Panel(
        table,
        title="[bold cyan]CONTRACT MODE SUMMARY[/bold cyan]",
        border_style="cyan",
        padding=(0, 1),
    )
    console.print()
    console.print(panel)


def _render_text_report(
    res: dict,
    total_units: int,
    verbose: bool,
    scan_duration: float = 0.0,
    frames_skipped: int = 0,
) -> None:
    """Render scan results as a Rich text report to the console."""
    # Classify findings into core vs linter
    all_findings = (
        res.get("validated_issues")
        or res.get("findings")
        or res.get("true_positives")
        or res.get("verified_findings")
        or []
    )

    for f in all_findings:
        detail = f.get("detail") or ""
        if "(Ruff)" in detail or str(f.get("id", "")).startswith("lint_"):
            pass  # linter finding (counted but not separately displayed yet)

    # Calculate metrics
    total_findings = len(all_findings)
    security_issues = sum(
        1
        for f in all_findings
        if f.get("category", "").lower() in ["security", "authentication", "authorization", "encryption", "secrets"]
    )
    quality_issues = total_findings - security_issues
    blocker_issues = sum(1 for f in all_findings if f.get("isBlocker", False) is True)
    critical_blockers = sum(
        1 for f in all_findings if f.get("isBlocker", False) is True and str(f.get("severity")).lower() == "critical"
    )

    total_files_scanned = res.get(
        "file_count",
        res.get(
            "total_files_scanned",
            total_units if total_units > 0 else len({f.get("file_path") for f in all_findings if f.get("file_path")}),
        ),
    )

    baseline_info = res.get("baseline_update", {})
    technical_debt = baseline_info.get("total_debt", total_findings)
    new_debt_added = baseline_info.get("new_debt", total_findings)

    # Fallback: try pipeline summary fields when no findings objects exist
    if total_findings == 0:
        if "total_issues_found" in res:
            total_findings = res["total_issues_found"]
        elif "final_issue_count" in res:
            total_findings = res["final_issue_count"]
        elif "issues_found" in res:
            total_findings = res["issues_found"]
        elif "pipeline_summary" in res and isinstance(res["pipeline_summary"], dict):
            pipeline_summary = res["pipeline_summary"]
            if "issues_found" in pipeline_summary:
                total_findings = pipeline_summary["issues_found"]
            elif "findings_count" in pipeline_summary:
                total_findings = pipeline_summary["findings_count"]

    # Re-check with validated/verified findings
    validated_findings = (
        res.get("validated_issues", [])
        or res.get("true_positives", [])
        or res.get("verified_findings", [])
        or res.get("verified_issues", [])
        or res.get("validated_findings", [])
        or all_findings
    )
    if validated_findings and validated_findings != all_findings:
        total_findings = len(validated_findings)
        security_issues = sum(
            1
            for f in validated_findings
            if f.get("category", "").lower() in ["security", "authentication", "authorization", "encryption", "secrets"]
        )
        quality_issues = total_findings - security_issues
        blocker_issues = sum(1 for f in validated_findings if f.get("isBlocker", False) is True)
        critical_blockers = sum(
            1
            for f in validated_findings
            if f.get("isBlocker", False) is True and str(f.get("severity")).lower() == "critical"
        )

    # Final fallback: check verified count fields
    if total_findings == 0:
        verified_count = res.get(
            "verified_count",
            res.get("total_verified", res.get("final_findings_count", res.get("issues_found", 0))),
        )
        if verified_count > 0:
            total_findings = verified_count
            security_issues = res.get("security_issues_count", res.get("security_findings", 0))
            quality_issues = total_findings - security_issues
            blocker_issues = res.get("blocker_issues_count", res.get("blocker_findings", 0))
            critical_blockers = res.get("critical_blocker_count", res.get("critical_findings", 0))

    # ─── Findings ────────────────────────────────────────────
    display_findings = [f for f in all_findings if f.get("category", "") != "Orphan Code Analysis"]
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    display_findings.sort(key=lambda x: severity_order.get(str(x.get("severity", "info")).lower(), 5))

    if display_findings:
        console.print()
        for idx, finding in enumerate(display_findings[:10]):
            severity = str(finding.get("severity", "info")).lower()
            color_map = {
                "critical": "red",
                "high": "dark_orange",
                "medium": "yellow3",
                "low": "steel_blue1",
                "info": "grey62",
            }
            label_map = {"critical": "critical", "high": "high", "medium": "medium", "low": "low", "info": "info"}
            color = color_map.get(severity, "grey62")
            sev_label = label_map.get(severity, severity)

            # Parse location
            location = finding.get("location", "")
            file_path = finding.get("file_path", finding.get("path", ""))
            line_num = finding.get("line_number", finding.get("line_start", 0))
            if not file_path and location:
                parts = location.rsplit(":", 1)
                file_path = parts[0] if parts else location
                try:
                    line_num = int(parts[1]) if len(parts) > 1 else 0
                except (ValueError, IndexError):
                    line_num = 0

            ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else "py"
            lang_map = {
                "py": "python",
                "ts": "typescript",
                "js": "javascript",
                "go": "go",
                "rs": "rust",
                "java": "java",
                "kt": "kotlin",
                "swift": "swift",
                "cs": "csharp",
                "dart": "dart",
            }
            lang = lang_map.get(ext, "python")

            code_snippet = finding.get("code", finding.get("snippet", finding.get("context", "")))
            message = finding.get("message", "")
            detail = finding.get("detail", "")
            rule_id = finding.get("id", finding.get("rule_id", ""))

            # ── Header line: ● SEVERITY  file.py:14  rule-id ──
            header = Text()
            header.append("  ● ", style=f"bold {color}")
            header.append(sev_label.upper(), style=f"bold {color}")
            header.append("  ", style="")
            header.append(file_path, style="bold white")
            if line_num:
                header.append(f":{line_num}", style="dim white")
            if rule_id:
                header.append(f"  [{rule_id}]", style="dim")
            console.print(header)

            # ── Message ──
            console.print(f"    [dim]{message}[/dim]")

            # ── Code snippet ──
            if code_snippet:
                from rich.padding import Padding

                console.print()
                syntax = Syntax(
                    code_snippet,
                    lang,
                    theme="github-dark",
                    line_numbers=True,
                    start_line=max(1, line_num - 2),
                    word_wrap=True,
                    background_color="default",
                    indent_guides=False,
                )
                console.print(Padding(syntax, (0, 0, 0, 4)))

            # ── Suggested fix (from Fortification remediation) ── (#197)
            rem = finding.get("remediation")
            rem_code = ""
            if isinstance(rem, dict):
                rem_code = rem.get("code", "")
            elif rem is not None:
                rem_code = getattr(rem, "code", "")
            if rem_code:
                console.print("    [bold green]Suggested Fix:[/bold green]")
                fix_syntax = Syntax(
                    rem_code,
                    lang,
                    theme="github-dark",
                    line_numbers=False,
                    word_wrap=True,
                    background_color="default",
                    indent_guides=False,
                )
                from rich.padding import Padding

                console.print(Padding(fix_syntax, (0, 0, 0, 4)))

            # ── Remediation tip (first meaningful line) ──
            if detail:
                tip_lines = [
                    ln.strip()
                    for ln in detail.strip().splitlines()
                    if ln.strip() and not ln.strip().startswith("✅") and not ln.strip().startswith("❌")
                ]
                if tip_lines:
                    console.print(f"    [green]↳[/green] [dim]{tip_lines[0][:120]}[/dim]")

            console.print()  # breathing room between findings

        if len(display_findings) > 10:
            remaining = len(display_findings) - 10
            console.print(
                f"  [dim]… {remaining} more finding{'s' if remaining > 1 else ''} not shown  ·  warden scan --format sarif -o report.sarif[/dim]\n"
            )

    # ─── Summary ─────────────────────────────────────────────
    console.print(Rule(style="bright_black"))
    console.print()

    frames_passed = res.get("frames_passed", 0)
    frames_failed = res.get("frames_failed", 0)
    total_frames = res.get("total_frames", 0)
    crit_col = "red" if critical_blockers > 0 else "green"

    # Two-column aligned stat table — like Claude Code's usage summary
    stat_table = Table(box=None, show_header=False, padding=(0, 3), show_edge=False)
    stat_table.add_column("", style="dim", no_wrap=True, min_width=20)
    stat_table.add_column("", no_wrap=True, min_width=8)
    stat_table.add_column("", style="dim", no_wrap=True, min_width=20)
    stat_table.add_column("", no_wrap=True, min_width=8)

    pass_col = "green"
    fail_col = "red" if frames_failed > 0 else "green"

    stat_table.add_row(
        "Files scanned",
        f"[bold white]{total_files_scanned}[/]",
        "Frames",
        f"[bold white]{total_frames}[/]",
    )
    stat_table.add_row(
        "Frames passed",
        f"[bold {pass_col}]{frames_passed}[/]",
        "Frames failed",
        f"[bold {fail_col}]{frames_failed}[/]",
    )
    stat_table.add_row(
        "Total findings",
        f"[bold white]{total_findings}[/]",
        "Security issues",
        f"[bold {'orange3' if security_issues > 0 else 'white'}]{security_issues}[/]",
    )
    stat_table.add_row(
        "Critical",
        f"[bold {crit_col}]{critical_blockers}[/]",
        "Quality issues",
        f"[bold white]{quality_issues}[/]",
    )
    if technical_debt > 0 or new_debt_added > 0:
        new_debt_col = "red" if new_debt_added > 0 else "green"
        stat_table.add_row(
            "Technical debt",
            f"[bold white]{technical_debt}[/]",
            "New debt",
            f"[bold {new_debt_col}]{'+' if new_debt_added > 0 else ''}{new_debt_added}[/]",
        )

    duration_str = f"{scan_duration:.1f}s" if scan_duration > 0 else "—"

    # Detect Rust engine availability
    try:
        from warden.validation.application.rust_validation_engine import RUST_AVAILABLE
    except ImportError:
        RUST_AVAILABLE = False
    rust_label = "[bold green]active[/]" if RUST_AVAILABLE else "[bold yellow]unavailable[/]"

    stat_table.add_row(
        "Scan duration",
        f"[bold white]{duration_str}[/]",
        "Rust engine",
        rust_label,
    )
    stat_table.add_row(
        "",
        "",
        "Frames skipped",
        f"[bold white]{frames_skipped}[/]",
    )

    console.print(stat_table)
    console.print()

    # Missing tool hints
    frame_results = res.get("results", [])
    missing_tools = []
    for fr in frame_results:
        meta = fr.get("metadata", {}) or {}
        if meta.get("status") == "skipped_tool_missing":
            hint = meta.get("install_hint")
            frame_name = fr.get("frame_name", "Unknown Frame")
            if hint:
                missing_tools.append((frame_name, hint))

    if missing_tools:
        console.print("\n[bold yellow]⚠️  Missing Dependencies (Action Required):[/bold yellow]")
        for name, hint in missing_tools:
            console.print(f"  • [cyan]{name}[/cyan]: {hint}")
        console.print("")

    # LLM metrics
    llm_metrics = res.get("llmMetrics", {})
    if llm_metrics:
        _display_llm_summary(llm_metrics)

    # Status banner
    status_raw = res.get("status")
    is_success = str(status_raw).upper() in ["2", "SUCCESS", "COMPLETED", "PIPELINESTATUS.COMPLETED"]

    if verbose:
        console.print(f"[dim]Debug: status={status_raw} ({type(status_raw).__name__}), is_success={is_success}[/dim]")

    quality_score = res.get("quality_score", res.get("qualityScore"))
    score_str = f"  •  Quality Score: [bold]{quality_score:.1f}/10[/bold]" if quality_score is not None else ""

    if is_success:
        console.print(
            Panel(
                f"[bold green]✨  Scan Completed Successfully[/bold green]{score_str}",
                border_style="green",
                padding=(0, 2),
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]💥  Scan Failed[/bold red]{score_str}",
                border_style="red",
                padding=(0, 2),
            )
        )


def _generate_configured_reports(final_result_data: dict, verbose: bool) -> None:
    """Generate reports from warden.yaml / .warden/config.yaml output configuration."""
    try:
        import yaml

        from warden.reports.generator import ReportGenerator

        root_manifest = Path.cwd() / "warden.yaml"
        legacy_config = Path.cwd() / ".warden" / "config.yaml"
        config_path = root_manifest if root_manifest.exists() else legacy_config
        if not config_path.exists():
            return

        with open(config_path) as f:
            config = yaml.safe_load(f)

        ci_config = config.get("ci", {})
        advanced_config = config.get("advanced", {})
        outputs = ci_config.get("output", []) or advanced_config.get("output", [])

        if not outputs:
            return

        if verbose:
            console.print(f"\n[dim]📝 Found {len(outputs)} configured output(s)...[/dim]")
        generator = ReportGenerator()

        for out in outputs:
            fmt = out.get("format")
            path_str = out.get("path")
            if not fmt or not path_str:
                continue

            out_path = Path.cwd() / path_str
            out_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                if fmt == "json":
                    generator.generate_json_report(final_result_data, out_path)
                    console.print(f"  ✅ [cyan]JSON[/cyan]: {path_str}")
                elif fmt == "markdown" or fmt == "md":
                    generator.generate_markdown_report(final_result_data, out_path)
                    console.print(f"  ✅ [cyan]Markdown[/cyan]: {path_str}")
                elif fmt == "sarif":
                    generator.generate_sarif_report(final_result_data, out_path)
                    console.print(f"  ✅ [cyan]SARIF[/cyan]: {path_str}")
                elif fmt == "junit":
                    generator.generate_junit_report(final_result_data, out_path)
                    console.print(f"  ✅ [cyan]JUnit[/cyan]: {path_str}")
                elif fmt == "html":
                    generator.generate_html_report(final_result_data, out_path)
                    console.print(f"  ✅ [cyan]HTML[/cyan]: {path_str}")
                elif fmt == "pdf":
                    generator.generate_pdf_report(final_result_data, out_path)
                    console.print(f"  ✅ [cyan]PDF[/cyan]: {path_str}")
                elif fmt == "shield":
                    generator.generate_svg_badge(final_result_data, out_path)
                    console.print(f"  ✅ [cyan]SHIELD (SVG)[/cyan]: {path_str}")
                elif fmt == "badge":
                    generator.generate_svg_badge(final_result_data, out_path)
                    console.print(f"  ✅ [cyan]BADGE (SVG)[/cyan]: {path_str}")

            except Exception as e:
                console.print(f"  ❌ [red]{fmt.upper()}[/red]: Failed - {e}")
                if verbose:
                    console.print(f"     {e!s}")

    except Exception as e:
        console.print(f"\n[red]⚠️  Report generation failed: {e}[/red]")
        if verbose:
            import traceback

            traceback.print_exc()


def _write_ai_status_file(final_result_data: dict) -> None:
    """Write lightweight AI status file to .warden/ai_status.md."""
    try:
        warden_dir = Path(".warden")
        if not warden_dir.exists():
            return

        status_raw = final_result_data.get("status")
        is_success = str(status_raw).upper() in ["2", "SUCCESS", "COMPLETED", "PIPELINESTATUS.COMPLETED"]
        status_icon = "✅ PASS" if is_success else "❌ FAIL"
        critical_count = final_result_data.get("critical_findings", 0)
        total_count = final_result_data.get("total_findings", 0)
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
        status_file = warden_dir / "ai_status.md"
        with open(status_file, "w") as f:
            f.write(status_content)
    except Exception:
        pass  # Silent fail for aux file


def _update_tech_debt_file(final_result_data: dict, verbose: bool) -> None:
    """Update .warden/TECH_DEBT.md with god class and large file findings."""
    try:
        from warden.reports.tech_debt_generator import TechDebtGenerator

        generator = TechDebtGenerator(project_root=Path.cwd())
        result = generator.generate(final_result_data)
        if result:
            try:
                rel = result.relative_to(Path.cwd())
            except ValueError:
                rel = result
            console.print(f"  [dim]Updated tech debt report: {rel}[/dim]")
    except Exception as e:
        if verbose:
            console.print(f"[yellow]Warning: Tech debt update failed: {e}[/yellow]")
