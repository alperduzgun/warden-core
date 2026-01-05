"""YAML loader for custom rules configuration.

This module loads custom rules from .warden/rules.yaml files.
"""

from pathlib import Path
from typing import Any, Dict

import structlog
import yaml

from warden.rules.domain.enums import RuleCategory, RuleSeverity
from warden.rules.domain.models import CustomRule, FrameRules, ProjectRuleConfig

logger = structlog.get_logger(__name__)


class RulesYAMLLoader:
    """Loads custom rules from YAML configuration files.

    Parses .warden/rules.yaml files and converts them to ProjectRuleConfig models.
    """

    @staticmethod
    async def load_from_file(file_path: Path) -> ProjectRuleConfig:
        """Load rules configuration from YAML file.

        Args:
            file_path: Path to the rules.yaml file

        Returns:
            ProjectRuleConfig with loaded rules

        Raises:
            FileNotFoundError: If file does not exist
            ValueError: If YAML is invalid or malformed
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Rules path not found: {file_path}")

        if file_path.is_dir():
             return await RulesYAMLLoader._load_from_directory(file_path)

        return await RulesYAMLLoader._load_single_file(file_path)

    @staticmethod
    async def _load_single_file(file_path: Path) -> ProjectRuleConfig:
        """Load rules configuration from a single YAML file."""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.error("yaml_parse_error", file_path=str(file_path), error=str(e))
            raise ValueError(f"Invalid YAML in {file_path}: {e}") from e

        return RulesYAMLLoader._parse_yaml_data(data, str(file_path))

    @staticmethod
    async def _load_from_directory(dir_path: Path) -> ProjectRuleConfig:
        """Load rules from all YAML files in a directory and merge them."""
        # Use shared merger logic (DRY)
        from warden.shared.utils.yaml_merger import YAMLMerger
        
        merged_data = YAMLMerger.merge_directory(dir_path)
        
        if not merged_data["rules"] and not merged_data["frame_rules"]:
             logger.warning("no_rules_found_in_directory", directory=str(dir_path))

        logger.info("merged_rules_config", directory=str(dir_path), total_rules=len(merged_data["rules"]))
        return RulesYAMLLoader._parse_yaml_data(merged_data, str(dir_path))

    @staticmethod
    def _parse_yaml_data(data: Dict[str, Any], source: str) -> ProjectRuleConfig:
        """Parse validated YAML dictionary into ProjectRuleConfig."""
        # Validate structure
        # RulesYAMLLoader._validate_yaml_structure(data) # This might be too strict for partial files, skip strict top-level check for merged data?
        # Actually let's assumemerged data is complete enough 

        # Parse project config
        project_data = data.get("project", {})
        rules_data = data.get("rules", [])
        ai_validation = data.get("ai_validation", {})
        exclude_data = data.get("exclude", {})

        # Parse rules
        rules = [RulesYAMLLoader._parse_rule(rule_data) for rule_data in rules_data]

        # Parse global_rules (list of rule IDs)
        global_rules_ids = data.get("global_rules", [])

        # Validate global_rules IDs exist
        rule_ids = {rule.id for rule in rules}
        invalid_global_rules = [rid for rid in global_rules_ids if rid not in rule_ids]
        if invalid_global_rules:
            logger.warning(
                "invalid_global_rules",
                invalid_ids=invalid_global_rules,
                message=f"Global rules reference non-existent rule IDs: {invalid_global_rules}",
            )
            # Filter out invalid IDs
            global_rules_ids = [rid for rid in global_rules_ids if rid in rule_ids]

        # Parse frame_rules (after parsing all rules)
        frame_rules = RulesYAMLLoader._parse_frame_rules(data, rules)

        config = ProjectRuleConfig(
            project_name=project_data.get("name", "unknown"),
            language=project_data.get("language", "unknown"),
            framework=project_data.get("framework"),
            rules=rules,
            global_rules=global_rules_ids,
            frame_rules=frame_rules,
            ai_validation_enabled=ai_validation.get("enabled", True),
            llm_provider=ai_validation.get("llm_provider"),
            exclude_paths=exclude_data.get("paths", []),
            exclude_files=exclude_data.get("files", []),
        )

        logger.info(
            "rules_loaded",
            source=source,
            rule_count=len(rules),
            enabled_count=sum(1 for r in rules if r.enabled),
            global_rules_count=len(global_rules_ids),
            frame_rules_count=len(frame_rules),
        )

        return config

    @staticmethod
    def _validate_yaml_structure(data: Dict[str, Any]) -> None:
        """Validate YAML structure.

        Args:
            data: Parsed YAML data

        Raises:
            ValueError: If structure is invalid
        """
        if not isinstance(data, dict):
            raise ValueError("YAML must be a dictionary")

        if "project" not in data:
            raise ValueError("Missing 'project' section")

        if "rules" not in data:
            raise ValueError("Missing 'rules' section")

        if not isinstance(data["rules"], list):
            raise ValueError("'rules' must be a list")

    @staticmethod
    def _parse_rule(rule_data: Dict[str, Any]) -> CustomRule:
        """Parse a single rule from YAML data.

        Args:
            rule_data: Rule data from YAML

        Returns:
            CustomRule instance

        Raises:
            ValueError: If rule data is invalid
        """
        # Required fields (conditions is optional for script-type rules)
        required_fields = ["id", "name", "category", "severity", "isBlocker", "description", "enabled", "type"]
        for field in required_fields:
            if field not in rule_data:
                raise ValueError(f"Missing required field '{field}' in rule")

        # For non-script rules, conditions is required
        rule_type = rule_data["type"]
        if rule_type != "script" and "conditions" not in rule_data:
            raise ValueError(f"Missing required field 'conditions' in non-script rule")

        # For script rules, either 'script' or 'scriptPath' is required
        if rule_type == "script" and "script" not in rule_data and "scriptPath" not in rule_data:
            raise ValueError(f"Script-type rule requires either 'script' or 'scriptPath' field")

        # Parse enums
        try:
            category = RuleCategory(rule_data["category"])
        except ValueError as e:
            raise ValueError(f"Invalid category '{rule_data['category']}': {e}") from e

        try:
            severity = RuleSeverity(rule_data["severity"])
        except ValueError as e:
            raise ValueError(f"Invalid severity '{rule_data['severity']}': {e}") from e

        # Parse conditions (if present)
        conditions = {}
        if "conditions" in rule_data:
            conditions = RulesYAMLLoader._parse_conditions(rule_data["conditions"])

        # For script rules, store the script content in conditions
        if rule_type == "script" and "script" in rule_data:
            conditions = {"script": rule_data["script"]}

        return CustomRule(
            id=rule_data["id"],
            name=rule_data["name"],
            category=category,
            severity=severity,
            is_blocker=rule_data["isBlocker"],
            description=rule_data["description"],
            enabled=rule_data["enabled"],
            type=rule_data["type"],
            conditions=conditions,
            examples=rule_data.get("examples"),
            message=rule_data.get("message"),
            language=rule_data.get("language"),
            exceptions=rule_data.get("exceptions"),
            script_path=rule_data.get("scriptPath"),
            timeout=rule_data.get("timeout"),
        )

    @staticmethod
    def _parse_conditions(conditions_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse and validate rule conditions from YAML data.

        Args:
            conditions_data: Conditions data from YAML

        Returns:
            Validated conditions dictionary

        Raises:
            ValueError: If conditions structure is invalid
        """
        if not isinstance(conditions_data, dict):
            raise ValueError("Conditions must be a dictionary")

        # Validate security rule conditions
        if "secrets" in conditions_data:
            RulesYAMLLoader._validate_secrets_condition(conditions_data["secrets"])

        if "git" in conditions_data:
            RulesYAMLLoader._validate_git_condition(conditions_data["git"])

        if "connections" in conditions_data:
            RulesYAMLLoader._validate_connections_condition(conditions_data["connections"])

        # Validate convention rule conditions
        if "redis" in conditions_data:
            RulesYAMLLoader._validate_redis_condition(conditions_data["redis"])

        if "api" in conditions_data:
            RulesYAMLLoader._validate_api_condition(conditions_data["api"])

        if "naming" in conditions_data:
            RulesYAMLLoader._validate_naming_condition(conditions_data["naming"])

        return conditions_data

    @staticmethod
    def _validate_secrets_condition(condition: Dict[str, Any]) -> None:
        """Validate secrets condition structure."""
        if "patterns" not in condition:
            raise ValueError("secrets condition requires 'patterns' field")
        if not isinstance(condition["patterns"], list):
            raise ValueError("secrets.patterns must be a list")
        if not condition["patterns"]:
            raise ValueError("secrets.patterns cannot be empty")

    @staticmethod
    def _validate_git_condition(condition: Dict[str, Any]) -> None:
        """Validate git condition structure."""
        valid_fields = {"authorNameBlacklist", "authorEmailBlacklist", "commitMessagePattern"}
        if not any(field in condition for field in valid_fields):
            raise ValueError("git condition requires at least one of: authorNameBlacklist, authorEmailBlacklist, commitMessagePattern")

        if "authorEmailBlacklist" in condition and not isinstance(condition["authorEmailBlacklist"], list):
            raise ValueError("git.authorEmailBlacklist must be a list")

    @staticmethod
    def _validate_connections_condition(condition: Dict[str, Any]) -> None:
        """Validate connections condition structure."""
        if "forbiddenPatterns" in condition and not isinstance(condition["forbiddenPatterns"], list):
            raise ValueError("connections.forbiddenPatterns must be a list")

    @staticmethod
    def _validate_redis_condition(condition: Dict[str, Any]) -> None:
        """Validate redis condition structure."""
        if "keyPattern" not in condition:
            raise ValueError("redis condition requires 'keyPattern' field")
        if not isinstance(condition["keyPattern"], str):
            raise ValueError("redis.keyPattern must be a string (regex pattern)")

    @staticmethod
    def _validate_api_condition(condition: Dict[str, Any]) -> None:
        """Validate api condition structure."""
        if "routePattern" not in condition:
            raise ValueError("api condition requires 'routePattern' field")
        if not isinstance(condition["routePattern"], str):
            raise ValueError("api.routePattern must be a string (regex pattern)")

    @staticmethod
    def _validate_naming_condition(condition: Dict[str, Any]) -> None:
        """Validate naming condition structure."""
        valid_fields = {"asyncMethodSuffix", "interfacePrefix", "privateFieldPrefix"}
        if not any(field in condition for field in valid_fields):
            raise ValueError("naming condition requires at least one of: asyncMethodSuffix, interfacePrefix, privateFieldPrefix")

    @staticmethod
    def _parse_frame_rules(config_data: Dict[str, Any], all_rules: list[CustomRule]) -> Dict[str, FrameRules]:
        """Parse frame_rules section from YAML config.

        Args:
            config_data: Raw YAML config dict
            all_rules: List of all available rules (for ID lookup)

        Returns:
            Dict mapping frame_id -> FrameRules

        Example YAML:
            frame_rules:
                security:
                    pre_rules: ["rule-id-1", "rule-id-2"]
                    post_rules: ["rule-id-3"]
                    on_fail: "stop"
                chaos:
                    pre_rules: ["rule-id-4"]
                    on_fail: "continue"
        """
        frame_rules_data = config_data.get("frame_rules", {})
        if not frame_rules_data:
            logger.debug("no_frame_rules_section", message="No frame_rules section in config")
            return {}

        # Create lookup map: rule_id -> CustomRule object
        rule_lookup = {rule.id: rule for rule in all_rules}

        frame_rules_result: Dict[str, FrameRules] = {}
        missing_rule_ids: list[str] = []

        for frame_id, rules_spec in frame_rules_data.items():
            if not isinstance(rules_spec, dict):
                logger.warning(
                    "invalid_frame_rules_format",
                    frame_id=frame_id,
                    message=f"Frame rules for '{frame_id}' must be a dict, skipping",
                )
                continue

            # Get rule ID lists
            pre_rule_ids = rules_spec.get("pre_rules", [])
            post_rule_ids = rules_spec.get("post_rules", [])
            on_fail = rules_spec.get("on_fail", "stop")

            # Validate on_fail value
            if on_fail not in ("stop", "continue"):
                logger.warning(
                    "invalid_on_fail_value",
                    frame_id=frame_id,
                    on_fail=on_fail,
                    message=f"Invalid on_fail value '{on_fail}' for frame '{frame_id}', defaulting to 'stop'",
                )
                on_fail = "stop"

            # Convert rule IDs to CustomRule objects
            pre_rules = []
            for rule_id in pre_rule_ids:
                if rule_id in rule_lookup:
                    pre_rules.append(rule_lookup[rule_id])
                else:
                    missing_rule_ids.append(f"{frame_id}.pre_rules: {rule_id}")
                    logger.warning(
                        "missing_rule_id",
                        frame_id=frame_id,
                        rule_type="pre_rules",
                        rule_id=rule_id,
                        message=f"Rule ID '{rule_id}' not found in rules list",
                    )

            post_rules = []
            for rule_id in post_rule_ids:
                if rule_id in rule_lookup:
                    post_rules.append(rule_lookup[rule_id])
                else:
                    missing_rule_ids.append(f"{frame_id}.post_rules: {rule_id}")
                    logger.warning(
                        "missing_rule_id",
                        frame_id=frame_id,
                        rule_type="post_rules",
                        rule_id=rule_id,
                        message=f"Rule ID '{rule_id}' not found in rules list",
                    )

            # Create FrameRules instance
            frame_rules_result[frame_id] = FrameRules(
                pre_rules=pre_rules,
                post_rules=post_rules,
                on_fail=on_fail,
            )

        # Log summary
        if missing_rule_ids:
            logger.warning(
                "frame_rules_missing_ids",
                missing_count=len(missing_rule_ids),
                missing_ids=missing_rule_ids,
                message=f"Found {len(missing_rule_ids)} missing rule IDs in frame_rules",
            )

        logger.info(
            "frame_rules_loaded",
            frame_count=len(frame_rules_result),
            frames=list(frame_rules_result.keys()),
            message=f"Loaded frame_rules for {len(frame_rules_result)} frames",
        )

        return frame_rules_result
