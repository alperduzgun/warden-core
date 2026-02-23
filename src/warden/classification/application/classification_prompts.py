"""
Prompt templates and formatting logic for LLM-based classification.
"""

import json
from typing import Any

from warden.analysis.domain.project_context import Framework, ProjectType


def get_classification_system_prompt(available_frames: list[Any] | None = None) -> str:
    """Get classification system prompt with Strategic Selection Principles."""
    if available_frames:
        frames_descriptions = "\n".join([f"- {f.frame_id}: {f.description}" for f in available_frames])
    else:
        frames_descriptions = """- SecurityFrame: Critical vulnerability detection (SQLi, XSS, Secrets). Uses LSP data flow for taint tracking.
- ResilienceFrame: Chaos engineering - simulate failures, find missing resilience patterns (timeout, retry, circuit breaker).
- OrphanFrame: Dead code detection (Unused functions/classes).
- ArchitecturalFrame: Design pattern and coupling analysis.
- StressFrame: Performance/Load testing for critical paths.
- PropertyFrame: Invariant and API contract validation.
- FuzzFrame: Boundary testing for parsers and validators.
  HIGH VALUE for: protocol parsers, file format handlers, input validators, codecs, deserializers, binary readers.
  SKIP for: simple CRUD, config loaders, standard REST endpoints. Only use if code handles untrusted structured input.
- DemoSecurityFrame: [DEMO ONLY] Example security rules for training."""

    return f"""You are the Lead Software Architect and Technical Advisor for this project.
Your goal is to design a high-value, low-noise validation strategy tailored to the project's specific context.

### PRINCIPLES OF STRATEGIC SELECTION:
1. **Contextual Relevance**: Select frames that target risks INHERENT to the technology stack.
   - *Example*: Skip memory-safety checks for garbage-collected languages (Python/JS) unless navigating FFI.
   - *Example*: Skip 'Chaos' validation for simple CLI scripts; reserve it for distributed/networked services.

2. **Noise Intolerance (Precision > Recall)**:
   - Identify frames that rely on mechanisms mismatching the language runtime (e.g., static array bounds checks in Python).
   - **FuzzFrame Selection**: Enable for parser/validator code (JSON, XML, binary, protocol handlers, input validators). Skip for standard business logic.
   - **SUPPRESS** 'DemoSecurityFrame' for production code (training only).
   - If a frame is known to be noisy, only select it if the ROI (Return on Investment) is high.

3. **Dependency-Awareness**:
   - Trigger specialized frames based on libraries found in 'STATS'.
   - *Example*: Detect `sqlalchemy` -> Enable SQL-focused Security rules.
   - *Example*: Detect `react` -> Enable Frontend Performance rules.
   - *Example*: Detect `struct`, `protobuf`, `msgpack`, `xml.etree` -> Enable FuzzFrame for parser validation.

### TASK:
1. Analyze the `TYPE`, `FRAMEWORK`, `STATS` (dependencies), and `HISTORY`.
2. Select the optimal set of Validation Frames.
3. Define suppression rules for noise reduction (especially for tests/examples).
4. Provide architectural reasoning for your choices.

### AVAILABLE FRAMES:
{frames_descriptions}

Return a JSON object:
{{
  "selected_frames": ["frame_id_1", "frame_id_2"],
  "suppression_rules": [{{"pattern": "tests/*", "reason": "Redundant checks", "suppress": ["security"]}}],
  "priorities": {{ "security": "CRITICAL", "chaos": "HIGH" }},
  "advisories": ["Note: Fuzzing disabled due to Python runtime context", "Warn: High complexity in auth module detected"],
  "reasoning": "Selected SecurityFrame due to sensitive dependencies (SQLAlchemy). Rejected FuzzFrame due to high noise risk in Python runtime. Enabled ResilienceFrame for API resilience."
}}
"""


def format_classification_user_prompt(context: dict[str, Any]) -> str:
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
- Skip 'architecture' for small scripts.
- Prioritize frames with historical issues.

Return JSON only.
"""
    return prompt
