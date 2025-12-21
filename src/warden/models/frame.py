"""
Frame and rule models for Panel compatibility.

These models define validation frames and custom rules:
- Frame: Validation frame definition (security, chaos, fuzz, etc.)
- CustomRule: User-defined security/convention rules
- FrameApplicability: Language/framework applicability

Panel JSON format: camelCase
Python internal format: snake_case
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal

from warden.shared.domain.base_model import BaseDomainModel


# Type aliases for Panel compatibility
FrameCategory = Literal['global', 'language-specific', 'framework-specific']
FramePriority = Literal['critical', 'high', 'medium', 'low']
RuleCategory = Literal['security', 'convention', 'performance', 'custom']
RuleSeverity = Literal['critical', 'high', 'medium', 'low']
RuleType = Literal['security', 'convention']


@dataclass
class FrameApplicability(BaseDomainModel):
    """
    Language/framework applicability for a frame.

    Panel TypeScript equivalent:
    ```typescript
    interface FrameApplicability {
      language?: string
      framework?: string
    }
    ```
    """

    language: Optional[str] = None  # e.g., "python", "typescript", "dart"
    framework: Optional[str] = None  # e.g., "fastapi", "flutter", "react"


@dataclass
class Frame(BaseDomainModel):
    """
    Validation frame definition.

    Panel TypeScript equivalent:
    ```typescript
    export interface Frame {
      id: string
      name: string
      description: string
      category: 'global' | 'language-specific' | 'framework-specific'
      applicability: FrameApplicability[]
      priority: 'critical' | 'high' | 'medium' | 'low'
      isBlocker: boolean
      condition?: string
    }
    ```

    Frame categories:
    - global: All languages (Security, Chaos, Fuzz, Property, Stress)
    - language-specific: Specific languages (Python, TypeScript, Dart)
    - framework-specific: Specific frameworks (FastAPI, Flutter, React)
    """

    id: str
    name: str
    description: str
    category: FrameCategory
    applicability: List[FrameApplicability] = field(default_factory=list)
    priority: FramePriority = 'medium'
    is_blocker: bool = False
    condition: Optional[str] = None  # e.g., "HasAsync", "HasUserInput"

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON (camelCase)."""
        data = super().to_json()
        # Convert applicability
        data['applicability'] = [a.to_json() for a in self.applicability]
        return data

    def applies_to(self, language: Optional[str] = None,
                   framework: Optional[str] = None) -> bool:
        """Check if frame applies to given language/framework."""
        if self.category == 'global':
            return True

        if not self.applicability:
            return False

        for app in self.applicability:
            if language and app.language == language:
                return True
            if framework and app.framework == framework:
                return True

        return False


@dataclass
class SecurityRuleConditions(BaseDomainModel):
    """
    Security rule conditions.

    Panel TypeScript equivalent:
    ```typescript
    interface SecurityRuleConditions {
      checkGit: boolean
      checkSecrets: boolean
      checkConnections: boolean
    }
    ```
    """

    check_git: bool = False
    check_secrets: bool = True
    check_connections: bool = False

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            'checkGit': self.check_git,
            'checkSecrets': self.check_secrets,
            'checkConnections': self.check_connections
        }


@dataclass
class ConventionRuleConditions(BaseDomainModel):
    """
    Convention rule conditions.

    Panel TypeScript equivalent:
    ```typescript
    interface ConventionRuleConditions {
      checkRedis: boolean
      checkApi: boolean
      checkNaming: boolean
    }
    ```
    """

    check_redis: bool = False
    check_api: bool = False
    check_naming: bool = True

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        return {
            'checkRedis': self.check_redis,
            'checkApi': self.check_api,
            'checkNaming': self.check_naming
        }


@dataclass
class RuleExample(BaseDomainModel):
    """
    Rule examples (valid/invalid code).

    Panel TypeScript equivalent:
    ```typescript
    interface RuleExample {
      valid?: string[]
      invalid?: string[]
    }
    ```
    """

    valid: List[str] = field(default_factory=list)
    invalid: List[str] = field(default_factory=list)


@dataclass
class CustomRule(BaseDomainModel):
    """
    Custom validation rule.

    Panel TypeScript equivalent:
    ```typescript
    export interface CustomRule {
      id: string
      name: string
      category: 'security' | 'convention' | 'performance' | 'custom'
      severity: 'critical' | 'high' | 'medium' | 'low'
      isBlocker: boolean
      description: string
      enabled: boolean
      type: 'security' | 'convention'
      conditions: SecurityRuleConditions | ConventionRuleConditions
      examples?: { valid?: string[]; invalid?: string[] }
      language?: string[]
    }
    ```

    Used in PipelineConfig.global_rules and FrameNodeData.pre_rules/post_rules.
    """

    id: str
    name: str
    category: RuleCategory
    severity: RuleSeverity
    is_blocker: bool
    description: str
    enabled: bool = True
    type: RuleType = 'security'
    conditions: Dict[str, Any] = field(default_factory=dict)  # SecurityRuleConditions | ConventionRuleConditions
    examples: Optional[RuleExample] = None
    language: List[str] = field(default_factory=list)

    def to_json(self) -> Dict[str, Any]:
        """Convert to Panel-compatible JSON."""
        data = super().to_json()

        # Convert examples if present
        if self.examples:
            data['examples'] = self.examples.to_json()

        return data

    def applies_to_language(self, language: str) -> bool:
        """Check if rule applies to given language."""
        if not self.language:
            return True  # No language restriction
        return language in self.language


# Predefined global frames
GLOBAL_FRAMES: List[Frame] = [
    Frame(
        id='security',
        name='AI Security Scanner',
        description='Detects SQL injection, XSS, secrets, command injection',
        category='global',
        priority='critical',
        is_blocker=True,
        applicability=[FrameApplicability()]  # All languages
    ),
    Frame(
        id='chaos',
        name='AI Resilience Tester',
        description='Tests network failures, timeouts, error recovery',
        category='global',
        priority='high',
        is_blocker=False,
        condition='HasAsync',
        applicability=[FrameApplicability()]
    ),
    Frame(
        id='fuzz',
        name='AI Fuzz Tester',
        description='Tests malformed inputs, edge cases, type safety',
        category='global',
        priority='medium',
        is_blocker=False,
        condition='HasUserInput',
        applicability=[FrameApplicability()]
    ),
    Frame(
        id='property',
        name='AI Property Validator',
        description='Verifies idempotency, invariants, mathematical properties',
        category='global',
        priority='medium',
        is_blocker=False,
        condition='HasCalculations',
        applicability=[FrameApplicability()]
    ),
    Frame(
        id='stress',
        name='AI Stress Analyzer',
        description='Tests performance, memory leaks, concurrent access',
        category='global',
        priority='low',
        is_blocker=False,
        applicability=[FrameApplicability()]
    ),
    Frame(
        id='architectural',
        name='Architectural Validator',
        description='Validates design patterns, SOLID principles, dependencies',
        category='global',
        priority='medium',
        is_blocker=False,
        applicability=[FrameApplicability()]
    ),
    Frame(
        id='project_architecture',
        name='Project Architecture Validator',
        description='Validates project-level structure, organization, and patterns',
        category='global',
        priority='medium',
        is_blocker=False,
        applicability=[FrameApplicability()]
    ),
    Frame(
        id='gitchanges',
        name='Git Changes Analyzer',
        description='Analyzes only changed lines in git commits for targeted validation',
        category='global',
        priority='medium',
        is_blocker=False,
        applicability=[FrameApplicability()]
    ),
    Frame(
        id='orphan',
        name='Dead Code Detector',
        description='Detects unused functions and classes using LLM-powered analysis',
        category='global',
        priority='low',
        is_blocker=False,
        applicability=[FrameApplicability()]
    ),
]


def get_frame_by_id(frame_id: str) -> Optional[Frame]:
    """Get predefined frame by ID."""
    for frame in GLOBAL_FRAMES:
        if frame.id == frame_id:
            return frame
    return None


def get_applicable_frames(language: Optional[str] = None,
                          framework: Optional[str] = None) -> List[Frame]:
    """Get frames applicable to given language/framework."""
    return [
        frame for frame in GLOBAL_FRAMES
        if frame.applies_to(language, framework)
    ]


def get_priority_value(priority: FramePriority) -> int:
    """
    Get numeric value for priority (lower = higher priority).

    Returns:
        0 = critical (highest)
        1 = high
        2 = medium
        3 = low (lowest)
    """
    priority_map = {
        'critical': 0,
        'high': 1,
        'medium': 2,
        'low': 3
    }
    return priority_map.get(priority, 2)  # Default to medium


def get_frames_by_priority(frames: List[Frame]) -> List[Frame]:
    """
    Sort frames by priority (critical → high → medium → low).

    Args:
        frames: List of frames to sort

    Returns:
        Frames sorted by priority (highest first)
    """
    return sorted(frames, key=lambda f: get_priority_value(f.priority))


def get_frames_grouped_by_priority(frames: List[Frame]) -> Dict[FramePriority, List[Frame]]:
    """
    Group frames by priority for parallel execution.

    Returns dictionary:
    {
        'critical': [security],
        'high': [chaos],
        'medium': [fuzz, property, architectural],
        'low': [stress]
    }

    Args:
        frames: List of frames to group

    Returns:
        Dictionary mapping priority to frames
    """
    groups: Dict[FramePriority, List[Frame]] = {
        'critical': [],
        'high': [],
        'medium': [],
        'low': []
    }

    for frame in frames:
        groups[frame.priority].append(frame)

    return groups


def get_execution_groups(frames: List[Frame]) -> List[List[Frame]]:
    """
    Get execution groups for parallel processing.

    Each group contains frames with same priority.
    Groups are ordered by priority (critical first, low last).

    Example:
        Group 1: [security] (critical)
        Group 2: [chaos] (high)
        Group 3: [fuzz, property, architectural] (medium)
        Group 4: [stress] (low)

    Args:
        frames: List of frames to group

    Returns:
        List of frame groups (outer list is sequential, inner lists can run parallel)
    """
    grouped = get_frames_grouped_by_priority(frames)

    # Build execution groups in priority order
    execution_groups: List[List[Frame]] = []

    for priority in ['critical', 'high', 'medium', 'low']:
        if grouped[priority]:  # type: ignore
            execution_groups.append(grouped[priority])  # type: ignore

    return execution_groups
