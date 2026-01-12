"""
Prompt templates and formatting logic for LLM-based classification.
"""

import json
from typing import Any, Dict, List, Optional
from warden.analysis.domain.project_context import Framework, ProjectType

def get_classification_system_prompt(available_frames: Optional[List[Any]] = None) -> str:
    """Get classification system prompt."""
    if available_frames:
        frames_descriptions = "\n".join([
            f"- {f.frame_id}: {f.description}" 
            for f in available_frames
        ])
    else:
        frames_descriptions = """- SecurityFrame: SQL injection, XSS, hardcoded secrets
- ChaosFrame: Error handling, timeouts, resilience
- OrphanFrame: Unused code detection
- ArchitecturalFrame: Design pattern compliance
- StressFrame: Performance and load testing
- PropertyFrame: Invariant and contract validation
- FuzzFrame: Input validation and edge cases"""

    return f"""You are a senior Software Architect and Security Engineer. Determine the optimal validation strategy for the project.

Task:
1. Select validation frames for the codebase.
2. Identify focal areas for suppression (test/example code).
3. Prioritize frames by risk.

Available Frames:
{frames_descriptions}

Return a JSON object:
{{
  "selected_frames": ["frame_id_1", "frame_id_2"],
  "suppression_rules": [{{"pattern": "*.test.py", "reason": "test_code", "suppress": ["security"]}}],
  "priorities": {{"security": "CRITICAL", "chaos": "HIGH"}},
  "reasoning": "Brief explanation"
}}

Guidelines:
- Skip security for test files.
- Prioritize frames that found issues before.
- Use only valid frame IDs from the list provided.
"""

def format_classification_user_prompt(context: Dict[str, Any]) -> str:
    """Format user prompt for classification."""
    project_type = context.get("project_type", ProjectType.APPLICATION.value)
    framework = context.get("framework", Framework.NONE.value)
    file_contexts = context.get("file_contexts", {})
    previous_issues = context.get("previous_issues", [])
    file_path = context.get("file_path", "")

    # Analyze file context distribution
    context_counts = {}
    for fc in file_contexts.values():
        context_type = fc.get("context", "UNKNOWN")
        context_counts[context_type] = context_counts.get(context_type, 0) + 1

    prompt = f"""Select validation frames for:
TYPE: {project_type}
FRAMEWORK: {framework}
FILE: {file_path}

STATS:
{json.dumps(context_counts, indent=2)}

HISTORY:
{json.dumps(previous_issues[:10], indent=2) if previous_issues else "None"}

Requirements:
- Run 'security' on production code.
- Skip 'architectural' for small scripts.
- Prioritize frames with historical issues.

Return JSON only.
"""
    return prompt
