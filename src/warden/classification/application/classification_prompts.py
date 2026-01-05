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

    return f"""You are a senior Software Architect and Security Engineer. Analyze the provided project context and determine the optimal validation strategy.

Task:
1. Select which validation frames are most relevant for the codebase.
2. Identify rules for suppressing false positives (e.g., test files, edge cases).
3. Prioritize frames based on risk and impact.

Frame Selection Criteria:
1. Project Type: Match frames to project characteristics
2. Framework: Use framework-specific validation
3. File Context: Skip irrelevant frames for test/example code
4. Previous Issues: Prioritize frames that found issues before
5. Risk Level: Focus on high-risk areas

Available Frames:
{frames_descriptions}

Suppression Guidelines:
- Test files with intentional vulnerabilities
- Example code demonstrating bad practices
- Generated code from trusted sources
- Framework-specific patterns
- Documentation code snippets

Return a JSON object with:
1. selected_frames: List of frame IDs to run
2. suppression_rules: Rules for false positive filtering
3. priorities: Priority order for frames
4. reasoning: Brief explanation of choices"""

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

    prompt = f"""Analyze the project and select appropriate validation frames:

PROJECT TYPE: {project_type}
FRAMEWORK: {framework}
FILE: {file_path}

FILE CONTEXT DISTRIBUTION:
{json.dumps(context_counts, indent=2)}

PREVIOUS ISSUES FOUND:
{json.dumps(previous_issues[:10], indent=2) if previous_issues else "None"}

PROJECT CHARACTERISTICS:
- Total files: {len(file_contexts)}
- Test files: {context_counts.get('TEST', 0)}
- Example files: {context_counts.get('EXAMPLE', 0)}
- Production files: {context_counts.get('PRODUCTION', 0)}

Based on this context:
1. Which validation frames should run?
2. What suppression rules should apply?
3. What priority order for frames?

Consider:
- Don't run SecurityFrame on test files with intentional vulnerabilities
- Skip ArchitecturalFrame for small scripts
- Prioritize frames that found issues previously
- Apply framework-specific suppressions

Return as JSON."""

    return prompt
