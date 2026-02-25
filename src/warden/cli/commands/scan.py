import asyncio
import logging as _stdlib_logging
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog as _structlog
import typer
from rich import box as rbox
from rich.console import Console, Group
from rich.live import Live
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

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
        frame_results = result_data.get("frame_results", result_data.get("frameResults", []))
        for frame in frame_results:
            findings.extend(frame.get("findings", []))
        categories = {}

        # If too many findings, limit to critical ones
        critical_findings = [f for f in findings if str(f.get("severity")).upper() == "CRITICAL"]
        if not critical_findings:
            critical_findings = findings[:50]  # Fallback to top 50 if no explicit critical tag

        for f in critical_findings:
            cat = f.get("category", "General")
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(f)

        # 3. Prepare Context (Sampled) - SANITIZED to prevent prompt injection
        context_parts = [
            "Scan Failed.",
            f"Stats: {critical_count} critical issues, {frames_failed} failed frames.",
            "",
            "Top Issue Categories:",
        ]

        for cat, items in list(categories.items())[:5]:  # Top 5 categories
            check = items[0]
            # Sanitize all user-controlled strings (category, message, file_path)
            # Fail-safe: If sanitizer fails, redact entirely
            try:
                safe_cat = PromptSanitizer.escape_prompt_injection(str(cat))
            except Exception:
                safe_cat = "[REDACTED_CATEGORY]"

            try:
                safe_msg = PromptSanitizer.escape_prompt_injection(str(check.get("message", "")))
            except Exception:
                safe_msg = "[REDACTED_MESSAGE]"

            try:
                safe_path = PromptSanitizer.escape_prompt_injection(str(check.get("file_path", "")))
            except Exception:
                safe_path = "[REDACTED_PATH]"

            line_num = check.get("line_number", 0)

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
                use_fast_tier=True,  # Force Fast Tier (Qwen)
            ),
            timeout=5.0,
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


def _attempt_self_healing_sync(error: Exception, level: str) -> bool:
    """
    Attempt LLM-powered self-healing for a scan error.

    Returns True if the error was fixed and the scan should be retried.
    """
    try:
        from warden.self_healing import SelfHealingOrchestrator

        diagnostic = SelfHealingOrchestrator()
        context = f"warden scan --level {level}"

        console.print("\n[bold blue]🔧 Self-Healing: Analyzing error...[/bold blue]")

        result = asyncio.run(diagnostic.diagnose_and_fix(error, context=context))

        if result.fixed:
            console.print(f"[green]✓ Self-healed: {result.diagnosis}[/green]")
            if result.packages_installed:
                console.print(f"[dim]  Installed: {', '.join(result.packages_installed)}[/dim]")
            if getattr(result, "models_pulled", None):
                console.print(f"[dim]  Pulled models: {', '.join(result.models_pulled)}[/dim]")
            console.print("[dim]  Retrying scan...[/dim]\n")
            return True

        # Not fixed — show diagnosis
        if result.diagnosis:
            console.print(f"[yellow]Diagnosis:[/yellow] {result.diagnosis}")
        if result.suggested_action:
            console.print(f"[yellow]💡 Suggested:[/yellow] {result.suggested_action}")

        return False

    except Exception:
        # Self-healing itself failed — fall through to original error handling
        return False


def _ensure_scan_dependencies(level: str) -> None:
    """Auto-install missing packages needed for the given scan level."""
    try:
        from warden.services.dependencies.auto_resolver import ensure_dependencies

        needed: list[str] = []
        if level in ("standard", "deep"):
            needed.append("tiktoken")

        if not needed:
            return

        still_missing = ensure_dependencies(needed, context=f"scan --level {level}")
        if still_missing:
            console.print(
                f"[yellow]Optional dependencies unavailable: {', '.join(still_missing)}. "
                f"Scan will use fallback heuristics.[/yellow]"
            )
    except Exception:
        pass  # Dependency check is best-effort, never block the scan


def _needs_ollama() -> bool:
    """Return True if the project config requires Ollama."""
    import os

    import yaml

    # Respect CI env var overrides — if provider is forced to a cloud provider, skip
    env_provider = os.environ.get("WARDEN_LLM_PROVIDER", "").strip().lower()
    if env_provider and env_provider != "ollama":
        return False

    config_candidates = [Path.cwd() / "warden.yaml", Path.cwd() / ".warden" / "config.yaml"]
    for cfg_path in config_candidates:
        if cfg_path.exists():
            try:
                with open(cfg_path) as f:
                    data = yaml.safe_load(f) or {}
                llm = data.get("llm", {})
                provider = llm.get("provider", "")
                use_local = llm.get("use_local_llm", False)
                return provider == "ollama" or bool(use_local)
            except Exception:
                return False

    return False


def _preflight_ollama_check(rich_console: "Console") -> bool:
    """
    Verify Ollama is running and required models are present before scan starts.

    Returns True when ready (or Ollama is not needed).
    Returns False when a blocking issue could not be resolved.
    """
    if not _needs_ollama():
        return True

    from warden.services.local_model_manager import LocalModelManager

    manager = LocalModelManager()

    # 1. Check binary exists first — distinct message from "server not running"
    rich_console.print("[dim]🔍 Preflight: checking Ollama...[/dim]")
    if not manager.is_installed():
        rich_console.print("[red]❌ Ollama is not installed.[/red]")
        rich_console.print("[dim]   macOS : brew install ollama[/dim]")
        rich_console.print("[dim]   Linux : curl -fsSL https://ollama.com/install.sh | sh[/dim]")
        rich_console.print("[dim]   or    : https://ollama.com/download[/dim]")
        rich_console.print("[dim]   After installing, run: warden scan (preflight will auto-start the server)[/dim]")
        return False

    # 2. Ensure server is running
    if not manager.ensure_ollama_running():
        rich_console.print("[red]❌ Ollama could not be started.[/red]")
        rich_console.print("[dim]   Try running: ollama serve[/dim]")
        return False

    # 2. Check required models
    missing = [m for m in manager.get_configured_models() if not manager.is_model_available(m)]
    if not missing:
        return True

    # 3. Pull missing models (always auto-pull in scan context — user already chose Ollama)
    for model in missing:
        rich_console.print(f"[yellow]⚠️  Model missing: {model} — pulling now...[/yellow]")
        success = manager.pull_model(model, show_progress=True)
        if not success:
            rich_console.print(f"[red]❌ Failed to pull model '{model}'. Run: ollama pull {model}[/red]")
            return False

    return True


def scan_command(
    paths: list[str] | None = typer.Argument(None, help="Files or directories to scan"),
    frames: list[str] | None = typer.Option(None, "--frame", "-f", help="Specific frames to run"),
    format: str = typer.Option(
        "text", "--format", help="Output format: text, json, sarif, junit, html, pdf, shield/badge"
    ),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed logs"),
    level: str = typer.Option("standard", "--level", help="Analysis level: basic, standard, deep"),
    no_ai: bool = typer.Option(False, "--disable-ai", help="Shorthand for --level basic"),
    memory_profile: bool = typer.Option(False, "--memory-profile", help="Enable memory profiling and leak detection"),
    ci: bool = typer.Option(False, "--ci", help="CI mode: read-only, optimized for CI/CD pipelines"),
    diff: bool = typer.Option(False, "--diff", help="Scan only files changed relative to base branch"),
    base: str = typer.Option("main", "--base", help="Base branch for diff comparison (default: main)"),
    no_update_baseline: bool = typer.Option(False, "--no-update-baseline", help="Skip baseline update after scan"),
    cost_report: bool = typer.Option(False, "--cost-report", help="Display per-frame LLM cost breakdown"),
    auto_fix: bool = typer.Option(False, "--auto-fix", help="Apply auto-fixable fortification fixes"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview fixes without applying (use with --auto-fix)"),
    force: bool = typer.Option(False, "--force", help="Bypass memory cache and force a full analysis of all files"),
    no_preflight: bool = typer.Option(False, "--no-preflight", help="Skip Ollama model availability check before scan"),
    benchmark: bool = typer.Option(False, "--benchmark", "-b", help="Show per-phase timing breakdown after scan"),
    contract_mode: bool = typer.Option(
        False,
        "--contract-mode",
        help="Run data flow contract analysis (DEAD_WRITE, MISSING_WRITE, NEVER_POPULATED).",
    ),
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

    # ── Log verbosity gate ────────────────────────────────────────────────────
    # Fail fast default: suppress DEBUG/INFO unless --verbose is passed.
    # Applied once per process; idempotent via sentinel check on processor list.
    _cli_log_level = _stdlib_logging.DEBUG if verbose else _stdlib_logging.WARNING
    _stdlib_logging.basicConfig(level=_cli_log_level, force=True)
    _stdlib_logging.getLogger().setLevel(_cli_log_level)
    for _ns in ("httpx", "httpcore", "urllib3", "asyncio", "anthropic", "warden"):
        _stdlib_logging.getLogger(_ns).setLevel(_cli_log_level)

    # Structlog processor-level filter — drop events below threshold.
    # Named sentinel class so the idempotency check is reliable.
    class _CliLevelFilter:
        """Structlog processor: drops events with level < cli threshold."""

        _LEVELS: dict[str, int] = {"debug": 10, "info": 20, "warning": 30, "warn": 30, "error": 40, "critical": 50}

        def __call__(self, logger: Any, method: str, event_dict: dict) -> dict:
            if self._LEVELS.get(method, 0) < _cli_log_level:
                raise _structlog.DropEvent()
            return event_dict

    _current_procs = list(_structlog.get_config().get("processors", []))
    if not any(isinstance(p, _CliLevelFilter) for p in _current_procs):
        _current_procs.insert(0, _CliLevelFilter())
        _structlog.configure(processors=_current_procs)
    # ─────────────────────────────────────────────────────────────────────────

    # Run async scan function
    baseline_fingerprints = None
    intelligence_context = None
    try:
        # Handle --no-ai shorthand
        if no_ai:
            level = "basic"

        # Enforce AI-First Philosophy
        if level == "basic":
            console.print("\n[bold red blink]💀 CRITICAL WARNING: ZOMBIE MODE ACTIVE[/bold red blink]")
            console.print("[bold red]Warden is running without AI. Capability is reduced by 99%.[/bold red]")
            console.print("[red]Heuristic scanning is a fallback, not a feature. Expect poor results.[/red]\n")

        # Auto-install scan dependencies based on analysis level
        if level != "basic":
            _ensure_scan_dependencies(level)

        # Ollama preflight: ensure server running + models present before wasting time
        if level != "basic" and not no_preflight:
            ok = _preflight_ollama_check(console)
            if not ok:
                raise typer.Exit(1)

        # Default to "." if no paths provided AND no diff mode
        if not paths and not diff:
            paths = ["."]
        elif not paths:
            paths = []

        # Incremental Scanning Logic (--diff mode)

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
                    console.print(
                        f"[dim]🧠 Intelligence loaded: {modules} modules, quality={quality}/100, posture={posture}[/dim]"
                    )

                    # Show risk distribution for changed files in diff mode
                    if diff and paths:
                        risk_counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
                        for p in paths:
                            risk = intel_loader.get_risk_for_file(p)
                            risk_counts[risk.value] = risk_counts.get(risk.value, 0) + 1
                        critical = risk_counts["P0"] + risk_counts["P1"]
                        low_risk = risk_counts["P3"]
                        if critical > 0:
                            console.print(
                                f"[dim]   ⚠️  {critical} critical (P0/P1) + {low_risk} low-risk (P3) files changed[/dim]"
                            )
                else:
                    console.print(
                        "[yellow]⚠️  No pre-computed intelligence found. Run 'warden init' first for optimal CI performance.[/yellow]"
                    )
            except ImportError:
                console.print("[dim]Intelligence loader not available[/dim]")
            except Exception as e:
                console.print(f"[yellow]⚠️  Intelligence load failed: {e}[/yellow]")

        exit_code = asyncio.run(
            _run_scan_async(
                paths,
                frames,
                format,
                output,
                verbose,
                level,
                memory_profile,
                ci,
                baseline_fingerprints,
                intelligence_context,
                update_baseline=not no_update_baseline,
                cost_report=cost_report,
                auto_fix=auto_fix,
                dry_run=dry_run,
                force=force,
                benchmark=benchmark,
                contract_mode=contract_mode,
            )
        )

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
    except (SystemExit, typer.Exit):
        raise
    except Exception as e:
        # Try self-healing before giving up
        healed = _attempt_self_healing_sync(e, level)
        if healed:
            try:
                exit_code = asyncio.run(
                    _run_scan_async(
                        paths if paths else ["."],
                        frames,
                        format,
                        output,
                        verbose,
                        level,
                        memory_profile,
                        ci,
                        baseline_fingerprints,
                        intelligence_context,
                        update_baseline=not no_update_baseline,
                        cost_report=cost_report,
                        auto_fix=auto_fix,
                        dry_run=dry_run,
                        force=force,
                        benchmark=benchmark,
                        contract_mode=contract_mode,
                    )
                )
                if exit_code != 0:
                    raise typer.Exit(exit_code)
                return
            except (SystemExit, typer.Exit):
                raise
            except Exception as retry_err:
                console.print(f"\n[bold red]Error after self-healing retry:[/bold red] {retry_err}")

        console.print(f"\n[bold red]Error:[/bold red] {e}")
        console.print(
            "[yellow]💡 Tip:[/yellow] Run [bold cyan]warden doctor[/bold cyan] to check your setup, or [bold cyan]warden init --force[/bold cyan] to reconfigure."
        )
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Extracted helpers for _run_scan_async
# ---------------------------------------------------------------------------


async def _process_stream_events(
    bridge: WardenBridge,
    paths: list[str],
    frames: list[str] | None,
    verbose: bool,
    level: str,
    ci_mode: bool,
    force: bool,
    bench_collector: Any | None = None,
    contract_mode: bool = False,
) -> tuple[dict | None, dict, int]:
    """Process pipeline streaming events with a live-updating display.

    Returns ``(final_result_data, frame_stats, total_units)``.
    """
    import time

    from rich.spinner import Spinner

    _spinner_widget = Spinner("dots", style="bold blue")

    # ── Global scan stats ──────────────────────────────────────────────────
    frame_stats: dict[str, int] = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}
    final_result_data: dict | None = None
    processed_units = 0
    total_units = 0
    current_phase = ""
    current_frame = ""
    _scan_start = time.monotonic()  # wall-clock for elapsed display

    # ── Phase-level state ──────────────────────────────────────────────────
    # Completed phases → summary line + optional step subtitle each
    phase_summary_rows: list[Text] = []
    # Active phase → individual frame rows (cleared on each new phase)
    current_phase_frames: list[Text] = []
    # Per-phase counters and step log for the summary
    _phase_passed = 0
    _phase_failed = 0
    _phase_issues = 0
    _phase_start = time.monotonic()
    _last_phase = ""  # prevent duplicate headers
    _phase_steps: list[str] = []  # progress_update status strings for subtitle

    MAX_FRAME_ROWS = 6  # max frame detail rows visible for the current phase

    from warden.cli.commands import _scan_ux as _UX

    def _flush_phase() -> None:
        """Collapse the current phase into a summary row (+ dim step subtitle)."""
        nonlocal _phase_passed, _phase_failed, _phase_issues, _phase_start, _last_phase, _phase_steps
        if not _last_phase:
            return
        elapsed = time.monotonic() - _phase_start
        total_f = _phase_passed + _phase_failed
        has_issues = _phase_issues > 0

        # ── header row: glyph + name + frame count + status + time ─────────
        row = Text()
        row.append("  ", style="")
        if has_issues:
            row.append("[!]", style="bold dark_orange")
        else:
            row.append("[+]", style="bold green")
        row.append(" ", style="")
        row.append(f"{_last_phase:<20}", style="bold white")
        if total_f:
            row.append(f"  {total_f} frame{'s' if total_f != 1 else ''}", style="dim")
        if has_issues:
            row.append(f"  {_phase_issues} issue{'s' if _phase_issues != 1 else ''}", style="bold dark_orange")
        else:
            row.append("  clean", style="dim green")
        row.append(f"  {elapsed:.1f}s", style="dim")
        phase_summary_rows.append(row)

        # ── step subtitle: show last 2 unique steps, Claude Code style ─────
        if _phase_steps:
            seen: set[str] = set()
            unique_steps: list[str] = []
            for s in _phase_steps:
                if s not in seen:
                    seen.add(s)
                    unique_steps.append(s)
            shown = unique_steps[-2:]
            subtitle = Text()
            subtitle.append("     └ ", style="dim bright_black")
            subtitle.append(" · ".join(shown), style="dim")
            phase_summary_rows.append(subtitle)

        current_phase_frames.clear()
        _phase_passed = _phase_failed = _phase_issues = 0
        _phase_start = time.monotonic()
        _phase_steps = []
        _last_phase = ""

    def _make_live_renderable() -> Group:
        """Build live panel:
        [completed phase summaries]
        [current phase frame rows]
        [spinner + active status + wall-clock]
        [rotating security tip]
        """
        elapsed_total = time.monotonic() - _scan_start
        mm = int(elapsed_total // 60)
        ss = int(elapsed_total % 60)
        clock_str = f"  [dim]{mm:02d}:{ss:02d}[/dim]" if elapsed_total >= 1 else ""

        counter_str = f" ({processed_units}/{total_units})" if total_units > 0 else ""
        frame_hint = f"  [dim]{current_frame}[/dim]" if current_frame and current_frame != current_phase else ""

        active_tbl = Table.grid(padding=(0, 1))
        active_tbl.add_column(no_wrap=True)
        active_tbl.add_column(no_wrap=False)
        active_tbl.add_row(
            _spinner_widget,
            Text.from_markup(f"[white]{current_phase}[/white]{frame_hint}[dim]{counter_str}[/dim]{clock_str}"),
        )

        renderables: list = [*phase_summary_rows]

        # Show phase hint when active phase has zero or very few frame rows
        phase_hint_text = _UX.PHASE_HINTS.get(current_phase, "")
        if phase_hint_text and len(current_phase_frames) < 2:
            _max = max(10, console.width - 8)
            hint_row = Text()
            hint_row.append("     ", style="")
            hint_row.append(phase_hint_text[:_max], style="dim")
            renderables.append(hint_row)

        renderables.extend(current_phase_frames[-MAX_FRAME_ROWS:])
        renderables.append(active_tbl)

        # Rotating security tip — swaps every 14 s
        tip_idx = int(elapsed_total / 14) % len(_UX.TIPS)
        _max_tip = max(10, console.width - 8)
        tip_row = Text()
        tip_row.append("  · ", style="dim bright_black")
        tip_row.append(_UX.TIPS[tip_idx][:_max_tip], style="dim")
        renderables.append(tip_row)

        return Group(*renderables)

    try:
        with Live(
            _make_live_renderable(),
            console=console,
            refresh_per_second=12,
            transient=False,
        ) as live:
            async for event in bridge.execute_pipeline_stream_async(
                file_path=paths,
                frames=frames,
                verbose=verbose,
                analysis_level=level,
                ci_mode=ci_mode,
                force=force,
                contract_mode=contract_mode,
            ):
                event_type = event.get("type")

                if event_type == "progress":
                    evt = event["event"]
                    data = event.get("data", {})

                    # ── discovery / pipeline start ────────────────────────────
                    if evt == "discovery_complete":
                        total_units = data.get("total_files", 0)
                        current_phase = f"Discovered {total_units} files"
                        current_frame = ""

                    elif evt == "pipeline_started":
                        if total_units <= 0:
                            total_units = data.get("file_count", 0)
                        current_phase = "Starting pipeline"
                        current_frame = ""

                    elif evt == "progress_init":
                        new_total = data.get("total_units", 0)
                        if new_total > 0:
                            total_units = new_total

                    # ── phase transitions ──────────────────────────────────────
                    elif evt == "phase_started":
                        if bench_collector is not None:
                            bench_collector.on_event("phase_started", data)
                        raw = data.get("phase_name", data.get("phase", current_phase))
                        label = str(raw).title()

                        # Only transition when the phase name actually changes
                        if label != _last_phase:
                            _flush_phase()  # collapse previous phase
                            current_phase = label
                            current_frame = ""
                            _last_phase = label

                        phase_total = data.get("total_units", 0)
                        if phase_total > 0:
                            total_units = phase_total
                            processed_units = 0

                    # ── per-frame activity ───────────────────────────────────
                    elif evt == "progress_update":
                        increment = data.get("increment", 0)
                        if increment > 0:
                            processed_units += increment
                        elif "frame_id" in data:
                            processed_units += 1
                        if total_units > 0 and processed_units > total_units:
                            processed_units = total_units
                        new_status = data.get("status", data.get("phase", ""))
                        if new_status:
                            current_frame = str(new_status)
                            _phase_steps.append(str(new_status))  # record for subtitle

                    # ── frame completed ─────────────────────────────────────
                    elif evt == "frame_completed":
                        if bench_collector is not None:
                            bench_collector.on_event("frame_completed", data)
                        nonlocal_frame_name = data.get("frame_name", data.get("frame_id", "?"))
                        frame_status = data.get("status", "unknown")
                        findings_num = data.get("findings", data.get("issues_found", 0))
                        duration = data.get("duration", 0)

                        frame_stats["total"] += 1
                        if frame_status == "passed":
                            frame_stats["passed"] += 1
                            _phase_passed += 1
                            icon, color = "✔", "green"
                        elif frame_status == "failed":
                            frame_stats["failed"] += 1
                            _phase_failed += 1
                            icon, color = "✘", "red"
                        else:
                            frame_stats["skipped"] += 1
                            icon, color = "–", "dim"

                        _phase_issues += findings_num
                        current_frame = nonlocal_frame_name

                        # ── Critical finding flash row ─────────────────────────────
                        severity = str(data.get("severity", "")).lower()
                        if frame_status == "failed" and findings_num > 0 and severity in ("critical", "high", ""):
                            flash = Text()
                            flash.append("  !! ", style="bold red")
                            flash.append(
                                f"{findings_num} issue{'s' if findings_num != 1 else ''} in {nonlocal_frame_name}",
                                style="bold white",
                            )
                            current_phase_frames.append(flash)

                        # ── Regular frame row ──────────────────────────────────
                        row = Text()
                        row.append(f"    {icon} ", style=f"bold {color}")
                        row.append(f"{nonlocal_frame_name:<26}", style="white" if findings_num > 0 else "dim")
                        if findings_num > 0:
                            row.append(
                                f"  {findings_num} issue{'s' if findings_num != 1 else ''}", style=f"bold {color}"
                            )
                        else:
                            row.append("  clean", style="dim green")
                        row.append(f"  {duration:.1f}s", style="dim")
                        current_phase_frames.append(row)

                elif event_type == "result":
                    final_result_data = event["data"]
                    _flush_phase()  # collapse final phase
                    current_phase = "Complete"
                    current_frame = ""

                live.update(_make_live_renderable())

    except KeyboardInterrupt:
        # ── Ctrl+C: show partial summary ──────────────────────────────────────
        elapsed_s = time.monotonic() - _scan_start
        mm, ss = int(elapsed_s // 60), int(elapsed_s % 60)
        console.print()
        console.print(f"  [yellow]Scan cancelled after {mm:02d}:{ss:02d}[/yellow]")
        if phase_summary_rows:
            console.print()
            for r in phase_summary_rows:
                console.print(r)
        if _last_phase:
            cancelled = Text()
            cancelled.append("  [!] ", style="bold yellow")
            cancelled.append(f"Cancelled during  {_last_phase}", style="yellow")
            console.print(cancelled)
        console.print()
        return None, frame_stats, total_units

    import random

    q_text, q_author = random.choice(_UX.QUOTES)
    console.print()
    console.print(f"  [dim italic]{q_text}[/dim italic]")
    console.print(f"                                        [dim]— {q_author}[/dim]")
    console.print()
    return final_result_data, frame_stats, total_units


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


def _render_text_report(res: dict, total_units: int, verbose: bool) -> None:
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
                except:
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
                    pass
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


def _update_baseline(
    final_result_data: dict,
    intelligence_context: dict | None,
    verbose: bool,
) -> None:
    """Update baseline with scan results and display debt report."""
    try:
        from warden.cli.commands.helpers.baseline_manager import BaselineManager

        console.print("\n[bold blue]📉 Updating Baseline...[/bold blue]")

        baseline_mgr = BaselineManager(Path.cwd())

        module_map = None
        if intelligence_context and intelligence_context.get("modules"):
            module_map = intelligence_context["modules"]

        if not baseline_mgr.is_module_based():
            console.print("[dim]Migrating to module-based baseline structure...[/dim]")
            baseline_mgr.migrate_from_legacy(module_map)

        update_stats = baseline_mgr.update_baseline_for_modules(
            scan_results=final_result_data,
            module_map=module_map,
        )

        console.print("[green]✓ Baseline updated![/green]")
        console.print(f"[dim]   Modules updated: {update_stats['modules_updated']}[/dim]")

        if update_stats["total_new_debt"] > 0:
            console.print(f"[yellow]   New debt items: {update_stats['total_new_debt']}[/yellow]")
        if update_stats["total_resolved_debt"] > 0:
            console.print(f"[green]   Resolved debt: {update_stats['total_resolved_debt']}[/green]")

        debt_report = baseline_mgr.get_debt_report()
        for warning in debt_report.get("warnings", []):
            level_color = {"critical": "red", "warning": "yellow", "info": "dim"}.get(warning.get("level"), "dim")
            console.print(f"[{level_color}]   ⚠️  {warning['message']}[/{level_color}]")

    except Exception as e:
        console.print(f"[yellow]⚠️  Baseline update failed: {e}[/yellow]")
        if verbose:
            import traceback

            traceback.print_exc()


# ---------------------------------------------------------------------------
# Main async scan orchestrator
# ---------------------------------------------------------------------------


async def _run_scan_async(
    paths: list[str],
    frames: list[str] | None,
    format: str,
    output: str | None,
    verbose: bool,
    level: str = "standard",
    memory_profile: bool = False,
    ci_mode: bool = False,
    baseline_fingerprints: dict[str, str] | None = None,
    intelligence_context: dict | None = None,
    update_baseline: bool = False,
    cost_report: bool = False,
    auto_fix: bool = False,
    dry_run: bool = False,
    force: bool = False,
    benchmark: bool = False,
    contract_mode: bool = False,
) -> int:
    """Async implementation of scan command."""

    # ── Startup header ──────────────────────────────────────────────────
    try:
        from importlib.metadata import version as _pkg_ver

        _warden_ver = _pkg_ver("warden-core")
    except Exception:
        _warden_ver = "dev"

    _level_label = level.value if hasattr(level, "value") else str(level)
    _proj_label = Path.cwd().name
    _file_label = f"{len(paths)} path{'s' if len(paths) != 1 else ''}"

    # \u2500\u2500 ASCII art logo \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    from warden.cli.commands import _scan_ux as _UX_h

    console.print()
    _max_w = max(10, console.width - 4)
    for _line in _UX_h.LOGO_LINES:
        console.print(f"  [bold steel_blue1]{_line[:_max_w]}[/]")

    # \u2500\u2500 Info line \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
    header = Text()
    header.append(" Warden ", style="bold white on dark_blue")
    header.append(f" v{_warden_ver} ", style="dim")
    header.append(" | ", style="dim bright_black")
    header.append(_proj_label, style="bold")
    header.append(" | ", style="dim bright_black")
    header.append(_file_label, style="dim")
    header.append(" | ", style="dim bright_black")
    header.append(_level_label, style="dim")
    console.print()
    console.print(header)
    console.print(Text("\u2500" * min(console.width - 2, 72), style="dim bright_black"))
    console.print()

    bridge = WardenBridge(project_root=Path.cwd())

    # Initialise benchmark collector if requested (lazy import keeps startup fast).
    bench_collector = None
    if benchmark:
        from warden.benchmark.collector import BenchmarkCollector

        bench_collector = BenchmarkCollector()

    try:
        # 1. Stream pipeline events and collect results
        final_result_data, frame_stats, total_units = await _process_stream_events(
            bridge,
            paths,
            frames,
            verbose,
            level,
            ci_mode,
            force,
            bench_collector=bench_collector,
            contract_mode=contract_mode,
        )

        # 1.5 Display benchmark report if requested.
        if bench_collector is not None:
            from warden.benchmark.reporter import BenchmarkReporter

            prev_report = BenchmarkReporter.load_previous(Path.cwd() / ".warden")
            bench_report = bench_collector.finalize(bridge, files_scanned=total_units)
            BenchmarkReporter.display(bench_report, console, prev=prev_report)
            bench_path = BenchmarkReporter.save(bench_report, Path.cwd() / ".warden")
            try:
                rel = bench_path.relative_to(Path.cwd())
            except ValueError:
                rel = bench_path
            console.print(f"  [dim]Saved → {rel}[/dim]\n")

        # 2. Render text report to console
        if final_result_data and format == "text":
            _render_text_report(final_result_data, total_units, verbose)

            # Display per-frame cost breakdown if requested
            if cost_report:
                _display_frame_cost_breakdown()

        # 2.5 Display Contract Mode Summary panel (when --contract-mode is active)
        if contract_mode and final_result_data:
            _render_contract_mode_summary(final_result_data)

        # 3. Generate configured reports from YAML config
        if final_result_data:
            _generate_configured_reports(final_result_data, verbose)

            # Auto-generate badge in root directory
            try:
                from warden.reports.generator import ReportGenerator

                generator = ReportGenerator()
                badge_path = Path.cwd() / "warden_badge.svg"
                generator.generate_svg_badge(final_result_data, badge_path)
                console.print("\n[bold green]🛡️  Warden Badge Generated![/bold green]")
                console.print(f"  [dim]Badge saved to: {badge_path}[/dim]")
                console.print("  [dim]Add this to your README.md:[/dim]")
                console.print("  [cyan]![Warden Quality](./warden_badge.svg)[/cyan]")
            except Exception as e:
                if verbose:
                    console.print(f"[dim]Failed to auto-generate root badge: {e}[/dim]")

        # 4. Generate explicit --output report
        if output and final_result_data:
            from warden.reports.generator import ReportGenerator

            generator = ReportGenerator()
            out_path = Path(output)
            out_path.parent.mkdir(parents=True, exist_ok=True)

            console.print(f"\n[dim]Generating {format.upper()} report to {output}...[/dim]")

            try:
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
                elif format == "shield" or format == "badge":
                    generator.generate_svg_badge(final_result_data, out_path)

                console.print("[bold green]Report saved![/bold green]")
            except Exception as e:
                console.print(f"[red]❌ Failed to save report: {e}[/red]")

        # 5. Write AI status file
        if final_result_data:
            _write_ai_status_file(final_result_data)

        # 6. Update baseline
        if update_baseline and final_result_data:
            _update_baseline(final_result_data, intelligence_context, verbose)

        # 6.5 Auto-fix (after scan results, before exit code)
        if auto_fix and final_result_data:
            try:
                from warden.fortification.application.auto_fixer import AutoFixer

                fixer = AutoFixer(project_root=Path.cwd(), dry_run=dry_run)
                fortifications = final_result_data.get("fortifications", [])

                if fortifications:
                    mode = "DRY RUN" if dry_run else "APPLYING"
                    console.print(f"\n[bold blue]🔧 Auto-Fix ({mode})...[/bold blue]")

                    fix_result = await fixer.apply_fixes(fortifications)

                    console.print(f"[green]✓ {fix_result.summary}[/green]")

                    if fix_result.applied and not dry_run:
                        console.print("[dim]Review changes with: git diff[/dim]")
                        console.print("[dim]Reject all with: git checkout .[/dim]")
                else:
                    console.print("\n[dim]No auto-fixable items found.[/dim]")
            except Exception as e:
                console.print(f"[yellow]⚠️  Auto-fix failed: {e}[/yellow]")

        # 7. Exit code decision
        status_val = final_result_data.get("status") if final_result_data else None
        pipeline_ok = final_result_data and str(status_val).upper() in [
            "2",
            "5",
            "SUCCESS",
            "COMPLETED",
            "COMPLETED_WITH_FAILURES",
            "PIPELINESTATUS.COMPLETED",
            "PIPELINESTATUS.COMPLETED_WITH_FAILURES",
        ]

        critical_count = final_result_data.get("critical_findings", 0) if final_result_data else 0
        frames_failed = final_result_data.get("frames_failed", 0) if final_result_data else 0

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
