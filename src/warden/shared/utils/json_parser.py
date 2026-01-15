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
from typing import Any, Dict, List, Union
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)

def parse_json_from_llm(response: str) -> Union[Dict[str, Any], List[Any], None]:
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
        first_brace = cleaned_json.find('{')
        first_bracket = cleaned_json.find('[')
        start_idx = -1
        if first_brace != -1 and first_bracket != -1:
            start_idx = min(first_brace, first_bracket)
        elif first_brace != -1:
            start_idx = first_brace
        elif first_bracket != -1:
            start_idx = first_bracket
            
        if start_idx != -1:
            last_brace = cleaned_json.rfind('}')
            last_bracket = cleaned_json.rfind(']')
            end_idx = max(last_brace, last_bracket)
            if end_idx != -1 and end_idx > start_idx:
                cleaned_json = cleaned_json[start_idx:end_idx+1]

    # 2. Repair Strategy (Chaos Engineering)
    try:
        return json.loads(cleaned_json)
    except json.JSONDecodeError:
        # Attempt repair
        repaired_json = _repair_json(cleaned_json)
        try:
            return json.loads(repaired_json)
        except json.JSONDecodeError as e:
            logger.warning(
                "json_repair_failed",
                error=str(e),
                snippet=cleaned_json[:100]
            )
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
    json_str = re.sub(r'[\x00-\x1F\x7F]', '', json_str)
    
    # Fix missing quotes on keys (looks for keys followed by :)
    # Pattern: finds an alphanumeric word at start of object or after comma/brace, not inside quotes
    json_str = re.sub(r'([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', json_str)
    
    # Remove trailing commas before closing braces/brackets
    json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
    
    # Python-isms (hallucinated by local models trained on Python)
    json_str = re.sub(r'\bTrue\b', 'true', json_str)
    json_str = re.sub(r'\bFalse\b', 'false', json_str)
    json_str = re.sub(r'\bNone\b', 'null', json_str)
    
    return json_str
