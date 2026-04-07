"""Rule refiner: detect false positives in scan findings and update rule context.

After a 'warden scan', run 'warden rules refine' to classify cached findings
with an LLM and append acceptable-pattern guidance to the context field of
AI rules that produced false positives.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_FP_CLASSIFY_PROMPT = """\
You are a security code reviewer. A rule flagged the following code snippet. Determine if it is a real violation or an acceptable pattern (false positive).

Rule: "{rule_name}"
Description: {rule_description}
{context_block}
File: {filename}, line {line}

Code:
{code_snippet}

Respond ONLY in JSON (no markdown, no explanation):
{{
  "verdict": "real" or "false_positive",
  "pattern": "short description of the acceptable pattern (only if false_positive, else empty string)",
  "reason": "one sentence explanation"
}}"""


@dataclass
class RefinementResult:
    """Result of a rules-refinement pass."""

    updates: list[dict] = field(default_factory=list)
    analyzed: int = 0
    skipped_real: int = 0
    skipped_duplicate: int = 0


def _read_code_snippet(file_path: Path, line: int, context_lines: int = 10) -> str:
    """Return up to 2*context_lines lines surrounding *line* from *file_path*.

    Returns empty string when the file cannot be read.
    Line numbers are 1-based; line=0 is treated as "beginning of file".
    """
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""

    if not lines:
        return ""

    # Treat 0 as "unknown line" — show the first 20 lines as best-effort context.
    if line <= 0:
        end = min(20, len(lines))
        return "\n".join(f"{i + 1}: {lines[i]}" for i in range(end))

    # 1-based → 0-based index
    idx = line - 1
    start = max(0, idx - context_lines)
    end = min(len(lines), idx + context_lines + 1)
    return "\n".join(f"{i + 1}: {lines[i]}" for i in range(start, end))


def _parse_cache_key(cache_key: str) -> tuple[str, str, str]:
    """Parse a findings-cache key of the form ``{frame_id}:{file_path}:{hash}``.

    Returns ``(frame_id, file_path, hash_value)``.
    The file path may itself contain colons (e.g. Windows absolute paths), so
    the split is anchored to the first and last segments only.
    """
    parts = cache_key.split(":")
    if len(parts) < 3:
        return cache_key, "", ""
    frame_id = parts[0]
    hash_value = parts[-1]
    file_path = ":".join(parts[1:-1])
    return frame_id, file_path, hash_value


def _parse_llm_json(raw: str) -> dict | None:
    """Strip markdown fences from *raw* and attempt JSON parse.

    Returns the parsed dict on success, or None on failure.
    """
    cleaned = (
        raw.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def _collect_findings_from_cache(
    cache_path: Path,
    ai_rule_ids: set[str],
) -> list[tuple[str, Path | None, int]]:
    """Read findings_cache.json and return (rule_id, source_file, line) tuples."""
    if not cache_path.exists():
        return []
    try:
        cache: dict[str, Any] = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("findings_cache_read_error", path=str(cache_path), error=str(exc))
        return []

    collected = []
    for cache_key, entry in cache.items():
        findings: list[dict] = entry.get("findings", [])
        if not findings:
            continue
        _frame_id, file_path_str, _hash = _parse_cache_key(cache_key)
        source_file = Path(file_path_str) if file_path_str else None
        for finding in findings:
            rule_id = finding.get("id", "")
            if rule_id in ai_rule_ids:
                collected.append((rule_id, source_file, finding.get("line", 0)))
    return collected


def _collect_findings_from_baseline(
    baseline_dir: Path,
    ai_rule_ids: set[str],
) -> list[tuple[str, Path | None, int]]:
    """Read .warden/baseline/*.json and return (rule_id, source_file, line) tuples.

    Custom rule violations (frame_id=global_script_rules) are stored in the
    baseline after each scan but NOT in findings_cache.json.
    """
    if not baseline_dir.exists():
        return []

    collected = []
    for baseline_file in sorted(baseline_dir.glob("*.json")):
        if baseline_file.name == "_meta.json":
            continue
        try:
            data: dict = json.loads(baseline_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        for finding in data.get("findings", []):
            rule_id = finding.get("id", "")
            if rule_id not in ai_rule_ids:
                continue
            location: str = finding.get("location", "")
            source_file: Path | None = None
            line = finding.get("line", 0)
            if location:
                # location format: "/abs/path/to/file:lineno"
                parts = location.rsplit(":", 1)
                if len(parts) == 2 and parts[1].isdigit():
                    source_file = Path(parts[0])
                    if line == 0:
                        line = int(parts[1])
                else:
                    source_file = Path(location)
            collected.append((rule_id, source_file, line))
    return collected


async def refine_rules(
    project_path: Path,
    llm_service: Any,
    rule_ids: list[str] | None = None,
    dry_run: bool = False,
) -> RefinementResult:
    """Classify scan findings with an LLM and update AI rule context fields.

    Reads from both findings_cache.json (structural frames) and the baseline
    (custom AI rule violations, stored under .warden/baseline/).

    Args:
        project_path: Root of the project (must contain .warden/).
        llm_service: LLM client with a ``complete_async(prompt, system_prompt)`` method.
        rule_ids: If provided, only analyse findings for these rule IDs.
        dry_run: When True, compute updates but do not write rules.yaml.

    Returns:
        :class:`RefinementResult` summarising what was done.
    """
    from warden.rules.infrastructure.yaml_loader import RulesYAMLLoader  # noqa: PLC0415

    result = RefinementResult()

    # 1. Load AI rules
    rule_config = RulesYAMLLoader.load_rules_sync(project_path)
    ai_rules: dict[str, Any] = {
        r.id: r
        for r in rule_config.rules
        if r.enabled and r.type == "ai"
    }

    if rule_ids:
        ai_rules = {rid: r for rid, r in ai_rules.items() if rid in rule_ids}

    if not ai_rules:
        logger.info("no_ai_rules_to_refine")
        return result

    ai_rule_ids = set(ai_rules.keys())

    # 2. Collect findings from all sources, deduplicate by (rule_id, path, line)
    raw_findings: list[tuple[str, Path | None, int]] = []
    raw_findings += _collect_findings_from_cache(
        project_path / ".warden" / "cache" / "findings_cache.json",
        ai_rule_ids,
    )
    raw_findings += _collect_findings_from_baseline(
        project_path / ".warden" / "baseline",
        ai_rule_ids,
    )

    # Deduplicate: same (rule_id, resolved_path, line) counted once
    seen: set[tuple[str, str, int]] = set()
    deduped: list[tuple[str, Path | None, int]] = []
    for rule_id, src, line in raw_findings:
        key = (rule_id, str(src), line)
        if key not in seen:
            seen.add(key)
            deduped.append((rule_id, src, line))

    if not deduped:
        warden_dir = project_path / ".warden"
        if not warden_dir.exists():
            logger.warning("no_findings_found", reason="no .warden directory")
        else:
            logger.info("no_ai_rule_findings_found", hint="Run 'warden scan' first")
        return result

    # 3. Classify each unique finding with LLM
    fp_by_rule: dict[str, list[dict[str, str]]] = {rid: [] for rid in ai_rules}

    for finding_rule_id, source_file, line in deduped:
        rule = ai_rules[finding_rule_id]
        snippet = _read_code_snippet(source_file, line) if source_file else ""

        context_block = (
            f"Existing context:\n{rule.context}\n" if rule.context else ""
        )

        prompt = _FP_CLASSIFY_PROMPT.format(
            rule_name=rule.name,
            rule_description=rule.description,
            context_block=context_block,
            filename=source_file.name if source_file else "unknown",
            line=line if line > 0 else "unknown",
            code_snippet=snippet or "(source not available)",
        )

        logger.debug(
            "classifying_finding",
            rule_id=finding_rule_id,
            file=str(source_file),
            line=line,
        )

        try:
            response = await llm_service.complete_async(
                prompt=prompt,
                system_prompt=(
                    "You are a security code reviewer. "
                    "Respond only in JSON as instructed."
                ),
            )
            raw: str = response.content if hasattr(response, "content") else str(response)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "llm_classify_error",
                rule_id=finding_rule_id,
                error=str(exc),
            )
            continue

        parsed = _parse_llm_json(raw)
        if parsed is None:
            logger.warning(
                "llm_json_parse_failed",
                rule_id=finding_rule_id,
                raw=raw[:200],
            )
            continue

        result.analyzed += 1
        verdict: str = parsed.get("verdict", "real")
        pattern: str = parsed.get("pattern", "")
        reason: str = parsed.get("reason", "")

        if verdict != "false_positive":
            result.skipped_real += 1
            continue

        if not pattern:
            result.skipped_real += 1
            continue

        fp_by_rule[finding_rule_id].append({"pattern": pattern, "reason": reason})

    # 4. Build context updates, skipping duplicates
    context_updates: dict[str, str] = {}

    for rule_id, fp_list in fp_by_rule.items():
        if not fp_list:
            continue

        rule = ai_rules[rule_id]
        existing_context: str = rule.context or ""
        new_lines: list[str] = []

        for fp in fp_list:
            pattern = fp["pattern"]
            reason = fp["reason"]
            # Dedup: skip if pattern already mentioned (case-insensitive)
            if pattern.lower() in existing_context.lower():
                result.skipped_duplicate += 1
                continue
            new_lines.append(f"Acceptable: {pattern} — {reason}")

        if not new_lines:
            continue

        separator = "\n" if existing_context else ""
        new_context = existing_context + separator + "\n".join(new_lines)
        context_updates[rule_id] = new_context
        result.updates.append(
            {
                "rule_id": rule_id,
                "pattern": new_lines[0],  # primary pattern for display
                "reason": fp_list[0]["reason"],
                "new_context": new_context,
            }
        )

    # 5. Persist unless dry-run
    if context_updates and not dry_run:
        RulesYAMLLoader.update_rule_contexts(project_path, context_updates)
        logger.info(
            "rule_contexts_updated",
            count=len(context_updates),
            rule_ids=list(context_updates.keys()),
        )

    return result
