"""Domain models for custom rules system.

This module defines the core domain models for project-specific validation rules.
All models are Panel-compatible with JSON serialization (camelCase).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from warden.rules.domain.enums import RuleCategory, RuleSeverity
from warden.shared.domain.base_model import BaseDomainModel


@dataclass
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
    is_blocker: bool
    description: str
    enabled: bool
    type: str  # 'security' | 'convention' | 'pattern' | 'script'
    conditions: Dict[str, Any]
    examples: Optional[Dict[str, List[str]]] = None
    message: Optional[str] = None
    language: Optional[List[str]] = None
    exceptions: Optional[List[str]] = None
    script_path: Optional[str] = None
    timeout: Optional[int] = None
    # Additional fields for default rules compatibility
    pattern: Optional[str] = None
    tags: Optional[List[str]] = None
    file_pattern: Optional[str] = None
    excluded_paths: Optional[List[str]] = None
    auto_fix: Optional[Dict[str, Any]] = None

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase).

        Returns:
            Dictionary with camelCase keys for Panel consumption
        """
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category.value,
            "severity": self.severity.value,
            "isBlocker": self.is_blocker,
            "description": self.description,
            "enabled": self.enabled,
            "type": self.type,
            "conditions": self.conditions,
            "examples": self.examples,
            "message": self.message,
            "language": self.language,
            "exceptions": self.exceptions,
            "scriptPath": self.script_path,
            "timeout": self.timeout,
            "pattern": self.pattern,
            "tags": self.tags,
            "filePattern": self.file_pattern,
            "excludedPaths": self.excluded_paths,
            "autoFix": self.auto_fix,
        }

    @classmethod
    def from_json(cls, data: dict) -> "CustomRule":
        """Parse Panel JSON (camelCase) to Python model.

        Args:
            data: Dictionary with camelCase keys from Panel

        Returns:
            CustomRule instance
        """
        return cls(
            id=data["id"],
            name=data["name"],
            category=RuleCategory(data["category"]),
            severity=RuleSeverity(data["severity"]),
            is_blocker=data["isBlocker"],
            description=data["description"],
            enabled=data["enabled"],
            type=data["type"],
            conditions=data["conditions"],
            examples=data.get("examples"),
            message=data.get("message"),
            language=data.get("language"),
            exceptions=data.get("exceptions"),
            script_path=data.get("scriptPath"),
            timeout=data.get("timeout"),
            pattern=data.get("pattern"),
            tags=data.get("tags"),
            file_pattern=data.get("filePattern"),
            excluded_paths=data.get("excludedPaths"),
            auto_fix=data.get("autoFix"),
        )


@dataclass
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

    rule_id: str
    rule_name: str
    category: RuleCategory
    severity: RuleSeverity
    is_blocker: bool
    file: str
    line: int
    message: str
    suggestion: Optional[str] = None
    code_snippet: Optional[str] = None

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase).

        Returns:
            Dictionary with camelCase keys for Panel consumption
        """
        return {
            "ruleId": self.rule_id,
            "ruleName": self.rule_name,
            "category": self.category.value,
            "severity": self.severity.value,
            "isBlocker": self.is_blocker,
            "file": self.file,
            "line": self.line,
            "message": self.message,
            "suggestion": self.suggestion,
            "codeSnippet": self.code_snippet,
        }

    @classmethod
    def from_json(cls, data: dict) -> "CustomRuleViolation":
        """Parse Panel JSON (camelCase) to Python model.

        Args:
            data: Dictionary with camelCase keys from Panel

        Returns:
            CustomRuleViolation instance
        """
        return cls(
            rule_id=data["ruleId"],
            rule_name=data["ruleName"],
            category=RuleCategory(data["category"]),
            severity=RuleSeverity(data["severity"]),
            is_blocker=data["isBlocker"],
            file=data["file"],
            line=data["line"],
            message=data["message"],
            suggestion=data.get("suggestion"),
            code_snippet=data.get("codeSnippet"),
        )


@dataclass
class FrameRules(BaseDomainModel):
    """Frame-specific rule configuration.

    Defines which custom rules should run before (PRE) and after (POST)
    a validation frame, and how to handle failures.

    Attributes:
        pre_rules: List of CustomRule objects to run before frame execution
        post_rules: List of CustomRule objects to run after frame execution
        on_fail: Behavior when blocker rule fails ("stop" or "continue")
    """

    pre_rules: List[CustomRule] = field(default_factory=list)
    post_rules: List[CustomRule] = field(default_factory=list)
    on_fail: str = "stop"  # "stop" or "continue"

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase).

        Returns:
            Dictionary with camelCase keys for Panel consumption
        """
        return {
            "preRules": [rule.to_json() for rule in self.pre_rules],
            "postRules": [rule.to_json() for rule in self.post_rules],
            "onFail": self.on_fail,
        }

    @classmethod
    def from_json(cls, data: dict) -> "FrameRules":
        """Parse Panel JSON (camelCase) to Python model.

        Args:
            data: Dictionary with camelCase keys from Panel

        Returns:
            FrameRules instance
        """
        return cls(
            pre_rules=[CustomRule.from_json(r) for r in data.get("preRules", [])],
            post_rules=[CustomRule.from_json(r) for r in data.get("postRules", [])],
            on_fail=data.get("onFail", "stop"),
        )


@dataclass
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

    project_name: str
    language: str
    framework: Optional[str] = None
    rules: List[CustomRule] = field(default_factory=list)
    global_rules: List[str] = field(default_factory=list)  # Rule IDs for global rules
    frame_rules: Dict[str, FrameRules] = field(default_factory=dict)
    ai_validation_enabled: bool = True
    llm_provider: Optional[str] = None
    exclude_paths: List[str] = field(default_factory=list)
    exclude_files: List[str] = field(default_factory=list)

    def to_json(self) -> dict:
        """Convert to Panel-compatible JSON (camelCase).

        Returns:
            Dictionary with camelCase keys for Panel consumption
        """
        return {
            "projectName": self.project_name,
            "language": self.language,
            "framework": self.framework,
            "rules": [rule.to_json() for rule in self.rules],
            "globalRules": self.global_rules,
            "frameRules": {frame_id: rules.to_json() for frame_id, rules in self.frame_rules.items()},
            "aiValidationEnabled": self.ai_validation_enabled,
            "llmProvider": self.llm_provider,
            "excludePaths": self.exclude_paths,
            "excludeFiles": self.exclude_files,
        }

    @classmethod
    def from_json(cls, data: dict) -> "ProjectRuleConfig":
        """Parse Panel JSON (camelCase) to Python model.

        Args:
            data: Dictionary with camelCase keys from Panel

        Returns:
            ProjectRuleConfig instance
        """
        return cls(
            project_name=data["projectName"],
            language=data["language"],
            framework=data.get("framework"),
            rules=[CustomRule.from_json(r) for r in data.get("rules", [])],
            global_rules=data.get("globalRules", []),
            frame_rules={
                frame_id: FrameRules.from_json(rules_data)
                for frame_id, rules_data in data.get("frameRules", {}).items()
            },
            ai_validation_enabled=data.get("aiValidationEnabled", True),
            llm_provider=data.get("llmProvider"),
            exclude_paths=data.get("excludePaths", []),
            exclude_files=data.get("excludeFiles", []),
        )
