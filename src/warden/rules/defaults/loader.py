"""Language-specific default rules loader."""

from pathlib import Path
from typing import Dict, List, Optional
import yaml

from warden.rules.domain.models import CustomRule
from warden.rules.domain.enums import RuleCategory, RuleSeverity


class DefaultRulesLoader:
    """Loads language-specific default rules."""

    def __init__(self):
        """Initialize the default rules loader."""
        self.rules_dir = Path(__file__).parent

    def get_rules_for_language(self, language: str) -> List[CustomRule]:
        """
        Get all default rules for a specific language.

        Args:
            language: Programming language (e.g., 'python', 'javascript')

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
                with open(yaml_file, 'r') as f:
                    data = yaml.safe_load(f)

                    if 'rules' in data:
                        for rule_data in data['rules']:
                            # Convert pattern to conditions for compatibility
                            conditions = {}
                            if 'pattern' in rule_data:
                                conditions = {'pattern': rule_data['pattern']}

                            # Map category from tags
                            category = RuleCategory.SECURITY if 'security' in rule_data.get('tags', []) else RuleCategory.CONVENTION

                            # Map severity
                            severity_str = rule_data.get('severity', 'medium')
                            severity = RuleSeverity.CRITICAL if severity_str == 'critical' else \
                                      RuleSeverity.HIGH if severity_str == 'high' else \
                                      RuleSeverity.MEDIUM if severity_str == 'medium' else \
                                      RuleSeverity.LOW

                            rule = CustomRule(
                                id=rule_data['id'],
                                name=rule_data['name'],
                                description=rule_data.get('description', ''),
                                category=category,
                                severity=severity,
                                is_blocker=severity_str in ['critical', 'high'],
                                enabled=rule_data.get('enabled', True),
                                type='pattern',
                                conditions=conditions,
                                message=rule_data.get('message', ''),
                                pattern=rule_data.get('pattern', ''),
                                tags=rule_data.get('tags', []),
                                file_pattern=rule_data.get('file_pattern', ''),
                                excluded_paths=rule_data.get('excluded_paths', []),
                                auto_fix=rule_data.get('auto_fix', None),
                            )
                            rules.append(rule)
            except Exception as e:
                # Log error but continue loading other files
                print(f"Error loading rules from {yaml_file}: {e}")
                continue

        return rules

    def get_security_rules(self, language: str) -> List[CustomRule]:
        """Get security-specific rules for a language."""
        security_file = self.rules_dir / language.lower() / "security.yaml"

        if not security_file.exists():
            return []

        return self._load_rules_from_file(security_file)

    def get_style_rules(self, language: str) -> List[CustomRule]:
        """Get style-specific rules for a language."""
        style_file = self.rules_dir / language.lower() / "style.yaml"

        if not style_file.exists():
            return []

        return self._load_rules_from_file(style_file)

    def _load_rules_from_file(self, file_path: Path) -> List[CustomRule]:
        """Load rules from a specific YAML file."""
        rules = []

        try:
            with open(file_path, 'r') as f:
                data = yaml.safe_load(f)

                if 'rules' in data:
                    for rule_data in data['rules']:
                        # Convert pattern to conditions for compatibility
                        conditions = {}
                        if 'pattern' in rule_data:
                            conditions = {'pattern': rule_data['pattern']}

                        # Map category from tags
                        category = RuleCategory.SECURITY if 'security' in rule_data.get('tags', []) else RuleCategory.CONVENTION

                        # Map severity
                        severity_str = rule_data.get('severity', 'medium')
                        severity = RuleSeverity.CRITICAL if severity_str == 'critical' else \
                                  RuleSeverity.HIGH if severity_str == 'high' else \
                                  RuleSeverity.MEDIUM if severity_str == 'medium' else \
                                  RuleSeverity.LOW

                        rule = CustomRule(
                            id=rule_data['id'],
                            name=rule_data['name'],
                            description=rule_data.get('description', ''),
                            category=category,
                            severity=severity,
                            is_blocker=severity_str in ['critical', 'high'],
                            enabled=rule_data.get('enabled', True),
                            type='pattern',
                            conditions=conditions,
                            message=rule_data.get('message', ''),
                            pattern=rule_data.get('pattern', ''),
                            tags=rule_data.get('tags', []),
                            file_pattern=rule_data.get('file_pattern', ''),
                            excluded_paths=rule_data.get('excluded_paths', []),
                            auto_fix=rule_data.get('auto_fix', None),
                        )
                        rules.append(rule)
        except Exception as e:
            print(f"Error loading rules from {file_path}: {e}")

        return rules

    def get_available_languages(self) -> List[str]:
        """Get list of languages with default rules."""
        languages = []

        for path in self.rules_dir.iterdir():
            if path.is_dir() and not path.name.startswith('__'):
                languages.append(path.name)

        return sorted(languages)

    def get_rules_summary(self) -> Dict[str, Dict[str, int]]:
        """Get a summary of available rules per language."""
        summary = {}

        for language in self.get_available_languages():
            rules = self.get_rules_for_language(language)

            # Count by severity
            severity_counts = {}
            for rule in rules:
                severity = rule.severity.lower()
                severity_counts[severity] = severity_counts.get(severity, 0) + 1

            summary[language] = {
                'total': len(rules),
                **severity_counts
            }

        return summary