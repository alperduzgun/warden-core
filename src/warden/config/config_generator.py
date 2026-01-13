"""Configuration generator for Warden initialization."""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional

import structlog

from warden.config.language_templates import (
    LanguageTemplate,
    get_language_template,
    GENERIC_TEMPLATE,
)

logger = structlog.get_logger(__name__)


class ConfigGenerator:
    """Generates .warden/config.yaml from language template."""

    def __init__(self, project_root: Path) -> None:
        """
        Initialize config generator.

        Args:
            project_root: Root directory of the project
        """
        self.project_root = project_root
        self.warden_dir = project_root / ".warden"

    async def generate_config(
        self,
        language: str,
        project_name: str,
        framework: str | None = None,
        sdk_version: str | None = None,
        project_type: str | None = None,
        interactive: bool = True,
    ) -> Dict[str, Any]:
        """
        Generate config.yaml content from language template.

        Args:
            language: Detected programming language
            project_name: Name of the project
            framework: Detected framework (optional)
            sdk_version: SDK/runtime version (optional)
            interactive: Whether to prompt user for customization

        Returns:
            Config dictionary ready for YAML serialization
        """
        logger.info(
            "generating_config",
            language=language,
            project_name=project_name,
            framework=framework,
            sdk_version=sdk_version,
        )

        # Get language template
        template = get_language_template(language)

        if template == GENERIC_TEMPLATE:
            logger.warning(
                "using_generic_template",
                language=language,
                reason="No specific template found",
            )

        # Build base configuration with full project metadata
        config = self._build_base_config(
            template, project_name, language, sdk_version, framework, project_type
        )

        # Add LLM configuration if recommended
        if template.llm_recommended:
            config["llm"] = self._build_llm_config()

        # Apply framework-specific tweaks
        if framework:
            config = self._apply_framework_tweaks(config, framework, language)

        # Add project metadata as comments (will be in YAML)
        config["_metadata"] = {
            "generated_by": "warden init",
            "language": language,
            "framework": framework,
            "sdk_version": sdk_version,
        }

        logger.info(
            "config_generated",
            frames_count=len(config.get("frames", [])),
            has_llm=template.llm_recommended,
        )

        return config

    def _build_base_config(
        self,
        template: LanguageTemplate,
        project_name: str,
        language: str,
        sdk_version: str | None,
        framework: str | None,
        project_type: str | None,
    ) -> Dict[str, Any]:
        """
        Build base configuration from template with full project metadata.

        Args:
            template: Language template
            project_name: Project name
            language: Programming language
            sdk_version: SDK/runtime version
            framework: Framework name
            project_type: Project type

        Returns:
            Base configuration dictionary
        """
        from datetime import datetime

        config = {
            "# Warden Configuration": f"Generated for {template.language} project",
            "project": {
                "name": project_name,
                "description": f"Warden configuration for {project_name}",
                "language": language,
                "sdk_version": sdk_version or "",
                "framework": framework or "",
                "project_type": project_type or "application",
                "detected_at": datetime.now().isoformat(),
            },
            "frames": template.recommended_frames.copy(),
        }

        # Add frame-specific configurations
        if template.default_rules:
            # Separate frames config and other settings
            frames_config = {}
            for frame_name, frame_settings in template.default_rules.items():
                if frame_name in template.recommended_frames:
                    frames_config[frame_name] = frame_settings

            if frames_config:
                config["frames_config"] = frames_config

        return config

    def _build_llm_config(self) -> Dict[str, Any]:
        """
        Build default LLM configuration with Azure OpenAI.

        Returns:
            LLM configuration dictionary
        """
        return {
            "provider": "azure_openai",  # Default to Azure OpenAI
            "model": "gpt-4o",
            "# Azure OpenAI specific settings": "",
            "azure": {
                "endpoint": "${AZURE_OPENAI_ENDPOINT}",
                "api_key": "${AZURE_OPENAI_API_KEY}",
                "deployment_name": "${AZURE_OPENAI_DEPLOYMENT_NAME}",
                "api_version": "${AZURE_OPENAI_API_VERSION}",
            },
            "# Fallback provider": "",
            "fallback": {
                "provider": "groq",
                "api_key": "${GROQ_API_KEY}",
            },
            "timeout": 300,
            "max_retries": 2,
        }

    def _apply_framework_tweaks(
        self, config: Dict[str, Any], framework: str, language: str
    ) -> Dict[str, Any]:
        """
        Apply framework-specific configuration adjustments.

        Args:
            config: Base configuration
            framework: Detected framework
            language: Programming language

        Returns:
            Modified configuration
        """
        logger.debug(
            "applying_framework_tweaks",
            framework=framework,
            language=language,
        )

        # Python frameworks
        if framework == "django":
            # Add Django-specific security checks
            if "frames_config" not in config:
                config["frames_config"] = {}
            if "security" in config["frames_config"]:
                checks = config["frames_config"]["security"].get("checks", [])
                checks.extend(["template_injection", "csrf_bypass"])
                config["frames_config"]["security"]["checks"] = list(set(checks))

        elif framework == "fastapi":
            # Add async validation and stress testing
            if "stress" not in config["frames"]:
                config["frames"].append("stress")
            if "frames_config" not in config:
                config["frames_config"] = {}
            config["frames_config"]["stress"] = {
                "enabled": True,
                "checks": ["api_load_testing", "async_performance"],
            }

        elif framework == "flask":
            # Similar to Django but lighter
            if "frames_config" in config and "security" in config["frames_config"]:
                checks = config["frames_config"]["security"].get("checks", [])
                checks.append("werkzeug_debugger")
                config["frames_config"]["security"]["checks"] = list(set(checks))

        # JavaScript frameworks
        elif framework in ["react", "vue", "angular"]:
            # Frontend-specific checks
            if "frames_config" not in config:
                config["frames_config"] = {}
            if "security" in config["frames_config"]:
                checks = config["frames_config"]["security"].get("checks", [])
                checks.extend(["xss", "dangerously_set_html", "eval_usage"])
                config["frames_config"]["security"]["checks"] = list(set(checks))

        elif framework in ["express", "nest", "koa"]:
            # Node.js backend frameworks
            if "frames_config" not in config:
                config["frames_config"] = {}
            if "security" in config["frames_config"]:
                checks = config["frames_config"]["security"].get("checks", [])
                checks.extend(["nosql_injection", "jwt_validation"])
                config["frames_config"]["security"]["checks"] = list(set(checks))

        # Java frameworks
        elif framework in ["spring", "spring-boot"]:
            # Spring-specific configurations
            if "frames_config" not in config:
                config["frames_config"] = {}
            if "security" in config["frames_config"]:
                checks = config["frames_config"]["security"].get("checks", [])
                checks.extend(["spring_security_config", "bean_validation"])
                config["frames_config"]["security"]["checks"] = list(set(checks))

        return config

    async def save_config(self, config: Dict[str, Any]) -> Path:
        """
        Save configuration to .warden/config.yaml.

        Args:
            config: Configuration dictionary

        Returns:
            Path to saved config file
        """
        # Ensure .warden directory exists
        self.warden_dir.mkdir(parents=True, exist_ok=True)

        # Config file path
        config_path = self.warden_dir / "config.yaml"

        # Remove metadata before saving (it's just for comments)
        save_config = config.copy()
        save_config.pop("_metadata", None)

        # Custom YAML formatting for better readability
        yaml_content = self._format_yaml(save_config)

        # Write config file
        config_path.write_text(yaml_content)

        logger.info("config_saved", path=str(config_path))

        return config_path

    def _format_yaml(self, config: Dict[str, Any]) -> str:
        """
        Format configuration as readable YAML.

        Args:
            config: Configuration dictionary

        Returns:
            Formatted YAML string
        """
        # Use custom formatting for better readability
        lines = []

        # Add header comment
        lines.append("# Warden Configuration File")
        lines.append("# Generated by 'warden init'")
        lines.append("# Customize as needed for your project")
        lines.append("")

        # Project section with all metadata
        if "project" in config:
            lines.append("# Project metadata (from warden init)")
            lines.append("project:")
            for key, value in config["project"].items():
                if value:  # Only include non-empty values
                    lines.append(f'  {key}: "{value}"')
            lines.append("")

        # LLM section with nested structures
        if "llm" in config:
            lines.append("# LLM Configuration (for AI-powered analysis)")
            lines.append("llm:")
            for key, value in config["llm"].items():
                if key.startswith("#"):
                    lines.append(f"  {key}")
                elif isinstance(value, dict):
                    # Handle nested dicts (azure, fallback)
                    lines.append(f"  {key}:")
                    for sub_key, sub_value in value.items():
                        if isinstance(sub_value, str):
                            lines.append(f'    {sub_key}: "{sub_value}"')
                        else:
                            lines.append(f"    {sub_key}: {sub_value}")
                elif isinstance(value, str):
                    lines.append(f'  {key}: "{value}"')
                else:
                    lines.append(f"  {key}: {value}")
            lines.append("")

        # Frames section
        if "frames" in config:
            lines.append("# Validation frames to run")
            lines.append("frames:")
            for frame in config["frames"]:
                lines.append(f"  - {frame}")
            lines.append("")

        # Frame configurations
        if "frames_config" in config:
            lines.append("# Frame-specific configurations")
            # Use standard YAML dump for complex nested structures
            frames_yaml = yaml.dump(
                {"frames_config": config["frames_config"]},
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
            )
            lines.append(frames_yaml.strip())
            lines.append("")

        # CI/CD section (default)
        lines.append("# CI/CD Integration")
        lines.append("ci:")
        lines.append("  enabled: true")
        lines.append("  fail_on_blocker: true")
        lines.append("  output:")
        lines.append('    - format: "markdown"')
        lines.append('      path: "./WARDEN_REPORT.md"')
        lines.append('    - format: "json"')
        lines.append('      path: "./warden-report.json"')
        lines.append("")

        # Advanced options
        lines.append("# Advanced Options")
        lines.append("advanced:")
        lines.append("  max_workers: 4")
        lines.append("  frame_timeout: 300")
        lines.append("  debug: false")

        return "\n".join(lines)