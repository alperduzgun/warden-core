"""
Project Purpose Detector Service.

Synthesizes project purpose and high-level architecture using LLM
from directory structure, dependencies, and code samples.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from warden.analysis.domain.intelligence import (
    FileException,
    ModuleInfo,
    RiskLevel,
    SecurityPosture,
)
from warden.llm.config import LlmConfiguration
from warden.llm.factory import create_client
from warden.llm.types import LlmRequest

logger = structlog.get_logger()

# Keywords that indicate critical security areas
CRITICAL_KEYWORDS = {
    "P0": [
        "crypto",
        "encrypt",
        "decrypt",
        "secret",
        "credential",
        "password",
        "token",
        "jwt",
        "oauth",
        "payment",
        "billing",
        "charge",
        "stripe",
        "paypal",
        "bank",
    ],
    "P1": [
        "auth",
        "login",
        "session",
        "permission",
        "role",
        "admin",
        "user",
        "account",
        "profile",
        "pii",
        "gdpr",
        "security",
    ],
}


class ProjectPurposeDetector:
    """
    Detects the semantic purpose and architecture of a project.

    Used during Phase 0 (Pre-Analysis) to provide high-level context
    to subsequent analysis frames, reducing token usage by avoiding
    redundant project-wide explanations.
    """

    def __init__(self, project_root: Path, llm_config: LlmConfiguration | None = None, llm_service: Any | None = None):
        """
        Initialize the detector.

        Args:
            project_root: Root directory of the project.
            llm_config: Optional LLM configuration.
            llm_service: Optional shared LLM service.
        """
        self.project_root = Path(project_root).resolve()

        if not self.project_root.exists():
            logger.warning("project_root_does_not_exist", path=str(self.project_root))
        self.llm = llm_service

        if not self.llm:
            try:
                # We use the default client if no config is provided
                self.llm = create_client(llm_config) if llm_config else create_client()
            except Exception as e:
                logger.warning("llm_client_creation_failed", error=str(e), fallback="no_llm")
                self.llm = None

    async def detect_async(
        self, file_list: list[Path], config_files: dict[str, str]
    ) -> tuple[str, str, dict[str, ModuleInfo]]:
        """
        Analyze the project and return (purpose, architecture_description, module_map).

        Args:
            file_list: List of all files in the project.
            config_files: Dictionary of detected configuration files.

        Returns:
            Tuple of (purpose, architecture_description, module_map).
        """
        if not self.llm:
            logger.debug("llm_skipped_project_purpose_detection", reason="no_client")
            return "Warden-initialized project", "Default architectural pattern", {}

        if not isinstance(config_files, dict):
            logger.warning("invalid_config_files_type", expected="dict", actual=type(config_files).__name__)
            config_files = {}

        logger.info("project_purpose_discovery_started", root=str(self.project_root))

        # 1. Prepare discovery canvas (context for LLM)
        canvas = await self._create_discovery_canvas_async(file_list, config_files)

        # 2. Construct LLM prompt with enhanced module mapping
        prompt = f"""Analyze the following project 'Discovery Canvas' and synthesize its high-level purpose and architecture.

PROJECT CANVAS:
{canvas}

TASK:
1. Identify the 'Project Purpose': What is this software primarily designed to do? (Be concise, 1-2 sentences).
2. Determine 'Security Posture': Based on the project type, what level of security scrutiny is appropriate?
   - paranoid: fintech, healthcare, critical infrastructure
   - strict: e-commerce, SaaS with user data
   - standard: internal tools, general applications
   - relaxed: prototypes, demos, personal projects
3. Summarize 'Architecture': How is the code organized? (e.g. Layered, Hexagonal, MVC, Python Package, Monorepo).
4. Identify 'Key Modules' with RISK LEVELS:
   - P0 (Critical): Handles authentication, payments, encryption, secrets, tokens
   - P1 (High): Handles user data, admin functions, permissions, PII
   - P2 (Medium): Core business logic, APIs, data processing
   - P3 (Low): Utilities, helpers, formatters, test code
   For each module, also identify security focus areas (e.g., injection, auth_bypass, data_leak, validation).
5. Identify 'Critical File Exceptions': Files in low-risk modules that handle sensitive operations (e.g., utils/crypto.py).
6. **Structural Anomalies**: Critically evaluate the structure for logical inconsistencies, redundant configuration files, or anti-patterns.

Return strictly JSON:
{{
  "purpose": "A concise summary of the project's intention.",
  "security_posture": "standard",
  "architecture": "Summary of the structural pattern.",
  "module_map": {{
    "module_name": {{
      "path": "relative/path/",
      "description": "What this module does",
      "risk_level": "P0|P1|P2|P3",
      "security_focus": ["injection", "auth_bypass"]
    }}
  }},
  "critical_files": [
    {{
      "path": "utils/crypto.py",
      "risk_level": "P0",
      "reason": "Handles encryption operations"
    }}
  ],
  "anomalies": [
    {{
      "description": "Description of the anomaly",
      "severity": "high"
    }}
  ]
}}"""

        try:
            request = LlmRequest(
                system_prompt="You are an expert system architect and security analyst. Analyze project structure to provide semantic context, assess security risk levels, and detect structural drift or ambiguity.",
                user_message=prompt,
                max_tokens=1200,  # Increased for enhanced output
                temperature=0.0,
                use_fast_tier=True,  # Use local Qwen for cost optimization
            )

            response = await self.llm.send_async(request)
            data = self._parse_json(response.content)

            purpose = data.get("purpose", "Analyzed software project")
            architecture = data.get("architecture", "Undetermined architecture")
            raw_module_map = data.get("module_map", {})
            critical_files = data.get("critical_files", [])
            anomalies = data.get("anomalies", [])

            # Convert raw module_map to ModuleInfo objects
            module_map = self._build_module_map(raw_module_map, file_list)

            # Apply keyword-based overrides for critical files
            module_map = self._apply_keyword_overrides(module_map, file_list, critical_files)

            if module_map:
                logger.debug("modules_identified", count=len(module_map))
                for name, info in module_map.items():
                    logger.debug(
                        "module_classified", name=name, risk=info.risk_level.value, security_focus=info.security_focus
                    )

            if anomalies:
                # Format anomalies for logging and purpose appending
                anomaly_summaries = []
                for anomaly in anomalies:
                    # Handle both string (legacy/fallback) and dict formats
                    if isinstance(anomaly, str):
                        desc = anomaly
                        sev = "medium"
                    else:
                        desc = anomaly.get("description", "Unknown anomaly")
                        sev = anomaly.get("severity", "medium")

                    logger.warning("structural_anomaly_detected", description=desc, severity=sev)
                    anomaly_summaries.append(f"[{sev.upper()}] {desc}")

                # Append anomalies to purpose description to ensure visibility in reports
                if anomaly_summaries:
                    purpose += f" [ANOMALIES: {'; '.join(anomaly_summaries)}]"

            logger.info("project_purpose_discovered", purpose=purpose[:60] + "...", modules=len(module_map))
            return purpose, architecture, module_map

        except Exception as e:
            logger.error("project_purpose_discovery_failed", error=str(e))
            return "Discovery failed", "Manual architectural analysis required", {}

    async def _create_discovery_canvas_async(self, file_list: list[Path], config_files: dict[str, str]) -> str:
        """Collect project metadata for the LLM discovery prompt."""
        # 1. Directory Structure (trimmed for token safety)
        dirs = sorted({str(f.parent.relative_to(self.project_root)) for f in file_list[:500]})
        dir_tree = "\n".join(f"- {d}" for d in dirs[:40])

        # 2. Dependency Summary
        deps = "\n".join(f"- {f}: {t}" for f, t in list(config_files.items())[:15])

        # 3. Entry point content sampling
        samples = ""
        # Common entry points across languages
        entry_patterns = [
            "main.py",
            "app.py",
            "index.ts",
            "setup.py",
            "pyproject.toml",
            "manage.py",
            "index.js",
            "main.go",
            "Cargo.toml",
        ]

        found_entries = []
        for pattern in entry_patterns:
            for f in file_list:
                if f.name == pattern:
                    found_entries.append(f)
                    break

        # Take first 3 found entries for sampling
        for f in found_entries[:3]:
            try:
                # Read the beginning of the file to understand its role
                # Increased limit to 3000 chars to avoid false "incomplete file" anomalies
                full_content = f.read_text(encoding="utf-8", errors="ignore")
                content = full_content[:3000]
                if len(full_content) > 3000:
                    content += "\n...[TRUNCATED]"

                samples += f"\nFILE: {f.name}\n```\n{content}\n```\n"
            except Exception as e:
                logger.debug("sample_read_failed", file=str(f), error=str(e))

        return f"""PROJECT NAME: {self.project_root.name}

DIRECTORY TREE (Sample):
{dir_tree}

CONFIGURATION & DEPENDENCIES:
{deps}

CODE SAMPLES (Entry Points/Configs):
{samples}"""

    def _parse_json(self, content: str) -> dict[str, Any]:
        """Extract and parse JSON from LLM response content."""
        try:
            # Try finding JSON block
            start = content.find("{")
            end = content.rfind("}") + 1
            if start != -1 and end > start:
                return json.loads(content[start:end])
        except Exception as e:
            logger.debug("json_parse_failed", error=str(e), content=content[:100])
        return {}

    def _build_module_map(self, raw_module_map: dict[str, Any], file_list: list[Path]) -> dict[str, ModuleInfo]:
        """
        Convert raw LLM module map to ModuleInfo objects.

        Args:
            raw_module_map: Dictionary from LLM response.
            file_list: List of all project files.

        Returns:
            Dictionary mapping module names to ModuleInfo objects.
        """
        module_map: dict[str, ModuleInfo] = {}

        for name, data in raw_module_map.items():
            if not isinstance(data, dict):
                continue

            # Parse risk level with fallback
            risk_str = data.get("risk_level", "P2")
            try:
                risk_level = RiskLevel(risk_str)
            except ValueError:
                risk_level = RiskLevel.P2_MEDIUM

            # Count files in this module's path
            module_path = data.get("path", "")
            file_count = 0
            if module_path:
                normalized_path = module_path.rstrip("/")
                for f in file_list:
                    try:
                        rel_path = str(f.relative_to(self.project_root))
                        if rel_path.startswith(normalized_path):
                            file_count += 1
                    except ValueError:
                        continue

            module_info = ModuleInfo(
                name=name,
                path=module_path,
                description=data.get("description", ""),
                risk_level=risk_level,
                security_focus=data.get("security_focus", []),
                file_count=file_count,
                verified=False,
            )
            module_map[name] = module_info

        return module_map

    def _apply_keyword_overrides(
        self, module_map: dict[str, ModuleInfo], file_list: list[Path], critical_files: list[dict[str, Any]]
    ) -> dict[str, ModuleInfo]:
        """
        Apply keyword-based risk overrides for files that contain critical patterns.

        This ensures files like utils/crypto.py are marked P0 even if in a P3 module.

        Args:
            module_map: Existing module map from LLM.
            file_list: List of all project files.
            critical_files: List of critical file exceptions from LLM.

        Returns:
            Updated module map with keyword overrides applied.
        """
        # First, process LLM-identified critical files as FileExceptions
        # These are logged but not added to module_map (they're file-level, not module-level)
        for cf in critical_files:
            if isinstance(cf, dict):
                path = cf.get("path", "")
                risk = cf.get("risk_level", "P0")
                reason = cf.get("reason", "")
                logger.debug("critical_file_identified", path=path, risk=risk, reason=reason)

        # Apply keyword-based scanning for files not covered by modules
        for f in file_list:
            try:
                rel_path = str(f.relative_to(self.project_root)).lower()
                filename = f.name.lower()

                # Check P0 keywords in filename or path
                for keyword in CRITICAL_KEYWORDS["P0"]:
                    if keyword in filename or keyword in rel_path:
                        # Find containing module and escalate if needed
                        for mod_name, mod_info in module_map.items():
                            mod_path = mod_info.path.rstrip("/").lower()
                            if rel_path.startswith(mod_path):
                                if mod_info.risk_level.value > "P0":
                                    logger.debug(
                                        "keyword_risk_escalation",
                                        file=rel_path,
                                        keyword=keyword,
                                        module=mod_name,
                                        from_risk=mod_info.risk_level.value,
                                        to_risk="P0",
                                    )
                                break
                        break

                # Check P1 keywords
                for keyword in CRITICAL_KEYWORDS["P1"]:
                    if keyword in filename or keyword in rel_path:
                        for mod_name, mod_info in module_map.items():
                            mod_path = mod_info.path.rstrip("/").lower()
                            if rel_path.startswith(mod_path):
                                if mod_info.risk_level.value > "P1":
                                    logger.debug(
                                        "keyword_risk_escalation",
                                        file=rel_path,
                                        keyword=keyword,
                                        module=mod_name,
                                        from_risk=mod_info.risk_level.value,
                                        to_risk="P1",
                                    )
                                break
                        break

            except ValueError:
                continue

        return module_map
