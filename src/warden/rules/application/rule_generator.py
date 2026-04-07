"""AI-powered rule generator for 'warden rules generate'.

Detects project language/framework and asks the LLM to produce
type:ai rules in the .warden/rules/llm_generated.yml format.
"""

from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger(__name__)

REQUIRED_FIELDS: frozenset[str] = frozenset(
    {"id", "name", "category", "severity", "isBlocker", "description", "enabled", "type"}
)
OUTPUT_FILENAME = "llm_generated.yml"

_RULE_GEN_PROMPT = """\
You are a senior security engineer writing Warden rule definitions.

Project details:
- Language: {language}
- Framework: {framework}

Generate 3-5 rules for this project in YAML format.
Each rule MUST have exactly these fields:
  id: (kebab-case string, unique)
  name: (human-readable string)
  category: (one of: security, convention, performance, custom, architectural, consistency, backend-ipc, logic)
  severity: (one of: critical, high, medium, low)
  isBlocker: (true or false)
  description: "quoted string — specific, actionable directive. Tells the LLM auditor exactly what to flag. MUST be quoted because it may contain colons."
  enabled: true
  type: "ai"
  language: [list of applicable languages, e.g. [python] or [javascript, typescript]]
  file_pattern: "glob pattern limiting which files to check, e.g. *.py or src/**/*.ts"
  context: "quoted string — architectural guidance for the LLM auditor to AVOID FALSE POSITIVES.
    Describe: (1) how exceptions propagate in this framework (e.g. global handler, middleware),
    (2) which file types or components are OUT OF SCOPE for this rule (e.g. background workers,
    startup/lifespan code, test files), (3) any known safe patterns that look like violations
    but are not (e.g. bare awaits in service layer where errors propagate to HTTP middleware),
    (4) what actually constitutes a REAL violation vs an acceptable pattern.
    MUST be quoted. Be specific to the framework: {framework}."

IMPORTANT: ALL string values that may contain colons, commas, or special characters MUST be wrapped in double quotes.

Return ONLY a valid YAML block starting with `rules:` — no markdown, no explanation, no code fences.

Example output:
rules:
  - id: no-raw-sql-concat
    name: "No Raw SQL Concatenation"
    category: security
    severity: critical
    isBlocker: true
    description: "Detect SQL queries built via string concatenation or f-strings containing SELECT/INSERT/UPDATE/DELETE. Flag any occurrence regardless of context."
    enabled: true
    type: ai
    language: [python]
    file_pattern: "*.py"
    context: "Django/FastAPI project. ORM queries via .filter()/.get() are safe — flag only raw cursor.execute() or string-interpolated SQL. Test files are out of scope. Migration files are out of scope."
"""

_PY_FRAMEWORKS: frozenset[str] = frozenset(
    {"django", "flask", "fastapi", "pyramid", "tornado", "fastmcp", "mcp"}
)
_JS_FRAMEWORKS: frozenset[str] = frozenset(
    {"react", "vue", "angular", "next", "nuxt", "svelte", "express", "nest"}
)


def _infer_language(framework: str) -> str:
    fw = framework.lower()
    if fw in _PY_FRAMEWORKS:
        return "python"
    if fw in _JS_FRAMEWORKS:
        return "javascript/typescript"
    return "unknown"


async def generate_rules_for_project(
    project_path: Path,
    llm_service: Any,
    force: bool = False,
) -> int:
    """Generate AI rules for a project and write to .warden/rules/llm_generated.yml.

    Args:
        project_path: Root directory of the project.
        llm_service: LLM service instance with a ``complete_async`` method.
        force: Overwrite existing file when True; skip when False.

    Returns:
        Number of rules written, or -1 when skipped (file exists, force=False).

    Raises:
        ValueError: LLM output is unparseable or missing required fields.
    """
    from warden.analysis.application.discovery.framework_detector import detect_frameworks_async  # noqa: PLC0415

    warden_dir = project_path / ".warden"
    single_file = warden_dir / "rules.yaml"

    # Determine where to write based on existing config structure:
    # - If .warden/rules.yaml exists → loader uses that file only; write there (append rules section)
    # - Otherwise → write to .warden/rules/llm_generated.yml (directory mode)
    if single_file.exists():
        output_path = single_file
        single_file_mode = True
    else:
        output_path = warden_dir / "rules" / OUTPUT_FILENAME
        single_file_mode = False

    # Skip guard applies only in directory mode (new standalone file)
    if not single_file_mode and output_path.exists() and not force:
        logger.info("llm_generated_rules_exist_skip", path=str(output_path))
        return -1

    # Detect language + framework
    detection = await detect_frameworks_async(project_path)
    framework = detection.primary_framework.value if detection.primary_framework else "unknown"
    language = _infer_language(framework)

    logger.info("rule_generation_started", language=language, framework=framework)

    prompt = _RULE_GEN_PROMPT.format(language=language, framework=framework)

    response = await llm_service.complete_async(
        prompt=prompt,
        system_prompt="You are a Warden rule definition generator. Output YAML only.",
    )
    raw: str = response.content if hasattr(response, "content") else str(response)

    # Parse
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"LLM returned invalid YAML: {exc}") from exc

    if not isinstance(data, dict) or "rules" not in data:
        raise ValueError(f"LLM output missing 'rules' key. Got: {raw[:300]}")

    rules = data["rules"]
    if not isinstance(rules, list) or len(rules) == 0:
        raise ValueError("LLM returned empty rules list.")

    # Validate required fields per rule
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"Rule #{i} is not a mapping.")
        missing = REQUIRED_FIELDS - set(rule.keys())
        if missing:
            raise ValueError(f"Rule #{i} (id={rule.get('id', '?')!r}) missing fields: {missing}")
        if rule.get("type") != "ai":
            raise ValueError(
                f"Rule #{i} (id={rule.get('id', '?')!r}) must have type: ai, got: {rule.get('type')!r}"
            )

    # Write
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if single_file_mode:
        # Append generated rules into the existing rules.yaml under a `rules:` key.
        # Read current content, merge rule IDs to avoid duplicates, then rewrite.
        existing_text = output_path.read_text(encoding="utf-8")
        try:
            existing_data: dict = yaml.safe_load(existing_text) or {}
        except yaml.YAMLError:
            existing_data = {}

        existing_rules: list = existing_data.get("rules", [])
        existing_ids = {r.get("id") for r in existing_rules if isinstance(r, dict)}

        if not force:
            new_rules = [r for r in rules if r.get("id") not in existing_ids]
        else:
            # force: replace any rule with same id, keep unrelated ones
            new_rules_by_id = {r["id"]: r for r in rules}
            existing_rules = [r for r in existing_rules if r.get("id") not in new_rules_by_id]
            new_rules = list(new_rules_by_id.values())

        if not new_rules:
            logger.info("llm_generated_rules_all_duplicate_skip", path=str(output_path))
            return 0

        existing_data["rules"] = existing_rules + new_rules

        # Register new rule IDs in global_rules so the orchestrator activates them.
        # Rules in the `rules:` section but absent from `global_rules:` are never run.
        existing_global: list = existing_data.get("global_rules", [])
        new_ids = [r["id"] for r in new_rules]
        existing_data["global_rules"] = existing_global + [rid for rid in new_ids if rid not in existing_global]

        ai_header = (
            "# Rules section includes AI-generated entries from 'warden rules generate'.\n"
            "# Review before committing. Regenerate with: warden rules generate --force\n\n"
        )
        output_path.write_text(
            ai_header + yaml.dump(existing_data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        written_count = len(new_rules)
    else:
        # Directory mode: write standalone file; also inject global_rules so they activate.
        new_ids = [r["id"] for r in rules]
        data["global_rules"] = new_ids
        header = (
            "# Auto-generated by 'warden rules generate'\n"
            "# Review this file before committing to your repository.\n"
            "# To regenerate: warden rules generate --force\n\n"
        )
        output_path.write_text(
            header + yaml.dump(data, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )
        written_count = len(rules)

    logger.info("llm_generated_rules_written", path=str(output_path), count=written_count, mode="single_file" if single_file_mode else "directory")
    return written_count
