"""
Warden Feedback Commands.

Commands for submitting user feedback on scan findings to close the
learning loop: false positive / true positive labelling persisted to
disk and applied on the next scan to suppress known noise.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from warden.shared.infrastructure.logging import get_logger

console = Console()
logger = get_logger(__name__)

# Create sub-app for feedback commands
feedback_app = typer.Typer(
    name="feedback",
    help="Submit feedback on findings to improve future scans",
    no_args_is_help=True,
)

_LEARNED_PATTERNS_FILE = ".warden/learned_patterns.yaml"
_REPORTS_DIR = ".warden/reports"


def _load_report(project_root: Path, scan_id: Optional[str]) -> dict:
    """
    Load the scan report that contains findings.

    Search order:
    1. .warden/reports/warden-report*.json  (--output or --ci mode)
    2. warden-report.json in project root
    3. .warden/cache/findings_cache.json    (always written by scan)
    """
    reports_dir = project_root / _REPORTS_DIR

    candidates: list[Path] = []

    if reports_dir.is_dir():
        candidates = sorted(
            reports_dir.glob("warden-report*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    # Also include the project-root level report if it exists
    root_report = project_root / "warden-report.json"
    if root_report.exists():
        candidates.insert(0, root_report)

    if scan_id and candidates:
        for candidate in candidates:
            try:
                with open(candidate) as f:
                    data = json.load(f)
                meta = data.get("metadata", {})
                if meta.get("scan_id") == scan_id or data.get("pipelineId") == scan_id:
                    return data
            except Exception:
                continue
        # scan_id was specified but not matched in any candidate
        raise FileNotFoundError(
            f"No warden-report found with scan_id '{scan_id}'. Run 'warden scan' first."
        )

    if candidates:
        with open(candidates[0]) as f:
            return json.load(f)

    # Fallback: findings_cache.json — always written by warden scan
    findings_cache = project_root / ".warden" / "cache" / "findings_cache.json"
    if findings_cache.exists():
        return _load_report_from_findings_cache(findings_cache)

    raise FileNotFoundError(
        "No warden-report found. Run 'warden scan' first."
    )


def _load_report_from_findings_cache(cache_path: Path) -> dict:
    """Convert .warden/cache/findings_cache.json into a report-like dict."""
    with open(cache_path) as f:
        cache = json.load(f)

    all_findings: list[dict] = []
    for entry in cache.values():
        if isinstance(entry, dict):
            for finding in entry.get("findings", []):
                if isinstance(finding, dict):
                    # Normalize: ensure file_path field exists
                    if "file_path" not in finding and "location" in finding:
                        loc = finding["location"]
                        finding["file_path"] = loc.split(":")[0] if ":" in loc else loc
                    all_findings.append(finding)

    return {"findings": all_findings, "frameResults": []}


def _collect_all_findings(report: dict) -> list[dict]:
    """Flatten all findings from all frame results in the report."""
    findings: list[dict] = []

    # Top-level findings list
    for f in report.get("findings", []):
        if isinstance(f, dict):
            findings.append(f)

    # Per-frame findings
    for frame in report.get("frameResults", report.get("frame_results", [])):
        for f in frame.get("findings", []):
            if isinstance(f, dict):
                findings.append(f)

    # Deduplicate by id
    seen: set[str] = set()
    unique: list[dict] = []
    for f in findings:
        fid = f.get("id") or f.get("rule_id", "")
        key = f"{fid}:{f.get('file_path', '')}"
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def _resolve_finding_ids(
    requested_ids: list[str],
    all_findings: list[dict],
) -> tuple[list[dict], list[str]]:
    """
    Resolve requested rule/finding IDs to actual finding dicts.

    Uses exact match only — prefix matching would unintentionally suppress
    findings with the same rule_id across unrelated files.

    Returns (matched_findings, unmatched_ids).
    """
    matched: list[dict] = []
    unmatched: list[str] = []

    for req_id in requested_ids:
        found = False
        for f in all_findings:
            fid = f.get("id") or f.get("rule_id", "")
            if fid == req_id:
                matched.append(f)
                found = True
        if not found:
            unmatched.append(req_id)

    return matched, unmatched


@feedback_app.command(name="mark")
def mark_command(
    false_positives: Optional[str] = typer.Option(
        None,
        "--false-positives",
        "-fp",
        help="Comma-separated finding IDs to mark as false positives",
    ),
    true_positives: Optional[str] = typer.Option(
        None,
        "--true-positives",
        "-tp",
        help="Comma-separated finding IDs to confirm as true positives",
    ),
    scan_id: Optional[str] = typer.Option(
        None,
        "--scan-id",
        "-s",
        help="Scan ID (pipeline_id or short scan_id) to load findings from",
    ),
    project_dir: Optional[str] = typer.Option(
        None,
        "--project",
        "-p",
        help="Project root directory (defaults to current directory)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force suppression of CRITICAL/HIGH severity findings (bypasses safety gate)",
    ),
) -> None:
    """
    Mark findings as false positives or confirm as true positives.

    Warden learns from your feedback and suppresses known false positives
    on future scans automatically.

    CRITICAL and HIGH severity findings cannot be marked as false positives
    without --force to prevent accidental suppression of real security issues.

    Examples:

        warden feedback mark --false-positives W001,W003 --scan-id abc123

        warden feedback mark --true-positives W002

        warden feedback mark --false-positives W001 --force
    """
    if not false_positives and not true_positives:
        console.print("[red]Error:[/red] Provide --false-positives and/or --true-positives.")
        raise typer.Exit(code=1)

    fp_ids: list[str] = [x.strip() for x in (false_positives or "").split(",") if x.strip()]
    tp_ids: list[str] = [x.strip() for x in (true_positives or "").split(",") if x.strip()]

    project_root = Path(project_dir).resolve() if project_dir else Path.cwd()

    try:
        report = _load_report(project_root, scan_id)
    except FileNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    all_findings = _collect_all_findings(report)

    if not all_findings:
        console.print("[yellow]No findings found in the report.[/yellow]")
        console.print("[dim]Run 'warden scan' to generate findings first.[/dim]")
        raise typer.Exit(code=0)

    # Resolve IDs
    fp_findings, fp_unmatched = _resolve_finding_ids(fp_ids, all_findings)
    tp_findings, tp_unmatched = _resolve_finding_ids(tp_ids, all_findings)

    if fp_unmatched:
        console.print(f"[yellow]Warning:[/yellow] Could not resolve IDs: {', '.join(fp_unmatched)}")
    if tp_unmatched:
        console.print(f"[yellow]Warning:[/yellow] Could not resolve IDs: {', '.join(tp_unmatched)}")

    if not fp_findings and not tp_findings:
        console.print("[red]Error:[/red] No matching findings found. Check your IDs and scan report.")
        raise typer.Exit(code=1)

    # Safety gate: block silent suppression of CRITICAL/HIGH findings
    if fp_findings and not force:
        risky = [
            f for f in fp_findings
            if f.get("severity", "").lower() in ("critical", "high")
        ]
        if risky:
            console.print(
                f"\n[bold red]Safety gate:[/bold red] {len(risky)} CRITICAL/HIGH finding(s) "
                "requested for false-positive suppression:"
            )
            for f in risky:
                sev = f.get("severity", "unknown").upper()
                fid = f.get("id") or f.get("rule_id", "?")
                path = f.get("file_path") or f.get("path", "?")
                console.print(f"  [bold red]•[/bold red] [{sev}] {fid} in {path}")
            console.print(
                "\n[dim]If these are genuine false positives, re-run with [bold]--force[/bold].[/dim]"
            )
            raise typer.Exit(code=1)

    console.print(
        f"[cyan]Processing feedback:[/cyan] "
        f"{len(fp_findings)} false positive(s), {len(tp_findings)} true positive(s)"
    )

    asyncio.run(
        _run_feedback_async(
            fp_findings=fp_findings,
            tp_findings=tp_findings,
            fp_ids=fp_ids,
            tp_ids=tp_ids,
            all_findings=all_findings,
            project_root=project_root,
        )
    )


async def _run_feedback_async(
    fp_findings: list[dict],
    tp_findings: list[dict],
    fp_ids: list[str],
    tp_ids: list[str],
    all_findings: list[dict],
    project_root: Path,
) -> None:
    """Run the async feedback learning pipeline."""
    from warden.classification.application.llm_classification_phase import (
        LLMClassificationPhase,
    )
    from warden.analysis.application.llm_phase_base import LLMPhaseConfig

    try:
        # Build a minimal phase config (LLM optional — persist still works without it)
        phase_config = LLMPhaseConfig(enabled=False)
        phase = LLMClassificationPhase(config=phase_config, llm_service=None)

        await phase.learn_from_feedback_async(
            false_positive_ids=fp_ids,
            true_positive_ids=tp_ids,
            findings=all_findings,
        )

        # Persist learned patterns to disk regardless of LLM availability
        patterns = _build_patterns_from_findings(fp_findings, tp_findings)
        LLMClassificationPhase._persist_learned_patterns(patterns, project_root)

        _print_feedback_summary(fp_findings, tp_findings)

    except Exception as exc:
        logger.error("feedback_processing_failed", error=str(exc))
        console.print(f"[red]Error processing feedback:[/red] {exc}")
        raise typer.Exit(code=1)


def _build_patterns_from_findings(
    fp_findings: list[dict],
    tp_findings: list[dict],
) -> dict:
    """Build a raw patterns dict from finding lists before persistence merge."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    patterns: list[dict] = []

    for f in fp_findings:
        rule_id = f.get("id") or f.get("rule_id") or ""
        file_path = f.get("file_path") or f.get("path") or ""
        message = f.get("message") or ""

        patterns.append(
            {
                "rule_id": rule_id,
                "file_pattern": str(Path(file_path).name) if file_path else "",
                "message_pattern": message[:80] if message else "",
                "type": "false_positive",
                "occurrence_count": 1,
                "confidence": 0.5,
                "first_seen": now,
                "last_seen": now,
            }
        )

    for f in tp_findings:
        rule_id = f.get("id") or f.get("rule_id") or ""
        file_path = f.get("file_path") or f.get("path") or ""
        message = f.get("message") or ""

        patterns.append(
            {
                "rule_id": rule_id,
                "file_pattern": str(Path(file_path).name) if file_path else "",
                "message_pattern": message[:80] if message else "",
                "type": "true_positive",
                "occurrence_count": 1,
                "confidence": 0.5,
                "first_seen": now,
                "last_seen": now,
            }
        )

    return {"version": 1, "patterns": patterns}


def _print_feedback_summary(fp_findings: list[dict], tp_findings: list[dict]) -> None:
    """Print a human-readable feedback summary."""
    console.print("\n[bold green]Feedback recorded successfully.[/bold green]")

    if fp_findings:
        console.print(f"\n[bold]False Positives Suppressed ({len(fp_findings)}):[/bold]")
        for f in fp_findings:
            rule = f.get("id") or f.get("rule_id", "unknown")
            path = f.get("file_path") or f.get("path", "unknown")
            console.print(f"  [dim]•[/dim] [yellow]{rule}[/yellow] in {path}")

    if tp_findings:
        console.print(f"\n[bold]True Positives Confirmed ({len(tp_findings)}):[/bold]")
        for f in tp_findings:
            rule = f.get("id") or f.get("rule_id", "unknown")
            path = f.get("file_path") or f.get("path", "unknown")
            console.print(f"  [dim]•[/dim] [red]{rule}[/red] in {path}")

    console.print(
        "\n[dim]Patterns saved to .warden/learned_patterns.yaml. "
        "They will be applied on the next scan.[/dim]"
    )


@feedback_app.command(name="list")
def list_command(
    project_dir: Optional[str] = typer.Option(
        None,
        "--project",
        "-p",
        help="Project root directory (defaults to current directory)",
    ),
) -> None:
    """
    List accumulated learned patterns from feedback.

    Shows all patterns Warden has learned from previous feedback sessions,
    including their confidence scores and occurrence counts.

    Example:

        warden feedback list
    """
    project_root = Path(project_dir).resolve() if project_dir else Path.cwd()
    patterns_file = project_root / _LEARNED_PATTERNS_FILE

    if not patterns_file.exists():
        console.print("[yellow]No learned patterns found.[/yellow]")
        console.print(
            "[dim]Run 'warden feedback mark --false-positives ...' to teach Warden.[/dim]"
        )
        return

    try:
        import yaml

        with open(patterns_file) as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        console.print(f"[red]Error reading learned patterns:[/red] {exc}")
        raise typer.Exit(code=1)

    patterns = data.get("patterns", [])
    version = data.get("version", "?")

    if not patterns:
        console.print("[yellow]Learned patterns file exists but contains no patterns.[/yellow]")
        return

    console.print(f"\n[bold cyan]Learned Patterns[/bold cyan] (schema v{version})\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Rule ID", style="cyan", min_width=20)
    table.add_column("Type", min_width=14)
    table.add_column("File Pattern", min_width=20)
    table.add_column("Message Pattern", min_width=30)
    table.add_column("Seen", justify="right")
    table.add_column("Confidence", justify="right")

    for p in patterns:
        ptype = p.get("type", "unknown")
        type_color = "yellow" if ptype == "false_positive" else "red"
        table.add_row(
            str(p.get("rule_id", "")),
            f"[{type_color}]{ptype}[/{type_color}]",
            str(p.get("file_pattern", "")),
            str(p.get("message_pattern", ""))[:40],
            str(p.get("occurrence_count", 1)),
            f"{p.get('confidence', 0.0):.2f}",
        )

    console.print(table)
    console.print(
        f"\n[dim]{len(patterns)} pattern(s) total. "
        "Patterns with confidence >= 0.8 suppress findings automatically.[/dim]"
    )


@feedback_app.command(name="unmark")
def unmark_command(
    finding_ids: str = typer.Argument(
        ...,
        help="Comma-separated rule IDs to remove from learned patterns",
    ),
    project_dir: Optional[str] = typer.Option(
        None,
        "--project",
        "-p",
        help="Project root directory (defaults to current directory)",
    ),
) -> None:
    """
    Remove learned patterns to re-enable previously suppressed findings.

    Use this to undo a false-positive marking and restore a finding to future
    scan results.

    Example:

        warden feedback unmark W001,W003
    """
    import yaml

    ids_to_remove = [x.strip() for x in finding_ids.split(",") if x.strip()]
    if not ids_to_remove:
        console.print("[red]Error:[/red] Provide at least one rule ID.")
        raise typer.Exit(code=1)

    project_root = Path(project_dir).resolve() if project_dir else Path.cwd()
    patterns_file = project_root / _LEARNED_PATTERNS_FILE

    if not patterns_file.exists():
        console.print("[yellow]No learned patterns file found — nothing to unmark.[/yellow]")
        raise typer.Exit(code=0)

    try:
        with open(patterns_file) as f:
            data = yaml.safe_load(f) or {}
    except Exception as exc:
        console.print(f"[red]Error reading learned patterns:[/red] {exc}")
        raise typer.Exit(code=1)

    existing = data.get("patterns", [])
    before_count = len(existing)

    kept = [p for p in existing if p.get("rule_id", "") not in ids_to_remove]
    removed_count = before_count - len(kept)

    if removed_count == 0:
        console.print(
            f"[yellow]No patterns found for IDs:[/yellow] {', '.join(ids_to_remove)}"
        )
        raise typer.Exit(code=0)

    data["patterns"] = kept

    try:
        with open(patterns_file, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    except Exception as exc:
        console.print(f"[red]Error writing learned patterns:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(
        f"\n[bold green]Unmarked {removed_count} pattern(s).[/bold green]"
    )
    console.print(
        f"[dim]Findings with rule ID(s) {', '.join(ids_to_remove)} "
        "will appear again on the next scan.[/dim]"
    )
