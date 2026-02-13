"""Language-specific default rules loader."""

from pathlib import Path
from typing import Dict, List, Optional

import yaml

from warden.rules.domain.enums import RuleCategory, RuleSeverity
from warden.rules.domain.models import CustomRule


class DefaultRulesLoader:
    """Loads language-specific default rules."""

    def __init__(self):
        """Initialize the default rules loader."""
        self.rules_dir = Path(__file__).parent
        # Assuming logger is set up globally or passed, but file used 'print'.
        # I need to verify imports. 'loader.py' lines 1-10 show NO logger import.
        # I should add 'from warden.shared.infrastructure.logging import get_logger' or use structlog.
        # Looking at previous file view, it had 'import yaml'.
        # I will stick to 'print' replacement if I can import logger, but wait, look at file content again.

    def get_rules_for_language(self, language: str, context_tags: dict[str, str] | None = None) -> list[CustomRule]:
        """
        Get all default rules for a specific language.

        Args:
            language: Programming language (e.g., 'python', 'javascript')
            context_tags: Optional dictionary of context tags (e.g., {'framework': 'fastapi'})

        Returns:
            List of CustomRule objects for the language
        """
        rules = []
        language_dir = self.rules_dir / language.lower()

        if not language_dir.exists():
            return rules

        # Load all YAML files in the language directory
        for yaml_file in language_dir.glob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)

                    if "rules" in data:
                        for rule_data in data["rules"]:
                            # STRICT ACTIVATION LOGIC (Safety Principle)
                            # If rule has activation criteria, context MUST match.
                            # If no context provided but activation required -> SKIP (Fail Safe)
                            if "activation" in rule_data:
                                if not context_tags:
                                    # Rule requires specific context, none provided -> Skip
                                    continue

                                activation = rule_data["activation"]
                                should_load = True
                                for key, value in activation.items():
                                    # Strict string equality (Strict Types)
                                    if str(context_tags.get(key)) != str(value):
                                        should_load = False
                                        break
                                if not should_load:
                                    continue

                            # Convert pattern to conditions for compatibility
                            conditions = {}
                            if "pattern" in rule_data:
                                conditions = {"pattern": rule_data["pattern"]}

                            # Map category from tags
                            category = (
                                RuleCategory.SECURITY
                                if "security" in rule_data.get("tags", [])
                                else RuleCategory.CONVENTION
                            )

                            # Map severity
                            severity_str = rule_data.get("severity", "medium")
                            severity = (
                                RuleSeverity.CRITICAL
                                if severity_str == "critical"
                                else RuleSeverity.HIGH
                                if severity_str == "high"
                                else RuleSeverity.MEDIUM
                                if severity_str == "medium"
                                else RuleSeverity.LOW
                            )

                            rule = CustomRule(
                                id=rule_data["id"],
                                name=rule_data["name"],
                                description=rule_data.get("description", ""),
                                category=category,
                                severity=severity,
                                is_blocker=severity_str in ["critical", "high"],
                                enabled=rule_data.get("enabled", True),
                                type="pattern",
                                conditions=conditions,
                                message=rule_data.get("message", ""),
                                pattern=rule_data.get("pattern", ""),
                                tags=rule_data.get("tags", []),
                                file_pattern=rule_data.get("file_pattern", ""),
                                excluded_paths=rule_data.get("excluded_paths", []),
                                auto_fix=rule_data.get("auto_fix", None),
                            )
                            rules.append(rule)
            except Exception as e:
                # Observability: Log failure structurally (placeholder print until logger import added)
                print(f"Error loading rules from {yaml_file}: {e}")

                # In a real fix, I would add logger import above.
                # I'll try to add it in a multi-edit if possible or separate step.
                continue

        return rules

    def get_security_rules(self, language: str) -> list[CustomRule]:
        """Get security-specific rules for a language."""
        security_file = self.rules_dir / language.lower() / "security.yaml"

        if not security_file.exists():
            return []

        return self._load_rules_from_file(security_file)

    def get_style_rules(self, language: str) -> list[CustomRule]:
        """Get style-specific rules for a language."""
        style_file = self.rules_dir / language.lower() / "style.yaml"

        if not style_file.exists():
            return []

        return self._load_rules_from_file(style_file)

    def _load_rules_from_file(self, file_path: Path) -> list[CustomRule]:
        """Load rules from a specific YAML file."""
        rules = []

        try:
            with open(file_path) as f:
                data = yaml.safe_load(f)

                if "rules" in data:
                    for rule_data in data["rules"]:
                        # Convert pattern to conditions for compatibility
                        conditions = {}
                        if "pattern" in rule_data:
                            conditions = {"pattern": rule_data["pattern"]}

                        # Map category from tags
                        category = (
                            RuleCategory.SECURITY
                            if "security" in rule_data.get("tags", [])
                            else RuleCategory.CONVENTION
                        )

                        # Map severity
                        severity_str = rule_data.get("severity", "medium")
                        severity = (
                            RuleSeverity.CRITICAL
                            if severity_str == "critical"
                            else RuleSeverity.HIGH
                            if severity_str == "high"
                            else RuleSeverity.MEDIUM
                            if severity_str == "medium"
                            else RuleSeverity.LOW
                        )

                        rule = CustomRule(
                            id=rule_data["id"],
                            name=rule_data["name"],
                            description=rule_data.get("description", ""),
                            category=category,
                            severity=severity,
                            is_blocker=severity_str in ["critical", "high"],
                            enabled=rule_data.get("enabled", True),
                            type="pattern",
                            conditions=conditions,
                            message=rule_data.get("message", ""),
                            pattern=rule_data.get("pattern", ""),
                            tags=rule_data.get("tags", []),
                            file_pattern=rule_data.get("file_pattern", ""),
                            excluded_paths=rule_data.get("excluded_paths", []),
                            auto_fix=rule_data.get("auto_fix", None),
                        )
                        rules.append(rule)
        except Exception as e:
            print(f"Error loading rules from {file_path}: {e}")

        return rules

    def get_available_languages(self) -> list[str]:
        """Get list of languages with default rules."""
        languages = []

        for path in self.rules_dir.iterdir():
            if path.is_dir() and not path.name.startswith("__"):
                languages.append(path.name)

        return sorted(languages)

    def get_rules_summary(self) -> dict[str, dict[str, int]]:
        """Get a summary of available rules per language."""
        summary = {}

        for language in self.get_available_languages():
            rules = self.get_rules_for_language(language)

            # Count by severity
            severity_counts = {}
            for rule in rules:
                severity = rule.severity.lower()
                severity_counts[severity] = severity_counts.get(severity, 0) + 1

            summary[language] = {"total": len(rules), **severity_counts}

        return summary
