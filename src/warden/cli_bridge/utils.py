"""
Bridge Utilities - Serialization and Metadata helpers.
"""

from pathlib import Path
from typing import Any, Dict

def detect_language(path: Path) -> str:
    """Detect programming language from file extension."""
    from warden.shared.utils.language_utils import get_language_from_path
    return get_language_from_path(path).value

def serialize_pipeline_result(result: Any) -> Dict[str, Any]:
    """Serialize pipeline result to JSON-RPC compatible dict."""
    if hasattr(result, "to_json"):
        return result.to_json()
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")

    # Fallback
    return {
        "pipeline_id": getattr(result, "pipeline_id", "unknown"),
        "status": getattr(result, "status", "unknown").value if hasattr(getattr(result, "status", None), 'value') else str(getattr(result, "status", "unknown")),
        "duration": getattr(result, "duration", 0),
        "total_findings": getattr(result, "total_findings", 0),
        "frame_results": [
            {
                "frame_id": fr.frame_id,
                "status": fr.status.value if hasattr(fr.status, 'value') else str(fr.status),
                "findings": [
                    {
                        "severity": getattr(f, "severity", "unknown"),
                        "message": getattr(f, "message", str(f)),
                        "line": getattr(f, "line_number", getattr(f, "line", 0)),
                    } for f in fr.findings
                ]
            } for fr in getattr(result, "frame_results", [])
        ]
    }
