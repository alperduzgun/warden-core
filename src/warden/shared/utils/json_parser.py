"""
Robust JSON Parser for LLM Responses.

Handles common LLM output formatting issues:
- Markdown code blocks (```json ... ```)
- Plain text wrapping
- Trailing commas
- Missing brackets (in simple cases)
"""

import json
import re
from typing import Any

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


def parse_json_from_llm(response: str) -> dict[str, Any] | list[Any] | None:
    """
    Extract and parse JSON from an LLM response string with robust repair logic.
    """
    if not response:
        return None

    # 1. Extraction: Find potential JSON block
    markdown_pattern = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
    match = markdown_pattern.search(response)

    cleaned_json = response
    if match:
        cleaned_json = match.group(1).strip()
    else:
        # Fallback recursive search for first { and last }
        first_brace = cleaned_json.find("{")
        first_bracket = cleaned_json.find("[")
        start_idx = -1
        if first_brace != -1 and first_bracket != -1:
            start_idx = min(first_brace, first_bracket)
        elif first_brace != -1:
            start_idx = first_brace
        elif first_bracket != -1:
            start_idx = first_bracket

        if start_idx != -1:
            last_brace = cleaned_json.rfind("}")
            last_bracket = cleaned_json.rfind("]")
            end_idx = max(last_brace, last_bracket)
            if end_idx != -1 and end_idx > start_idx:
                cleaned_json = cleaned_json[start_idx : end_idx + 1]

    # 2. Truncation recovery: close incomplete JSON structures
    cleaned_json = _recover_truncated_json(cleaned_json)

    # 3. Repair Strategy (Chaos Engineering)
    try:
        return json.loads(cleaned_json)
    except json.JSONDecodeError:
        # Attempt repair
        repaired_json = _repair_json(cleaned_json)
        try:
            return json.loads(repaired_json)
        except json.JSONDecodeError as e:
            logger.warning("json_repair_failed", error=str(e), snippet=cleaned_json[:100])
            return None


def _recover_truncated_json(json_str: str) -> str:
    """
    Recover JSON truncated by LLM max_tokens cutoff.

    Common patterns:
    - Array cut mid-object: '[{"a":1},{"b":2' → '[{"a":1}]'
    - Object cut mid-value: '{"a":1,"b":"trunc' → '{"a":1}'
    - Nested structure: '[{"a":[1,2' → '[{"a":[1,2]}]'
    - Corrupt tail: valid JSON + garbage at end
    """
    s = json_str.strip()
    if not s:
        return s

    # Already valid structure — try parse first
    if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
        try:
            json.loads(s)
            return s
        except json.JSONDecodeError:
            pass  # Fall through to recovery

    # Strategy: for {"findings": [...]} pattern, find the last complete
    # object in the array and close the structure.
    if s.startswith("{"):
        recovered = _recover_findings_array(s)
        if recovered:
            return recovered

    # Truncated array: starts with [ but no closing ]
    if s.startswith("[") and not s.endswith("]"):
        last_brace = s.rfind("}")
        if last_brace > 0:
            s = s[: last_brace + 1] + "]"
            logger.debug("json_truncation_recovered", type="array", action="closed_at_last_object")
            return s

    # Truncated object: starts with { but no closing }
    if s.startswith("{") and not s.endswith("}"):
        last_comma = s.rfind(",")
        if last_comma > 0:
            s = s[:last_comma] + "}"
            logger.debug("json_truncation_recovered", type="object", action="closed_at_last_comma")
            return s

    return json_str


def _recover_findings_array(json_str: str) -> str | None:
    """Recover a truncated {"findings": [...]} structure by progressively
    removing trailing objects until parsing succeeds."""
    # Quick check: does this look like a findings response?
    if '"findings"' not in json_str[:100]:
        return None

    # Find the start of the findings array
    arr_start = json_str.find("[")
    if arr_start < 0:
        return None

    # Strategy: find each complete "},{" boundary working backwards
    # and try closing the structure there.
    pos = len(json_str)
    for _ in range(50):  # Max 50 attempts
        # Find last "},\n" or "}, " or "},{"  boundary before pos
        candidate = json_str.rfind("}", 0, pos)
        if candidate <= arr_start:
            break

        # Try closing the JSON here: trim to this }, close array + object
        attempt = json_str[: candidate + 1] + "]}"
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, dict) and "findings" in parsed:
                count = len(parsed["findings"])
                logger.info("json_truncation_recovered_findings", recovered_count=count)
                return attempt
        except json.JSONDecodeError:
            pass
        pos = candidate  # Move backwards

    return None


def _repair_json(json_str: str) -> str:
    """
    Common LLM JSON repairs:
    - Fix missing quotes on keys: { key: "val" } -> { "key": "val" }
    - Remove trailing commas: [1, 2,] -> [1, 2]
    - Remove control characters.
    - Handle True/False/None to true/false/null
    """
    # Remove control characters
    json_str = re.sub(r"[\x00-\x1F\x7F]", "", json_str)

    # Fix missing quotes on keys (looks for keys followed by :)
    # Pattern: finds an alphanumeric word at start of object or after comma/brace, not inside quotes
    json_str = re.sub(r"([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', json_str)

    # Remove trailing commas before closing braces/brackets
    json_str = re.sub(r",\s*([\]}])", r"\1", json_str)

    # Python-isms (hallucinated by local models trained on Python)
    json_str = re.sub(r"\bTrue\b", "true", json_str)
    json_str = re.sub(r"\bFalse\b", "false", json_str)
    json_str = re.sub(r"\bNone\b", "null", json_str)

    return json_str
