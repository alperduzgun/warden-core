"""
Bridge Utilities - Serialization and Metadata helpers.
"""

from pathlib import Path
from typing import Any, Dict

def detect_language(path: Path) -> str:
    """Detect programming language from file extension."""
    try:
        from warden.shared.utils.language_utils import get_language_from_path
        return get_language_from_path(path).value
    except Exception:
        # Fallback for unknown extensions
        return "unknown"

def serialize_pipeline_result(result: Any) -> Dict[str, Any]:
    """Serialize pipeline result to JSON-RPC compatible dict."""
    try:
        if hasattr(result, "to_json"):
            # If to_json returns a string (serialized JSON), parse it back?
            # Or assume it returns a dict if the signature says so.
            # Assuming to_json returns a dict or serialized string.
            val = result.to_json()
            if isinstance(val, dict):
                return val
            # If it's a JSON string, we can't easily return it here if typed as Dict/Any 
            # without parsing, but usually in Python we pass dicts via IPC bridge.
            return {"data": val} # Wrapper if not dict
            
        if hasattr(result, "model_dump"):
            data = result.model_dump(mode="json")

            # Aggregate findings from frame_results for scan.py compatibility
            # scan.py expects findings in the top-level result
            # Note: frame_results may contain FrameResult objects that need to_json() conversion
            all_findings = []

            # First try from result.frame_results (might be objects)
            if hasattr(result, 'frame_results') and result.frame_results:
                import sys
                print(f"DEBUG: Processing {len(result.frame_results)} frame_results", file=sys.stderr)
                for frame_res in result.frame_results:
                    # If FrameResult object, access findings attribute directly
                    if hasattr(frame_res, 'findings') and frame_res.findings:
                        print(f"DEBUG: Frame {getattr(frame_res, 'frame_id', 'unknown')} has {len(frame_res.findings)} findings", file=sys.stderr)
                        # findings is a list of Finding objects
                        for finding in frame_res.findings:
                            # Convert Finding to dict
                            if hasattr(finding, 'to_dict'):
                                all_findings.append(finding.to_dict())
                            elif hasattr(finding, 'to_json'):
                                all_findings.append(finding.to_json())
                            elif isinstance(finding, dict):
                                all_findings.append(finding)
                print(f"DEBUG: Total findings aggregated: {len(all_findings)}", file=sys.stderr)

            # Fallback: try from serialized data
            elif 'frame_results' in data and isinstance(data['frame_results'], list):
                for frame_res in data['frame_results']:
                    if isinstance(frame_res, dict) and 'findings' in frame_res:
                        all_findings.extend(frame_res['findings'])

            data['findings'] = all_findings

            return data

        # Fallback manual serialization
        return {
            "pipeline_id": getattr(result, "pipeline_id", "unknown"),
            "status": getattr(result, "status", "unknown").value if hasattr(getattr(result, "status", None), 'value') else str(getattr(result, "status", "unknown")),
            "duration": getattr(result, "duration", 0),
            "total_findings": getattr(result, "total_findings", 0),
            "frame_results": [
                {
                    "frame_id": getattr(fr, "frame_id", "unknown"),
                    "status": getattr(fr.status, "value", str(fr.status)) if hasattr(fr, "status") else "unknown",
                    "findings": [
                        {
                            "severity": getattr(f, "severity", "unknown"),
                            "message": getattr(f, "message", str(f)),
                            "line": getattr(f, "line_number", getattr(f, "line", 0)),
                        } for f in getattr(fr, "findings", [])
                    ]
                } for fr in getattr(result, "frame_results", [])
            ]
        }
    except Exception as e:
        # Failsafe return to prevent bridge crash
        return {
            "error": "serialization_failed",
            "message": str(e),
            "original_type": str(type(result))
        }
