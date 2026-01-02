"""Domain models for custom rules system.

This module defines the core domain models for project-specific validation rules.
All models are Panel-compatible with JSON serialization (camelCase).
"""

from typing import Any, Dict, List, Optional

from pydantic import Field
from warden.rules.domain.enums import RuleCategory, RuleSeverity
from warden.shared.domain.base_model import BaseDomainModel


class CustomRule(BaseDomainModel):
    """Custom validation rule definition.

    Represents a project-specific rule that validates code against
    organizational policies, coding conventions, or compliance requirements.

    Attributes:
        id: Unique identifier for the rule
        name: Human-readable rule name
        category: Rule category (security, convention, performance, custom)
        severity: Severity level (critical, high, medium, low)
        is_blocker: If True, violations block deployment
        description: Detailed rule description
        enabled: Whether the rule is active
        type: Rule type ('security' | 'convention' | 'pattern' | 'script')
        conditions: Rule-specific validation conditions
        examples: Optional examples of valid/invalid code
        message: Optional custom violation message
        language: Optional list of applicable languages
        exceptions: Optional list of file patterns to exclude
        script_path: Optional path to validation script (for type='script')
        timeout: Optional timeout in seconds for script execution (default 30)
    """

    id: str
    name: str
    category: RuleCategory
    severity: RuleSeverity
    is_blocker: bool = Field(alias="isBlocker")  # Explicit alias if auto-alias fails for some reason, but auto-alias should work.
    description: str
    enabled: bool
    type: str  # 'security' | 'convention' | 'pattern' | 'script'
    conditions: Dict[str, Any]
    examples: Optional[Dict[str, List[str]]] = None
    message: Optional[str] = None
    language: Optional[List[str]] = None
    exceptions: Optional[List[str]] = None
    script_path: Optional[str] = Field(None, alias="scriptPath")
    timeout: Optional[int] = None
    # Additional fields for default rules compatibility
    pattern: Optional[str] = None
    tags: Optional[List[str]] = None
    file_pattern: Optional[str] = Field(None, alias="filePattern")
    excluded_paths: Optional[List[str]] = Field(None, alias="excludedPaths")
    auto_fix: Optional[Dict[str, Any]] = Field(None, alias="autoFix")


class CustomRuleViolation(BaseDomainModel):
    """Violation of a custom rule.

    Represents a detected violation of a custom rule in code.

    Attributes:
        rule_id: ID of the violated rule
        rule_name: Name of the violated rule
        category: Rule category
        severity: Violation severity
        is_blocker: Whether this violation blocks deployment
        file: File path where violation occurred
        line: Line number of violation
        message: Violation message
        suggestion: Optional suggestion to fix the violation
        code_snippet: Optional code snippet showing the violation
    """

    rule_id: str = Field(alias="ruleId")
    rule_name: str = Field(alias="ruleName")
    category: RuleCategory
    severity: RuleSeverity
    is_blocker: bool = Field(alias="isBlocker")
    file: str
    line: int
    message: str
    suggestion: Optional[str] = None
    code_snippet: Optional[str] = Field(None, alias="codeSnippet")


class FrameRules(BaseDomainModel):
    """Frame-specific rule configuration.

    Defines which custom rules should run before (PRE) and after (POST)
    a validation frame, and how to handle failures.

    Attributes:
        pre_rules: List of CustomRule objects to run before frame execution
        post_rules: List of CustomRule objects to run after frame execution
        on_fail: Behavior when blocker rule fails ("stop" or "continue")
    """

    pre_rules: List[CustomRule] = Field(default_factory=list, alias="preRules")
    post_rules: List[CustomRule] = Field(default_factory=list, alias="postRules")
    on_fail: str = Field("stop", alias="onFail")  # "stop" or "continue"


class ProjectRuleConfig(BaseDomainModel):
    """Project-level rule configuration.

    Configuration for custom rules at the project level.

    Attributes:
        project_name: Name of the project
        language: Primary programming language
        framework: Optional framework being used
        rules: List of custom rules
        global_rules: List of rule IDs that apply to ALL frames (PRE execution)
        frame_rules: Frame-specific rule mappings (frame_id -> FrameRules)
        ai_validation_enabled: Whether AI validation is enabled
        llm_provider: Optional LLM provider for AI validation
        exclude_paths: Optional list of paths to exclude
        exclude_files: Optional list of file patterns to exclude
    """

    project_name: str = Field(alias="projectName")
    language: str
    framework: Optional[str] = None
    rules: List[CustomRule] = Field(default_factory=list)
    global_rules: List[str] = Field(default_factory=list, alias="globalRules")  # Rule IDs for global rules
    frame_rules: Dict[str, FrameRules] = Field(default_factory=dict, alias="frameRules")
    ai_validation_enabled: bool = Field(True, alias="aiValidationEnabled")
    llm_provider: Optional[str] = Field(None, alias="llmProvider")
    exclude_paths: List[str] = Field(default_factory=list, alias="excludePaths")
    exclude_files: List[str] = Field(default_factory=list, alias="excludeFiles")
