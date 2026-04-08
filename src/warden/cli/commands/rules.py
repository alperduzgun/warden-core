"""Warden rules sub-commands.

Provides 'warden rules generate' for AI-powered rule scaffolding,
and 'warden rules autoimprove' for automated FP exclusion tuning.
"""

import asyncio
import hashlib
from pathlib import Path

import typer
from rich.console import Console

console = Console()

rules_app = typer.Typer(name="rules", help="Manage Warden custom rules.", no_args_is_help=True)


@rules_app.command(name="generate")
def generate_command(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory (default: cwd)"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing llm_generated.yml"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print rules to terminal, do not write file"),
) -> None:
    """Generate AI rules for this project using LLM analysis.

    Detects the project language and framework, asks the configured LLM to
    produce type:ai rules, and writes them to .warden/rules/llm_generated.yml.

    Review the output and commit the file to your repository.
    On the next scan, the orchestrator loads the rules automatically.

    Examples:
        warden rules generate
        warden rules generate --force
        warden rules generate --dry-run
        warden rules generate --path /path/to/project
    """
    root = path.resolve()
    warden_dir = root / ".warden"

    if not warden_dir.exists():
        console.print("[red]Error: Warden not initialized. Run 'warden init' first.[/red]")
        raise typer.Exit(1)

    console.print("\n[bold cyan]⚙  Warden Rules Generate[/bold cyan]")

    llm_service = _load_llm_service()
    if llm_service is None:
        raise typer.Exit(1)

    if dry_run:
        asyncio.run(_dry_run_async(root, llm_service))
        return

    output_path = warden_dir / "rules" / "llm_generated.yml"
    if output_path.exists() and not force:
        console.print(
            f"[yellow]⚠  {output_path.relative_to(root)} already exists. "
            "Use --force to overwrite.[/yellow]"
        )
        raise typer.Exit(0)

    asyncio.run(_generate_async(root, llm_service, force))


def _load_llm_service():
    """Load and return LLM service, or None on failure."""
    try:
        from warden.llm.config import load_llm_config
        from warden.llm.factory import create_client

        llm_config = load_llm_config()
        if llm_config is None:
            console.print(
                "[red]Error: LLM not configured. Run 'warden config llm' to set up.[/red]"
            )
            return None

        service = create_client(llm_config.default_provider)
        if service:
            service.config = llm_config
        return service
    except Exception as exc:
        console.print(f"[red]Error loading LLM service: {exc}[/red]")
        return None


async def _generate_async(root: Path, llm_service, force: bool) -> None:
    from warden.rules.application.rule_generator import OUTPUT_FILENAME, generate_rules_for_project

    try:
        count = await generate_rules_for_project(root, llm_service, force=force)
    except ValueError as exc:
        console.print(f"[red]Rule generation failed: {exc}[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]Unexpected error: {exc}[/red]")
        raise typer.Exit(1)

    if count == -1:
        console.print("[yellow]Rules already exist. Use --force to overwrite.[/yellow]")
    else:
        output_path = root / ".warden" / "rules" / OUTPUT_FILENAME
        console.print(
            f"[green]✓ {count} kural oluşturuldu → {output_path}\n"
            "[dim]Review edip git commit edin.[/dim][/green]"
        )


@rules_app.command(name="refine")
def refine_command(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Project directory (default: cwd)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show proposed changes without writing"),
    rule_id: list[str] = typer.Option([], "--rule", "-r", help="Limit to specific rule IDs (repeatable)"),
) -> None:
    """Refine AI rule context fields by analyzing recent scan findings for false positives.

    Reads the findings cache from the last scan, classifies each finding using
    the configured LLM, and appends acceptable-pattern guidance to the context
    field of rules that produced false positives.

    Examples:
        warden rules refine
        warden rules refine --dry-run
        warden rules refine --rule no-bare-except --rule no-hardcoded-secrets
        warden rules refine --path /path/to/project
    """
    root = path.resolve()
    warden_dir = root / ".warden"

    if not warden_dir.exists():
        console.print("[red]Error: Warden not initialized. Run 'warden init' first.[/red]")
        raise typer.Exit(1)

    console.print("\n[bold cyan]⚙  Warden Rules Refine[/bold cyan]")

    llm_service = _load_llm_service()
    if llm_service is None:
        raise typer.Exit(1)

    asyncio.run(_refine_async(root, llm_service, list(rule_id) or None, dry_run))


async def _refine_async(
    root: Path,
    llm_service,
    rule_ids: list[str] | None,
    dry_run: bool,
) -> None:
    from rich.table import Table

    from warden.rules.application.rule_refiner import refine_rules

    try:
        result = await refine_rules(
            project_path=root,
            llm_service=llm_service,
            rule_ids=rule_ids,
            dry_run=dry_run,
        )
    except Exception as exc:
        console.print(f"[red]Refine failed: {exc}[/red]")
        raise typer.Exit(1)

    # Summary table
    if result.analyzed > 0:
        table = Table(title="Refinement Results", show_lines=True)
        table.add_column("Rule ID", style="cyan")
        table.add_column("Verdict", style="green")
        table.add_column("Pattern")

        for upd in result.updates:
            table.add_row(upd["rule_id"], "false_positive", upd["pattern"])

        console.print(table)

    # Status line
    console.print(
        f"\nAnalyzed: [bold]{result.analyzed}[/bold]  "
        f"Real: [bold]{result.skipped_real}[/bold]  "
        f"Duplicates skipped: [bold]{result.skipped_duplicate}[/bold]"
    )

    if result.updates:
        if dry_run:
            console.print(f"\n[yellow][dry-run] Would update {len(result.updates)} rules[/yellow]")
            for upd in result.updates:
                console.print(f"\n  [bold]{upd['rule_id']}[/bold] proposed context addition:")
                console.print(f"  [dim]Acceptable: {upd['pattern']} — {upd['reason']}[/dim]")
        else:
            console.print(f"\n[green]✓ Updated context for {len(result.updates)} rules[/green]")
    else:
        console.print("\n[dim]No context updates needed.[/dim]")


async def _dry_run_async(root: Path, llm_service) -> None:
    from warden.analysis.application.discovery.framework_detector import detect_frameworks_async
    from warden.rules.application.rule_generator import (
        _JS_FRAMEWORKS,
        _PY_FRAMEWORKS,
        _RULE_GEN_PROMPT,
    )

    detection = await detect_frameworks_async(root)
    framework = detection.primary_framework.value if detection.primary_framework else "unknown"
    fw = framework.lower()
    language = (
        "python"
        if fw in _PY_FRAMEWORKS
        else ("javascript/typescript" if fw in _JS_FRAMEWORKS else "unknown")
    )

    prompt = _RULE_GEN_PROMPT.format(language=language, framework=framework)
    response = await llm_service.complete_async(
        prompt=prompt,
        system_prompt="You are a Warden rule definition generator. Output YAML only.",
    )
    raw: str = response.content if hasattr(response, "content") else str(response)
    console.print("[bold]Generated rules (dry-run — not written to disk):[/bold]\n")
    console.print(raw)


# ─── autoimprove ──────────────────────────────────────────────────────────────

_FP_EXCLUSIONS_PATH = Path("src/warden/validation/domain/fp_exclusions.py")

_AUTOIMPROVE_SYSTEM_PROMPT = (
    "You are a security analysis expert specializing in Python regex patterns. "
    "You help reduce false positives in static analysis tools by proposing precise "
    "regex exclusion patterns for the fp_exclusions.py file."
)

_AUTOIMPROVE_USER_PROMPT = """
The following code lines were flagged as security issues but are actually false positives
for the check '{check_id}'. Analyze these patterns and propose a Python regex pattern
that would match these false positives so they can be safely excluded.

False positive examples:
{fp_examples}

Respond with ONLY a raw Python regex pattern string (no quotes, no explanation).
The pattern must be specific enough to not match real vulnerabilities.
Example response format:
\\bsome_safe_function\\s*\\(

Your regex pattern:
""".strip()


@rules_app.command(name="autoimprove")
def autoimprove_command(
    corpus: Path = typer.Option(
        Path("verify/corpus"),
        "--corpus",
        help="Corpus directory [default: verify/corpus/]",
    ),
    frame: str = typer.Option(
        "security",
        "--frame",
        help="Frame to autoimprove: security | resilience",
    ),
    check: str | None = typer.Option(
        None,
        "--check",
        help="Improve only this check (e.g. sql-injection, timeout, circuit-breaker)",
    ),
    iterations: int = typer.Option(
        20,
        "--iterations",
        help="Maximum number of improvement iterations",
        min=1,
        max=100,
    ),
    min_improvement: float = typer.Option(
        0.005,
        "--min-improvement",
        help="Minimum F1 delta to accept a suggestion",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show proposed patterns without modifying fp_exclusions.py",
    ),
    fast: bool = typer.Option(
        False,
        "--fast",
        help="Skip LLM — use deterministic corpus scoring only (demo mode)",
    ),
) -> None:
    """Keep-or-revert loop: propose FP exclusion patterns, test against corpus, keep if F1 improves.

    For each iteration:
      1. Collect false positive examples from corpus FP files
      2. Ask LLM to propose a regex exclusion pattern (skipped with --fast)
      3. Temporarily apply the pattern to fp_exclusions.py
      4. Re-score the corpus — keep if F1 improved, revert otherwise

    Supports both security and resilience frames:
        warden rules autoimprove --frame security --fast --dry-run
        warden rules autoimprove --frame resilience --corpus verify/corpus/resilience/ --fast
        warden rules autoimprove --check timeout --frame resilience

    Examples:
        warden rules autoimprove --fast --dry-run
        warden rules autoimprove --corpus verify/corpus/ --iterations 5
        warden rules autoimprove --check xss --min-improvement 0.01
    """
    if not corpus.exists():
        console.print(f"[red]Corpus directory not found:[/red] {corpus}")
        raise typer.Exit(2)

    fp_exclusions_file = _resolve_fp_exclusions_path()
    if not fp_exclusions_file.exists():
        console.print(f"[red]fp_exclusions.py not found at:[/red] {fp_exclusions_file}")
        raise typer.Exit(2)

    llm_service = None
    if not fast and not dry_run:
        llm_service = _load_llm_service()
        if llm_service is None:
            console.print(
                "[yellow]LLM not configured — falling back to --fast mode.[/yellow]"
            )
            fast = True

    console.print("\n[bold cyan]Warden Rules Autoimprove[/bold cyan]")
    console.print(f"  Frame:      {frame}")
    console.print(f"  Corpus:     {corpus.resolve()}")
    console.print(f"  Check:      {check or '(all)'}")
    console.print(f"  Iterations: {iterations}")
    console.print(f"  Min delta:  {min_improvement:+.3f}")
    console.print(f"  Dry-run:    {dry_run}")
    console.print(f"  Fast:       {fast}\n")

    asyncio.run(
        _autoimprove_loop(
            corpus_dir=corpus,
            fp_exclusions_file=fp_exclusions_file,
            frame_id=frame,
            check_id=check,
            iterations=iterations,
            min_improvement=min_improvement,
            dry_run=dry_run,
            fast=fast,
            llm_service=llm_service,
        )
    )


def _resolve_fp_exclusions_path() -> Path:
    """Resolve fp_exclusions.py — prefer relative path from cwd, fall back to warden package."""
    # Try relative path from cwd (useful when running inside the warden-core repo)
    relative = Path.cwd() / _FP_EXCLUSIONS_PATH
    if relative.exists():
        return relative

    # Locate via installed package
    try:
        import inspect
        import warden.validation.domain.fp_exclusions as _mod
        return Path(inspect.getfile(_mod))
    except Exception:
        return relative  # return the expected path so the caller can report "not found"


def _collect_fp_examples(corpus_dir: Path, check_id: str | None) -> list[dict]:
    """
    Collect false positive code examples from corpus *_fp.py files.

    Returns list of dicts with keys: file, line_no, line, check_id.
    """
    examples: list[dict] = []
    fp_files = [
        p for p in sorted(corpus_dir.iterdir())
        if p.suffix == ".py" and (p.stem.endswith("_fp") or p.stem.startswith("clean_"))
    ]

    for fp_file in fp_files:
        content = fp_file.read_text(encoding="utf-8", errors="replace")

        # Parse corpus_labels to know which checks apply to this file
        from warden.validation.corpus.runner import parse_corpus_labels
        labels = parse_corpus_labels(content)
        if not labels:
            continue

        checks_here = (
            [check_id] if check_id and check_id in labels
            else ([k for k, v in labels.items() if v == 0] if not check_id else [])
        )

        for cid in checks_here:
            # Extract non-comment, non-empty lines as FP examples,
            # skipping triple-quoted docstring/comment regions entirely.
            in_triple_quote = False
            triple_quote_delim: str | None = None

            for line_no, line in enumerate(content.splitlines(), start=1):
                stripped = line.strip()

                if not stripped:
                    continue

                if in_triple_quote:
                    if triple_quote_delim and triple_quote_delim in stripped:
                        in_triple_quote = False
                        triple_quote_delim = None
                    continue

                if stripped.startswith("#"):
                    continue

                if '"""' in stripped or "'''" in stripped:
                    has_double = '"""' in stripped
                    has_single = "'''" in stripped
                    delim = (
                        '"""'
                        if has_double and (not has_single or stripped.find('"""') <= stripped.find("'''"))
                        else "'''"
                    )
                    # Single-line triple-quoted string (both open+close on same line) — skip
                    if stripped.count(delim) >= 2:
                        continue
                    # Opening of a multi-line triple-quoted block — enter and skip
                    in_triple_quote = True
                    triple_quote_delim = delim
                    continue

                if len(stripped) > 5:
                    examples.append({
                        "file": fp_file.name,
                        "line_no": line_no,
                        "line": stripped,
                        "check_id": cid,
                    })

        # Per-file soft cap: don't let one file dominate when check_id is None
        # and multiple checks are being collected across the whole corpus.
        if len(examples) >= 40:
            break

    return examples[:20]


async def _run_corpus_eval(corpus_dir: Path, check_id: str | None, fast: bool, frame_id: str = "security") -> "CorpusResult":  # noqa: F821
    """Run corpus evaluation and return CorpusResult."""
    from warden.validation.corpus.runner import CorpusRunner
    from warden.validation.infrastructure.frame_registry import get_registry

    registry = get_registry()
    registry.discover_all()
    frame_class = registry.get_frame_by_id(frame_id)
    if frame_class is None:
        raise RuntimeError(f"Frame '{frame_id}' not found in registry.")

    frame = frame_class()

    if fast:
        # Attributes vary by frame; try all known LLM-related attributes.
        # Security frame uses _llm_client/_verifier; resilience frame uses llm_service.
        for attr, value in (
            ("_llm_client", None),
            ("_llm", None),
            ("_verifier", None),
            ("_use_llm", False),
            ("llm_service", None),   # resilience frame
        ):
            if hasattr(frame, attr):
                try:
                    object.__setattr__(frame, attr, value)
                except Exception:
                    try:
                        setattr(frame, attr, value)
                    except Exception:
                        pass

    runner = CorpusRunner(corpus_dir, frame)
    return await runner.evaluate(check_id=check_id)


def _get_check_f1(result: "CorpusResult", check_id: str | None) -> float:  # noqa: F821
    """Extract F1 for a specific check or overall F1 if no check given."""
    if check_id and check_id in result.metrics:
        return result.metrics[check_id].f1
    return result.overall_f1


def _snapshot_file(path: Path) -> str:
    """Return SHA-256 hex digest of file contents (for detecting drift)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _apply_pattern_to_exclusions(
    fp_exclusions_file: Path,
    check_id_for_pattern: str,
    pattern: str,
) -> str:
    """
    Append a new regex pattern to the _LIBRARY_SAFE_PATTERNS dict for the given check.

    Returns the original file content (for reverting).
    Raises ValueError if the dict key is not found for that check.
    """
    original = fp_exclusions_file.read_text(encoding="utf-8")
    content = original

    # Inside a raw string r"..." backslashes are already literal — only escape double-quotes.
    escaped_pattern = pattern.replace('"', '\\"')
    new_line = f'        re.compile(r"{escaped_pattern}", re.IGNORECASE),\n'

    # Find the insertion point — the end of the check_id block in _LIBRARY_SAFE_PATTERNS
    # Look for: "    "check_id": [" or "    'check_id': ["
    import re as _re
    block_start = _re.search(
        rf'["\']({_re.escape(check_id_for_pattern)})["\']:\s*\[',
        content,
    )
    if block_start is None:
        raise ValueError(
            f"Check ID '{check_id_for_pattern}' not found in _LIBRARY_SAFE_PATTERNS. "
            "Add the check manually before running autoimprove."
        )

    # Find closing bracket of that list block (first '],' or '],' after block_start)
    search_from = block_start.end()
    close_match = _re.search(r'\n(\s*\])', content[search_from:])
    if close_match is None:
        raise ValueError(f"Could not find closing bracket for '{check_id_for_pattern}' list.")

    insert_at = search_from + close_match.start() + 1  # after the newline before ']'
    content = content[:insert_at] + new_line + content[insert_at:]

    # Atomic write: temp file + rename so a crash never leaves a partial file.
    import os as _os
    import tempfile as _tempfile
    fd, tmp = _tempfile.mkstemp(dir=fp_exclusions_file.parent, prefix=".fp_tmp_", suffix=".py")
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        _os.replace(tmp, fp_exclusions_file)
    except Exception:
        try:
            _os.unlink(tmp)
        except OSError:
            pass
        raise
    return original


def _revert_file(fp_exclusions_file: Path, original_content: str) -> None:
    """Restore fp_exclusions.py to its original content (atomic)."""
    import os as _os
    import tempfile as _tempfile
    fd, tmp = _tempfile.mkstemp(dir=fp_exclusions_file.parent, prefix=".fp_revert_", suffix=".py")
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(original_content)
        _os.replace(tmp, fp_exclusions_file)
    except Exception:
        try:
            _os.unlink(tmp)
        except OSError:
            pass
        raise


async def _ask_llm_for_pattern(
    llm_service,
    check_id: str,
    fp_examples: list[dict],
) -> str | None:
    """Ask the LLM to propose a regex exclusion pattern. Returns pattern string or None."""
    examples_text = "\n".join(
        f"  [{ex['file']} line {ex['line_no']}] {ex['line']}"
        for ex in fp_examples[:10]
    )
    prompt = _AUTOIMPROVE_USER_PROMPT.format(
        check_id=check_id,
        fp_examples=examples_text,
    )

    try:
        response = await llm_service.complete_async(
            prompt=prompt,
            system_prompt=_AUTOIMPROVE_SYSTEM_PROMPT,
            max_tokens=200,
        )
        if not response.success or not response.content.strip():
            return None
        # Extract the pattern — take first non-empty line that isn't explanation
        for line in response.content.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.lower().startswith("pattern"):
                return line
        return None
    except Exception as exc:
        console.print(f"[dim]LLM call failed: {exc}[/dim]")
        return None


def _make_demo_pattern(check_id: str, fp_examples: list[dict]) -> str:
    """Deterministic demo pattern when --fast is used (no LLM call)."""
    # Derive a plausible pattern from the most common word in FP examples
    words: dict[str, int] = {}
    for ex in fp_examples:
        for token in ex["line"].split():
            token = token.strip(".,;()[]{}\"'")
            if len(token) > 3 and token.isidentifier():
                words[token] = words.get(token, 0) + 1

    if words:
        top_word = max(words, key=lambda k: words[k])
        return rf"\b{top_word}\b"
    return rf"\b{check_id}_safe_pattern\b"


async def _autoimprove_loop(
    corpus_dir: Path,
    fp_exclusions_file: Path,
    frame_id: str,
    check_id: str | None,
    iterations: int,
    min_improvement: float,
    dry_run: bool,
    fast: bool,
    llm_service,
) -> None:
    from warden.validation.corpus.runner import format_metrics_table

    # Determine which checks to improve
    checks_to_improve: list[str] = []
    if check_id:
        checks_to_improve = [check_id]
    else:
        # Infer from corpus labels
        for p in sorted(corpus_dir.iterdir()):
            if p.suffix == ".py":
                from warden.validation.corpus.runner import parse_corpus_labels
                labels = parse_corpus_labels(p.read_text(encoding="utf-8", errors="replace"))
                for cid in labels:
                    if cid not in checks_to_improve:
                        checks_to_improve.append(cid)

    if not checks_to_improve:
        console.print("[yellow]No labeled checks found in corpus. Add corpus_labels: blocks.[/yellow]")
        return

    # Baseline evaluation
    console.print("[bold]Step 1/N  Baseline evaluation[/bold]")
    with console.status("Running baseline corpus eval…"):
        try:
            baseline_result = await _run_corpus_eval(corpus_dir, check_id, fast, frame_id)
        except Exception as exc:
            console.print(f"[red]Baseline eval failed: {exc}[/red]")
            return

    baseline_f1 = _get_check_f1(baseline_result, check_id)
    console.print(format_metrics_table(baseline_result))
    console.print(f"\n[bold]Baseline F1:[/bold] {baseline_f1:.4f}\n")

    if baseline_f1 >= 1.0:
        console.print("[green]F1 is already perfect (1.00). No improvements needed.[/green]")
        return

    accepted: list[dict] = []
    rejected: list[dict] = []
    current_f1 = baseline_f1

    for iteration in range(1, iterations + 1):
        console.print(f"[bold cyan]── Iteration {iteration}/{iterations} ──[/bold cyan]")

        # Collect FP examples
        fp_examples = _collect_fp_examples(corpus_dir, check_id)
        if not fp_examples:
            console.print("[dim]No FP examples found. Nothing to improve.[/dim]")
            break

        # Determine which check to target this iteration (rotate through checks with FP)
        target_check = check_id
        if target_check is None:
            # Find the check with the most FPs
            best_fp_check = None
            best_fp_count = 0
            for cid in checks_to_improve:
                m = baseline_result.metrics.get(cid)
                if m and m.fp > best_fp_count:
                    best_fp_count = m.fp
                    best_fp_check = cid
            if best_fp_check is None:
                console.print("[green]All checks have zero FPs. Done.[/green]")
                break
            target_check = best_fp_check

        # Check if there are actual FPs for this check
        check_metrics = baseline_result.metrics.get(target_check)
        if check_metrics and check_metrics.fp == 0:
            console.print(f"[dim]Check '{target_check}' has no FPs. Skipping.[/dim]")
            break

        # Only use FP examples for the check targeted in this iteration.
        target_fp_examples = [ex for ex in fp_examples if ex.get("check_id") == target_check]
        if not target_fp_examples:
            console.print(
                f"[dim]No FP examples found for check '{target_check}'. Skipping iteration.[/dim]"
            )
            continue

        # Get or generate a pattern
        if fast:
            pattern = _make_demo_pattern(target_check, target_fp_examples)
            console.print(f"  [dim]Fast mode — deterministic pattern: [cyan]{pattern}[/cyan][/dim]")
        elif llm_service is None:
            pattern = _make_demo_pattern(target_check, target_fp_examples)
            console.print(f"  [dim]No LLM available — deterministic pattern: [cyan]{pattern}[/cyan][/dim]")
        else:
            console.print(f"  Asking LLM for exclusion pattern (check: {target_check})…")
            pattern = await _ask_llm_for_pattern(llm_service, target_check, target_fp_examples)
            if not pattern:
                console.print("  [yellow]LLM returned no pattern. Skipping iteration.[/yellow]")
                continue
            console.print(f"  LLM proposed: [cyan]{pattern}[/cyan]")

        # Validate the pattern before writing it to fp_exclusions.py.
        # A bad LLM response (e.g. ".*") could suppress all security findings.
        import re as _re
        try:
            compiled = _re.compile(pattern, _re.IGNORECASE)
        except _re.error as regex_err:
            console.print(f"  [red]Pattern is not valid regex — skipping: {regex_err}[/red]")
            continue
        # Reject trivially broad patterns that would suppress everything
        if compiled.pattern in (".*", ".+", "."):
            console.print("  [red]Pattern is dangerously broad — skipping.[/red]")
            continue

        if dry_run:
            console.print(
                f"\n  [yellow][dry-run] Would add to _LIBRARY_SAFE_PATTERNS['{target_check}']:[/yellow]"
            )
            console.print(f"    [bold]re.compile(r\"{pattern}\", re.IGNORECASE)[/bold]")
            console.print(
                f"  [dim]Corpus eval skipped in dry-run. "
                f"Use without --dry-run to apply and measure impact.[/dim]\n"
            )
            # In dry-run, show one iteration and stop
            break

        # Apply pattern temporarily
        try:
            original_content = _apply_pattern_to_exclusions(fp_exclusions_file, target_check, pattern)
        except ValueError as exc:
            console.print(f"  [yellow]Cannot apply pattern: {exc}[/yellow]")
            continue
        except Exception as exc:
            console.print(f"  [red]Failed to modify fp_exclusions.py: {exc}[/red]")
            continue

        # Re-evaluate corpus
        with console.status("Re-scoring corpus…"):
            try:
                new_result = await _run_corpus_eval(corpus_dir, check_id, fast, frame_id)
            except Exception as exc:
                console.print(f"  [red]Corpus eval failed after patch: {exc}[/red]")
                _revert_file(fp_exclusions_file, original_content)
                continue

        new_f1 = _get_check_f1(new_result, check_id)
        delta = new_f1 - current_f1

        if delta >= min_improvement:
            current_f1 = new_f1
            baseline_result = new_result
            accepted.append({"iteration": iteration, "check": target_check, "pattern": pattern, "delta": delta})
            console.print(
                f"  [green]ACCEPTED[/green]  F1: {new_f1:.4f}  "
                f"(+{delta:.4f})  pattern kept in fp_exclusions.py"
            )
        else:
            _revert_file(fp_exclusions_file, original_content)
            rejected.append({"iteration": iteration, "check": target_check, "pattern": pattern, "delta": delta})
            console.print(
                f"  [red]REVERTED[/red]   F1: {new_f1:.4f}  "
                f"({delta:+.4f})  below min-improvement {min_improvement:+.3f}"
            )

        console.print()

        # Stop early if perfect
        if current_f1 >= 1.0:
            console.print("[green]F1 reached 1.00. Stopping.[/green]")
            break

    # Final summary
    console.print("\n[bold]Autoimprove Summary[/bold]")
    console.print(f"  Baseline F1:  {baseline_f1:.4f}")
    console.print(f"  Final F1:     {current_f1:.4f}")
    console.print(f"  Improvement:  {current_f1 - baseline_f1:+.4f}")
    console.print(f"  Accepted:     {len(accepted)}")
    console.print(f"  Rejected:     {len(rejected)}")

    if accepted and not dry_run:
        console.print("\n[green]Patterns kept in fp_exclusions.py:[/green]")
        for item in accepted:
            console.print(
                f"  [dim]iter {item['iteration']}[/dim] [{item['check']}] "
                f"[cyan]{item['pattern']}[/cyan]  (F1 +{item['delta']:.4f})"
            )
        console.print(
            "\n[dim]Review the changes in fp_exclusions.py and commit when satisfied.[/dim]"
        )
