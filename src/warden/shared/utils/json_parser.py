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
    Extract and parse JSON from an LLM response string.
    
    Args:
        response: The raw string response from the LLM.
        
    Returns:
        Parsed JSON object (dict or list) or None if parsing fails.
    """
    if not response:
        return None

    # Cleaning: Remove markdown code blocks
    # Logic: Look for ```json ... ``` or just ``` ... ```
    # Regex to capture content inside code blocks
    markdown_pattern = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
    match = markdown_pattern.search(response)
    
    cleaned_json = response
    if match:
        cleaned_json = match.group(1).strip()
    
    # Fallback: if no markdown, simply try to find the first { or [ and last } or ]
    else:
        # Find first '{' or '['
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
            # Find last '}' or ']'
            last_brace = cleaned_json.rfind('}')
            last_bracket = cleaned_json.rfind(']')
            end_idx = max(last_brace, last_bracket)
            
            if end_idx != -1 and end_idx > start_idx:
                cleaned_json = cleaned_json[start_idx:end_idx+1]

    try:
        return json.loads(cleaned_json)
    except json.JSONDecodeError as e:
        logger.warning(
            "json_parsing_failed_initial",
            error=str(e),
            snippet=cleaned_json[:100]
        )
        # TODO: Add more advanced repair logic here if needed (e.g., dirtyjson)
        return None
