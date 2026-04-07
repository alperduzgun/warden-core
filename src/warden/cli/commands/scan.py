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
_logger = _structlog.get_logger(__name__)

# Module-level constants — defined once, not recreated on every CLI invocation.
_VALID_FORMATS: frozenset[str] = frozenset({"text", "json", "sarif", "junit", "html", "pdf", "shield", "badge"})
_VALID_LEVELS: frozenset[str] = frozenset({"basic", "standard", "deep"})
_VALID_SEVERITIES: frozenset[str] = frozenset({"critical", "high", "medium", "low", "none"})

# Re-exports for backwards compatibility
from warden.cli.commands.scan_preflight import _needs_ollama, _preflight_ollama_check, _ensure_scan_dependencies
from warden.cli.commands.scan_output import (
    _display_llm_summary,
    _display_frame_cost_breakdown,
    _display_memory_stats,
    _render_contract_mode_summary,
    _render_text_report,
    _generate_configured_reports,
    _write_ai_status_file,
    _update_tech_debt_file,
    print_findings_detail,
)


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

    except (asyncio.TimeoutError, TimeoutError):
        console.print("\n[dim]⚠️  AI Analysis timed out (skipped)[/dim]")
    except Exception:
        # Silent fail - this is an enhancement, not a critical path
        # console.print(f"[dim]AI Analysis unavailable: {e}[/dim]")
        pass


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


def _auto_init_warden_dir(project_root: Path, console: Any) -> None:
    """Auto-create a minimal .warden/ on first scan if it doesn't exist (#534).

    Only creates the directory and a stub config.yaml — does not run the full
    interactive `warden init` flow. Subsequent scans are idempotent.

    Resilience properties:
    - Idempotent: returns immediately if .warden/ already exists.
    - Atomic write: tempfile + os.replace so crash mid-write never leaves a
      corrupt config.yaml.
    - TOCTOU-safe: config_path existence checked after mkdir so concurrent
      `warden scan` invocations don't overwrite each other.
    - YAML-safe: project name is stripped of characters that would break YAML
      double-quoted scalars.
    """
    import os as _os
    import re as _re
    import tempfile as _tempfile

    warden_dir = project_root / ".warden"
    config_path = warden_dir / "config.yaml"

    if warden_dir.is_dir():
        return  # Already initialised — nothing to do

    if warden_dir.exists() or warden_dir.is_symlink():
        # Path exists but is not a directory (e.g. a stray file or broken symlink).
        # Proceeding would corrupt later code that expects a directory.
        console.print(
            f"[yellow]⚠ Cannot initialize [bold]{warden_dir.name}[/bold]: "
            "the path exists but is not a directory. "
            "Remove or rename it, then rerun the scan.[/yellow]"
        )
        _logger.warning("warden_dir_invalid_path", path=str(warden_dir))
        return

    try:
        warden_dir.mkdir(parents=True, exist_ok=True)

        # After mkdir, another concurrent process may have already written
        # config.yaml — skip the write to avoid a silent overwrite.
        if config_path.exists():
            return

        # Sanitize project name for safe YAML double-quoted scalar:
        # strip control characters and backslash/double-quote that would
        # require YAML escape sequences we don't emit.
        raw_name = project_root.name or "project"
        project_name = _re.sub(r'[\x00-\x1f"\\]', "", raw_name) or "project"

        stub_config = (
            "# Warden config — auto-created on first scan.\n"
            "# Run 'warden init' for the full interactive setup.\n"
            "\n"
            "project:\n"
            f'  name: "{project_name}"\n'
            "\n"
            "frames:\n"
            "  - security\n"
            "  - orphan\n"
            "\n"
            "# LLM provider — remove section to run in offline mode\n"
            "# llm:\n"
            "#   provider: ollama\n"
            "#   model: qwen2.5-coder:7b\n"
        )

        # Atomic write: write to a temp file in the same directory, then
        # os.replace (POSIX rename) so a crash mid-write never corrupts
        # config.yaml.
        fd, tmp_path = _tempfile.mkstemp(
            dir=warden_dir, prefix=".cfg_tmp_", suffix=".yaml"
        )
        try:
            with _os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(stub_config)
            _os.replace(tmp_path, config_path)
        except Exception:
            try:
                _os.unlink(tmp_path)
            except OSError:
                pass
            raise

        console.print(
            "[dim]📁 Initialized [bold].warden/[/bold] — "
            "run [bold cyan]warden init[/bold cyan] for full setup.[/dim]"
        )
        _logger.info("warden_dir_auto_created", path=str(warden_dir))
    except PermissionError as exc:
        _logger.warning("warden_dir_auto_init_failed", error=str(exc))
        console.print(
            f"[yellow]⚠️  Could not create .warden/ ({exc}). "
            "Continuing without persistent config.[/yellow]"
        )
    except OSError as exc:
        _logger.warning("warden_dir_auto_init_failed", error=str(exc))
        console.print(
            f"[yellow]⚠️  Could not create .warden/ ({exc}). "
            "Continuing without persistent config.[/yellow]"
        )


def _run_scan_plan(paths: list[str] | None, level: str, max_files: int | None = None) -> None:
    """
    Generate and display a pre-scan analysis plan using ScanPlanner.

    Exits after printing — does not run the actual scan.
    """
    import asyncio as _asyncio
    from pathlib import Path as _Path

    from rich.table import Table

    from warden.pipeline.application.scan_planner import ScanPlanner

    project_root = _Path(paths[0]) if paths else _Path.cwd()
    if not project_root.is_dir():
        project_root = project_root.parent

    console.print(f"\n[bold cyan]Scan Plan[/bold cyan] — [dim]{project_root}[/dim]")

    # Minimal config shim so planner picks up the analysis level
    class _MinimalConfig:
        class analysis_level:  # noqa: N801
            value = level

        use_gitignore = True

    planner = ScanPlanner()
    scan_plan = _asyncio.run(planner.plan(project_root=project_root, config=_MinimalConfig(), max_files=max_files))

    # --- Summary panel ---
    console.print(f"\n[dim]{scan_plan.reasoning}[/dim]\n")

    # --- Files summary ---
    summary_table = Table(show_header=False, box=None, padding=(0, 2))
    summary_table.add_column("Key", style="bold")
    summary_table.add_column("Value", style="cyan")
    summary_table.add_row("Analysis level", scan_plan.analysis_level)
    files_label = f"{scan_plan.file_count} / {scan_plan.max_files} max"
    summary_table.add_row("Files to scan", files_label)
    summary_table.add_row("Files skipped", str(scan_plan.skipped_count))
    summary_table.add_row("Estimated LLM calls", str(scan_plan.estimated_llm_calls))
    summary_table.add_row("Frames selected", str(len(scan_plan.frames)))
    console.print(summary_table)

    # --- Frame table ---
    if scan_plan.frames:
        console.print()
        frame_table = Table(title="Frames", show_header=True, header_style="bold magenta", expand=False)
        frame_table.add_column("Frame ID", style="green", min_width=14, no_wrap=True)
        frame_table.add_column("Display Name", style="white", min_width=18, no_wrap=True)
        frame_table.add_column("LLM", style="cyan", justify="center", min_width=3, no_wrap=True)
        frame_table.add_column("What it checks", style="dim", min_width=20, max_width=55, no_wrap=True)

        for frame in scan_plan.frames:
            llm_badge = "[cyan]yes[/cyan]" if frame.is_llm_powered else "[dim]no[/dim]"
            description = (getattr(frame, "description", "") or frame.reason or "")
            frame_table.add_row(
                frame.frame_id,
                frame.display_name,
                llm_badge,
                description[:55],
            )

        console.print(frame_table)

    console.print(
        "\n[dim]Run without --plan to execute the scan.[/dim]\n"
    )


def scan_command(
    paths: list[str] | None = typer.Argument(None, help="Files or directories to scan"),
    frames: list[str] | None = typer.Option(None, "--frame", "-f", help="Specific frames to run"),
    format: str = typer.Option(
        "text", "--format", help="Output format: text, json, sarif, junit, html, pdf, shield/badge"
    ),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed logs"),
    level: str | None = typer.Option(None, "--level", help="Analysis level: basic, standard, deep"),
    no_ai: bool = typer.Option(False, "--disable-ai", help="Shorthand for --level basic"),
    quick_start: bool = typer.Option(
        False, "--quick-start", "--fast", help="Fast deterministic scan: no LLM, no setup required (<10s)"
    ),
    memory_profile: bool = typer.Option(False, "--memory-profile", help="Enable memory profiling and leak detection"),
    ci: bool = typer.Option(False, "--ci", help="CI mode: read-only, optimized for CI/CD pipelines"),
    diff: bool = typer.Option(False, "--diff", help="Scan only files changed relative to base branch"),
    base: str = typer.Option("main", "--base", help="Base branch for diff comparison (default: main)"),
    fail_on_severity: str = typer.Option("critical", "--fail-on-severity", help="Fail if findings at this severity or above: critical, high, medium, low, none"),
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
    resume: bool = typer.Option(
        False,
        "--resume",
        help="Resume a previously interrupted scan, skipping already-scanned files.",
    ),
    provider: str | None = typer.Option(None, "--provider", help="LLM provider override (e.g., ollama, groq, qwen_cli, auto)"),
    plan: bool = typer.Option(False, "--plan", help="Print the analysis plan (frames, file count, LLM estimates) and exit without scanning"),
    max_files: int | None = typer.Option(None, "--max-files", help="Override max files limit (default: 1000)"),
    auto_improve: bool = typer.Option(False, "--auto-improve", help="After scan, run autoimprove loop against corpus to reduce false positives"),
    auto_improve_corpus: str = typer.Option("verify/corpus", "--auto-improve-corpus", help="Corpus directory for --auto-improve (default: verify/corpus)"),
    auto_improve_iterations: int = typer.Option(5, "--auto-improve-iterations", help="Max autoimprove iterations (default: 5)", min=1, max=100),
    auto_improve_check: str | None = typer.Option(None, "--auto-improve-check", help="Limit autoimprove to a single check ID (e.g. sql-injection)"),
    auto_improve_threshold: float = typer.Option(0.75, "--auto-improve-threshold", help="pattern_confidence threshold for auto-FP corpus (default: 0.75)", min=0.0, max=1.0),
    report_fp: list[str] = typer.Option([], "--report-fp", help="Report a finding ID as false positive and auto-suppress (e.g. --report-fp security-sql-injection-3)"),
) -> None:
    """
    Run the full Warden pipeline on files or directories.
    """
    # ── Input validation (#638) ───────────────────────────────────────────────
    if format not in _VALID_FORMATS:
        console.print(f"[red]Error:[/red] Invalid --format '{format}'. Choose from: {', '.join(sorted(_VALID_FORMATS))}")
        raise typer.Exit(1)
    if level and level not in _VALID_LEVELS:
        console.print(f"[red]Error:[/red] Invalid --level '{level}'. Choose from: {', '.join(sorted(_VALID_LEVELS))}")
        raise typer.Exit(1)
    if fail_on_severity not in _VALID_SEVERITIES:
        console.print(f"[red]Error:[/red] Invalid --fail-on-severity '{fail_on_severity}'. Choose from: {', '.join(sorted(_VALID_SEVERITIES))}")
        raise typer.Exit(1)
    if max_files is not None and not (1 <= max_files <= 10000):
        console.print(f"[red]Error:[/red] --max-files must be between 1 and 10000, got {max_files}")
        raise typer.Exit(1)

    # Provider CLI override → env var (picked up by load_llm_config_async)
    if provider:
        import os as _os
        _os.environ["WARDEN_LLM_PROVIDER"] = provider

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
        # Resolve level: CLI flag > env var > default "standard"
        # level is None when --level was not explicitly passed by the user
        if level is None:
            import os as _os
            _env_level = _os.environ.get("WARDEN_ANALYSIS_LEVEL", "").strip().lower()
            level = _env_level if _env_level else "standard"

        # Handle --quick-start and --no-ai shorthands
        if quick_start or no_ai:
            if level != "basic" and level != "standard":
                # Explicit --level conflicts with --quick-start
                console.print(
                    "[yellow]⚠ --quick-start overrides --level. Running deterministic-only.[/yellow]"
                )
            level = "basic"

        # Mode-appropriate messaging for basic level
        if level == "basic":
            if quick_start:
                _logger.info("quick_start_mode", msg="Running deterministic-only analysis (no LLM)")
                console.print(
                    "\n[bold cyan]⚡ Quick-Start Mode[/bold cyan]"
                    " — deterministic analysis (regex + AST + taint), no LLM required."
                )
                console.print(
                    "[dim]For deeper AI-powered analysis: warden config llm[/dim]\n"
                )
            else:
                console.print("\n[bold yellow]⚠ Basic Mode[/bold yellow] — AI verification disabled.")
                console.print("[dim]Deterministic checks only (regex, AST, taint analysis).[/dim]\n")

        # --plan: generate and display analysis plan then exit
        if plan:
            _run_scan_plan(paths=paths, level=level, max_files=max_files)
            return

        # Auto-init: create minimal .warden/ on first scan (#534).
        # Skip in CI mode: --ci is intended to be read-only and creating files
        # would make the workspace dirty or fail on read-only checkouts.
        if not ci:
            _auto_init_warden_dir(Path.cwd(), console)

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

        # diff_changed_lines: maps relative file path → set of changed line numbers.
        # Populated below when --diff is used; stays empty for full-scan mode.
        diff_changed_lines: dict[str, set[int]] = {}

        if diff:
            try:
                from warden.cli.commands.helpers.git_helper import GitHelper
                from warden.validation.frames.gitchanges.git_diff_parser import GitDiffParser

                console.print(f"[dim]🔍 Detecting changed files relative to '{base}'...[/dim]")
                git_helper = GitHelper(Path.cwd())
                changed_files = git_helper.get_changed_files(base_branch=base)

                if not changed_files:
                    console.print("[yellow]⚠️  No changed files detected. Scan skipped.[/yellow]")
                    return

                console.print(f"[green]✓ Found {len(changed_files)} changed files[/green]")
                paths = changed_files

                # Parse diff to get per-file changed line numbers for post-filter
                try:
                    diff_output = git_helper.get_diff_output(base_branch=base)
                    if diff_output:
                        parser = GitDiffParser()
                        for file_diff in parser.parse(diff_output):
                            added = file_diff.get_all_added_lines()
                            if added:
                                diff_changed_lines[file_diff.file_path] = added
                            # Map old path for renames regardless of added lines
                            if file_diff.old_path and file_diff.old_path != file_diff.file_path:
                                diff_changed_lines[file_diff.old_path] = added or set()
                        # Ensure files with only deletions are in the map (empty set = drop all findings)
                        for f in changed_files:
                            rel = str(Path(f).resolve().relative_to(Path.cwd().resolve())) if Path(f).is_absolute() else f
                            if rel not in diff_changed_lines:
                                diff_changed_lines[rel] = set()
                        if diff_changed_lines:
                            _logger.info(
                                "diff_line_map_built",
                                files=len(diff_changed_lines),
                            )
                except Exception as _e:
                    _logger.warning("diff_line_parse_failed", error=str(_e))
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

        # Resume support (#101): if --resume and partial results exist, load them
        resume_keys: set[tuple[str, str]] | None = None
        if resume:
            from warden.pipeline.application.orchestrator.partial_results_writer import (
                PartialResultsWriter,
            )

            if PartialResultsWriter.has_partial_results(Path.cwd()):
                resume_keys = PartialResultsWriter.load_completed_keys(Path.cwd())
                console.print(f"[green]Resuming scan: {len(resume_keys)} file/frame pairs already completed[/green]")
            else:
                console.print("[yellow]No partial results found, starting fresh scan[/yellow]")

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
                resume=resume,
                diff_changed_lines=diff_changed_lines,
                fail_on_severity=fail_on_severity,
                max_files=max_files,
                auto_improve=auto_improve,
                auto_improve_corpus=auto_improve_corpus,
                auto_improve_iterations=auto_improve_iterations,
                auto_improve_check=auto_improve_check,
                auto_improve_threshold=auto_improve_threshold,
                report_fp=report_fp,
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
                        resume=resume,
                        diff_changed_lines=diff_changed_lines,
                        fail_on_severity=fail_on_severity,
                        auto_improve=auto_improve,
                        auto_improve_corpus=auto_improve_corpus,
                        auto_improve_iterations=auto_improve_iterations,
                        auto_improve_check=auto_improve_check,
                        auto_improve_threshold=auto_improve_threshold,
                        report_fp=report_fp,
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
    max_files: int | None = None,
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
    _total_issues_so_far = 0  # cumulative findings across all phases
    _phase_start = time.monotonic()
    _last_phase = ""  # prevent duplicate headers
    _phase_steps: list[str] = []  # progress_update status strings for subtitle

    MAX_FRAME_ROWS = 6  # max frame detail rows visible for the current phase

    from warden.cli.commands import _scan_ux as _UX

    # ── Phase checklist (Issue #202) ─────────────────────────────────────
    from warden.cli.commands._phase_checklist_renderer import (
        normalise_phase_name as _norm_phase,
    )
    from warden.cli.commands._phase_checklist_renderer import (
        render_checklist_rows as _render_checklist,
    )
    from warden.pipeline.domain.phase_checklist import PhaseChecklist

    _phase_checklist = PhaseChecklist.from_defaults()

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

        issues_str = (
            f"  [bold red]{_total_issues_so_far} issue{'s' if _total_issues_so_far != 1 else ''}[/bold red]"
            if _total_issues_so_far > 0
            else ""
        )

        active_tbl = Table.grid(padding=(0, 1))
        active_tbl.add_column(no_wrap=True)
        active_tbl.add_column(no_wrap=False)
        active_tbl.add_row(
            _spinner_widget,
            Text.from_markup(
                f"[white]{current_phase}[/white]{frame_hint}[dim]{counter_str}[/dim]{clock_str}{issues_str}"
            ),
        )

        # ── Build content block ──────────────────────────────────────────────
        # Phase checklist at the top (Issue #202)
        checklist_rows = _render_checklist(_phase_checklist)
        content: list = [*checklist_rows, Text(""), *phase_summary_rows]

        # Phase hint: only when no live status is already shown in spinner row
        phase_hint_text = _UX.PHASE_HINTS.get(current_phase, "")
        if phase_hint_text and len(current_phase_frames) < 2 and not current_frame:
            _max = max(10, console.width - 8)
            hint_row = Text()
            hint_row.append("     ", style="")
            hint_row.append(phase_hint_text[:_max], style="dim")
            content.append(hint_row)

        content.extend(current_phase_frames[-MAX_FRAME_ROWS:])
        content.append(active_tbl)

        # Rotating security tip — swaps every 14 s
        tip_idx = int(elapsed_total / 14) % len(_UX.TIPS)
        _max_tip = max(10, console.width - 8)
        tip_row = Text()
        tip_row.append("  · ", style="dim bright_black")
        tip_row.append(_UX.TIPS[tip_idx][:_max_tip], style="dim")
        content.append(tip_row)

        # ── Vertical centering ───────────────────────────────────────────────
        # Push content toward the vertical center of the terminal so it doesn't
        # stick to the very bottom of the visible area.  We cap at 60 to avoid
        # excessive padding on very tall windows.
        term_h = min(console.height or 24, 60)
        top_pad = max(0, (term_h - len(content)) // 2)
        renderables: list = [Text("") for _ in range(top_pad)] + content

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
                max_files=max_files,
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

                        # Update phase checklist (Issue #202)
                        _cl_name = _norm_phase(data.get("phase_name", data.get("phase", "")))
                        if _cl_name:
                            _phase_checklist.mark_phase_running(_cl_name)

                        phase_total = data.get("total_units", 0)
                        if phase_total > 0:
                            total_units = phase_total
                            processed_units = 0

                    # ── phase completed (Issue #202) ───────────────────────────
                    elif evt == "phase_completed":
                        if bench_collector is not None:
                            bench_collector.on_event("phase_completed", data)
                        _cl_name = _norm_phase(data.get("phase_name", data.get("phase", "")))
                        if _cl_name:
                            _phase_checklist.mark_phase_done(_cl_name)

                    # ── phase skipped (Issue #202) ─────────────────────────────
                    elif evt == "phase_skipped":
                        _cl_name = _norm_phase(data.get("phase_name", data.get("phase", "")))
                        if _cl_name:
                            _phase_checklist.mark_phase_skipped(_cl_name)

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
                        _total_issues_so_far += findings_num
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
                    # Mark any still-running phase as done (Issue #202)
                    active = _phase_checklist.active_phase
                    if active:
                        active.mark_done()
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


def _build_fp_corpus_from_findings(
    final_result_data: dict,
    project_root: Path,
    threshold: float = 0.75,
    verbose: bool = False,
) -> Path | None:
    """
    Build a .warden/corpus/<slug>_auto_fp.py file from low-confidence findings.

    Findings with pattern_confidence < threshold are treated as likely FPs and
    written as corpus stubs so autoimprove can add suppression patterns for them.

    Returns the path to the written file, or None if no qualifying findings found.
    """
    import re as _re

    frame_results = final_result_data.get("frameResults", [])
    low_conf: dict[str, list[dict]] = {}  # check_id → findings

    for frame in frame_results:
        for finding in frame.get("findings", []):
            conf = finding.get("patternConfidence")
            if conf is None or conf >= threshold:
                continue
            # Extract check_id from finding ID: "<frame>-<check>-<n>"
            fid = finding.get("id", "")
            m = _re.match(r"^[^-]+-(.+)-\d+$", fid)
            if not m:
                continue
            check_id = m.group(1)
            low_conf.setdefault(check_id, []).append(finding)

    if not low_conf:
        return None

    corpus_dir = project_root / ".warden" / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale auto-fp files from previous runs
    for stale in corpus_dir.glob("*_auto_fp.py"):
        stale.unlink()

    slug = project_root.name.lower().replace("-", "_").replace(".", "_")
    out_path = corpus_dir / f"{slug}_auto_fp.py"

    lines = ['"""']
    lines.append("Auto-generated FP corpus from low-confidence scan findings.")
    lines.append("corpus_labels:")
    for check_id in sorted(low_conf):
        lines.append(f"  {check_id}: 0")
    lines.append('"""')
    lines.append("")

    for check_id, findings in sorted(low_conf.items()):
        for i, finding in enumerate(findings):
            fn_name = f"fp_{check_id.replace('-', '_')}_{i}"
            snippet = (finding.get("code") or "# (no code snippet)").strip()
            # Strip >>> prompt markers from interactive snippets
            snippet = _re.sub(r"^>>> ?", "", snippet, flags=_re.MULTILINE)
            lines.append(f"def {fn_name}():")
            lines.append(f"    # low-confidence ({finding.get('patternConfidence', '?'):.2f}) — likely FP")
            lines.append(f"    # finding: {finding.get('title', check_id)}")
            for code_line in snippet.splitlines():
                lines.append(f"    # {code_line}" if code_line.strip() else "    #")
            lines.append("    pass")
            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    if verbose:
        total = sum(len(v) for v in low_conf.values())
        console.print(f"[dim]Auto-FP corpus: {total} low-confidence findings → {out_path.name}[/dim]")

    return out_path


def _build_reported_fp_corpus(
    finding_ids: list[str],
    final_result_data: dict | None,
    project_root: Path,
    verbose: bool = False,
) -> Path | None:
    """
    Build .warden/corpus/<slug>_reported_fp.py from explicitly reported finding IDs.

    Looks up each ID in final_result_data first, then falls back to the
    findings cache. Returns the corpus file path, or None if no IDs matched.
    """
    import re as _re

    # Build a flat ID → finding map from scan results
    id_map: dict[str, dict] = {}
    if final_result_data:
        for f in final_result_data.get("findings", []):
            if isinstance(f, dict) and f.get("id"):
                id_map[f["id"]] = f

    # Fall back to findings cache for IDs not in scan results
    cache_path = project_root / ".warden" / "cache" / "findings_cache.json"
    if cache_path.exists():
        try:
            import json as _json
            cache = _json.loads(cache_path.read_text())
            for v in cache.values():
                if not isinstance(v, dict):
                    continue
                for f in v.get("findings", []):
                    if isinstance(f, dict) and f.get("id") and f["id"] not in id_map:
                        id_map[f["id"]] = f
        except Exception:
            pass

    matched: dict[str, list[dict]] = {}  # check_id → findings
    missing: list[str] = []

    for fid in finding_ids:
        finding = id_map.get(fid)
        if not finding:
            missing.append(fid)
            continue
        raw_id = finding.get("id", fid)
        m = _re.match(r"^[^-]+-(.+)-\d+$", raw_id)
        check_id = m.group(1) if m else raw_id
        matched.setdefault(check_id, []).append(finding)

    if missing:
        console.print(f"[yellow]⚠️  --report-fp: finding ID(s) not found: {', '.join(missing)}[/yellow]")

    if not matched:
        return None

    corpus_dir = project_root / ".warden" / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale reported-fp file from previous runs
    for stale in corpus_dir.glob("*_reported_fp.py"):
        stale.unlink()

    slug = project_root.name.lower().replace("-", "_").replace(".", "_")
    out_path = corpus_dir / f"{slug}_reported_fp.py"

    lines = ['"""']
    lines.append("User-reported false positives.")
    lines.append("corpus_labels:")
    for cid in sorted(matched):
        lines.append(f"  {cid}: 0")
    lines.append('"""')
    lines.append("")

    for cid, findings in sorted(matched.items()):
        for i, finding in enumerate(findings):
            fn_name = f"reported_fp_{cid.replace('-', '_')}_{i}"
            snippet = (finding.get("code") or finding.get("codeSnippet") or "# (no snippet)").strip()
            snippet = _re.sub(r"^>>> ?", "", snippet, flags=_re.MULTILINE)
            lines.append(f"def {fn_name}():")
            lines.append(f"    # reported FP: {finding.get('id', cid)}")
            lines.append(f"    # {finding.get('message', '') or finding.get('title', '')}")
            for code_line in snippet.splitlines():
                lines.append(f"    # {code_line}" if code_line.strip() else "    #")
            lines.append("    pass")
            lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    if verbose:
        total = sum(len(v) for v in matched.values())
        console.print(f"[dim]Reported-FP corpus: {total} finding(s) → {out_path.name}[/dim]")

    return out_path


async def _run_autoimprove_post_scan(
    corpus_dir: Path,
    check_id: str | None,
    iterations: int,
    dry_run: bool,
    fast: bool,
    verbose: bool,
    final_result_data: dict | None,
) -> None:
    """
    Run autoimprove loop after a scan completes.

    Never raises — all errors are printed as warnings so the scan exit code
    is never affected by autoimprove failures.
    """
    try:
        if not corpus_dir.exists():
            console.print(f"[yellow]⚠️  --auto-improve: corpus dir not found: {corpus_dir}[/yellow]")
            return

        from warden.cli.commands.rules import (
            _autoimprove_loop,
            _load_llm_service,
            _resolve_fp_exclusions_path,
        )

        fp_exclusions_file = _resolve_fp_exclusions_path()
        if not fp_exclusions_file.exists():
            console.print(f"[yellow]⚠️  --auto-improve: fp_exclusions.py not found at {fp_exclusions_file}[/yellow]")
            return

        llm_service = None
        effective_fast = fast
        if not fast:
            try:
                llm_service = _load_llm_service()
            except Exception:
                effective_fast = True

        console.print("\n[bold blue]🔄 Auto-Improve (post-scan)...[/bold blue]")
        await _autoimprove_loop(
            corpus_dir=corpus_dir,
            fp_exclusions_file=fp_exclusions_file,
            check_id=check_id,
            iterations=iterations,
            min_improvement=0.005,
            dry_run=dry_run,
            fast=effective_fast,
            llm_service=llm_service,
        )
    except Exception as e:
        console.print(f"[yellow]⚠️  --auto-improve failed: {e}[/yellow]")
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
    resume: bool = False,
    diff_changed_lines: dict | None = None,
    fail_on_severity: str = "critical",
    max_files: int | None = None,
    auto_improve: bool = False,
    auto_improve_corpus: str = "verify/corpus",
    auto_improve_iterations: int = 5,
    auto_improve_check: str | None = None,
    auto_improve_threshold: float = 0.75,
    report_fp: list[str] | None = None,
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

    # ── ASCII art logo ──────────────────────────────────────────────────────
    from warden.cli.commands import _scan_ux as _UX_h

    console.print()
    _max_w = max(10, console.width - 4)
    for _line in _UX_h.LOGO_LINES:
        console.print(f"  [bold steel_blue1]{_line[:_max_w]}[/]")

    # ── Info line ──────────────────────────────────────────────────────────
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
    console.print(Text("─" * min(console.width - 2, 72), style="dim bright_black"))
    console.print()

    bridge = WardenBridge(project_root=Path.cwd())

    # Inject diff-mode changed_lines into orchestrator so context gets them
    if diff_changed_lines and hasattr(bridge, "orchestrator"):
        bridge.orchestrator.changed_lines = diff_changed_lines

    # Initialise benchmark collector if requested (lazy import keeps startup fast).
    bench_collector = None
    if benchmark:
        from warden.benchmark.collector import BenchmarkCollector

        bench_collector = BenchmarkCollector()

    import time as _time

    try:
        # 1. Stream pipeline events and collect results
        _scan_wall_start = _time.monotonic()
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
            max_files=max_files,
        )
        _scan_wall_duration = _time.monotonic() - _scan_wall_start

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
            _render_text_report(
                final_result_data,
                total_units,
                verbose,
                scan_duration=_scan_wall_duration,
                frames_skipped=frame_stats.get("skipped", 0),
            )

            # Display per-frame cost breakdown if requested
            if cost_report:
                _display_frame_cost_breakdown()

            # 2.1 Rich findings detail: severity icons + per-file listing
            print_findings_detail(final_result_data, console)

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

        # 3.5 Auto-save JSON report in CI mode for smoke checks
        if ci_mode and final_result_data:
            try:
                from warden.reports.generator import ReportGenerator

                ci_report_dir = Path.cwd() / ".warden" / "reports"
                ci_report_dir.mkdir(parents=True, exist_ok=True)
                ci_report_path = ci_report_dir / "warden-report.json"
                ReportGenerator().generate_json_report(final_result_data, ci_report_path)
                if verbose:
                    console.print(f"  [dim]CI report saved → {ci_report_path}[/dim]")
            except Exception as e:
                if verbose:
                    console.print(f"[dim]Failed to auto-save CI report: {e}[/dim]")

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
                elif format in ("markdown", "md"):
                    generator.generate_markdown_report(final_result_data, out_path)
                else:
                    console.print(f"[yellow]⚠ Unknown format: {format}[/yellow]")

                console.print("[bold green]Report saved![/bold green]")
            except Exception as e:
                console.print(f"[red]❌ Failed to save report: {e}[/red]")

        # 5. Write AI status file
        if final_result_data:
            _write_ai_status_file(final_result_data)

        # 5.5 Update .warden/TECH_DEBT.md with antipattern findings
        if final_result_data:
            _update_tech_debt_file(final_result_data, verbose)

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

        # 6.6 Auto-improve: build FP corpus from low-confidence findings (S2),
        # then run autoimprove loop against the best available corpus (S1).
        if auto_improve and final_result_data:
            _auto_fp_path = _build_fp_corpus_from_findings(
                final_result_data,
                project_root=Path.cwd(),
                threshold=auto_improve_threshold,
                verbose=verbose,
            )
            if _auto_fp_path:
                console.print(f"\n[dim]Auto-FP corpus → {_auto_fp_path.relative_to(Path.cwd())}[/dim]")
                _corpus_to_use = _auto_fp_path.parent
            else:
                # Resolve the corpus path: try as-is first, then relative to warden package.
                _corpus_candidate = Path(auto_improve_corpus)
                if not _corpus_candidate.is_absolute():
                    # Absolute form relative to CWD
                    _corpus_candidate_abs = Path.cwd() / _corpus_candidate
                    if _corpus_candidate_abs.exists():
                        _corpus_candidate = _corpus_candidate_abs
                    else:
                        # Try to resolve from the warden package location (warden-core repo)
                        try:
                            import warden as _w
                            _pkg_root = Path(_w.__file__).parent.parent.parent
                            _pkg_corpus = _pkg_root / auto_improve_corpus
                            if _pkg_corpus.exists():
                                _corpus_candidate = _pkg_corpus
                        except Exception:
                            pass
                _corpus_to_use = _corpus_candidate

            if _auto_fp_path or _corpus_to_use.exists():
                await _run_autoimprove_post_scan(
                    corpus_dir=_corpus_to_use,
                    check_id=auto_improve_check,
                    iterations=auto_improve_iterations,
                    dry_run=dry_run,
                    fast=(level == "basic"),
                    verbose=verbose,
                    final_result_data=final_result_data,
                )
            else:
                console.print(
                    "[dim]--auto-improve: no low-confidence findings and corpus not found "
                    f"({_corpus_to_use}). Pass --auto-improve-corpus <path> to specify one.[/dim]"
                )

        # 6.7 --report-fp: build reported-FP corpus and run autoimprove immediately.
        if report_fp:
            _reported_path = _build_reported_fp_corpus(
                finding_ids=report_fp,
                final_result_data=final_result_data,
                project_root=Path.cwd(),
                verbose=verbose,
            )
            if _reported_path:
                console.print(f"\n[dim]Reported-FP corpus → {_reported_path.relative_to(Path.cwd())}[/dim]")
                console.print(f"[bold blue]🔄 Auto-suppress ({len(report_fp)} finding(s))...[/bold blue]")
                await _run_autoimprove_post_scan(
                    corpus_dir=_reported_path.parent,
                    check_id=None,
                    iterations=5,
                    dry_run=dry_run,
                    fast=True,
                    verbose=verbose,
                    final_result_data=final_result_data,
                )

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
        blocker_violations = final_result_data.get("blocker_violations", 0) if final_result_data else 0

        if not pipeline_ok:
            console.print("[bold red]❌ Pipeline did not complete successfully.[/bold red]")
            return 1

        if blocker_violations > 0:
            console.print(
                f"[bold red]❌ Scan failed: {blocker_violations} custom rule blocker violation(s).[/bold red]"
            )
            return 2  # Exit code 2: Policy Failure (Blocker rule violated)

        # Severity gate: fail if findings at configured severity or above
        _sev_threshold = fail_on_severity.lower() if fail_on_severity else "critical"
        _sev_counts = {
            "critical": critical_count,
            "high": critical_count + (final_result_data.get("high_findings", 0) if final_result_data else 0),
            "medium": critical_count + (final_result_data.get("high_findings", 0) if final_result_data else 0) + (final_result_data.get("medium_findings", 0) if final_result_data else 0),
            "low": (final_result_data.get("total_findings", 0) if final_result_data else 0),
        }
        _gate_count = _sev_counts.get(_sev_threshold, critical_count)
        if _gate_count > 0 and _sev_threshold != "none":
            console.print(f"[bold red]❌ Scan failed: {_gate_count} issue(s) at severity '{_sev_threshold}' or above.[/bold red]")
            await _generate_smart_failure_summary(critical_count, frames_failed, final_result_data)
            return 2  # Exit code 2: Policy Failure

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
