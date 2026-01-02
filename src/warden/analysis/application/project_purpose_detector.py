"""
Project Purpose Detector Service.

Synthesizes project purpose and high-level architecture using LLM
from directory structure, dependencies, and code samples.
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import structlog

from warden.llm.factory import create_client
from warden.llm.config import LlmConfiguration
from warden.llm.types import LlmRequest, LlmResponse

logger = structlog.get_logger()


class ProjectPurposeDetector:
    """
    Detects the semantic purpose and architecture of a project.
    
    Used during Phase 0 (Pre-Analysis) to provide high-level context
    to subsequent analysis frames, reducing token usage by avoiding
    redundant project-wide explanations.
    """

    def __init__(self, project_root: Path, llm_config: Optional[LlmConfiguration] = None):
        """
        Initialize the detector.
        
        Args:
            project_root: Root directory of the project.
            llm_config: Optional LLM configuration.
        """
        self.project_root = Path(project_root)
        try:
            # We use the default client if no config is provided
            self.llm = create_client(llm_config) if llm_config else create_client()
        except Exception as e:
            logger.warning("llm_client_creation_failed", error=str(e), fallback="no_llm")
            self.llm = None

    async def detect_async(self, file_list: List[Path], config_files: Dict[str, str]) -> Tuple[str, str]:
        """
        Analyze the project and return (purpose, architecture_description).
        
        Args:
            file_list: List of all files in the project.
            config_files: Dictionary of detected configuration files.
            
        Returns:
            Tuple of (purpose, architecture_description).
        """
        if not self.llm:
            logger.debug("llm_skipped_project_purpose_detection", reason="no_client")
            return "Warden-initialized project", "Default architectural pattern"

        logger.info("project_purpose_discovery_started", root=str(self.project_root))

        # 1. Prepare discovery canvas (context for LLM)
        canvas = await self._create_discovery_canvas(file_list, config_files)
        
        # 2. Construct LLM prompt
        prompt = f"""Analyze the following project 'Discovery Canvas' and synthesize its high-level purpose and architecture.
        
PROJECT CANVAS:
{canvas}

TASK:
1. Identify the 'Project Purpose': What is this software primarily designed to do? (Be concise, 1-2 sentences).
2. Summarize 'Architecture': How is the code organized? (e.g. Layered, Hexagonal, MVC, Python Package, Monorepo).
3. Identify 'Key Modules': Group top-level directories or files into functional areas.

Return strictly JSON:
{{
  "purpose": "A concise summary of the project's intention.",
  "architecture": "Summary of the structural pattern.",
  "module_map": {{ "module_name": "functional description" }}
}}"""

        try:
            request = LlmRequest(
                system_prompt="You are an expert system architect and code analyzer. Analyze project structure to provide semantic context.",
                user_message=prompt,
                max_tokens=800,
                temperature=0.0
            )
            
            response = await self.llm.send_async(request)
            data = self._parse_json(response.content)
            
            purpose = data.get("purpose", "Analyzed software project")
            architecture = data.get("architecture", "Undetermined architecture")
            module_map = data.get("module_map", {})
            
            if module_map:
                logger.debug("modules_identified", count=len(module_map))
            
            logger.info("project_purpose_discovered", purpose=purpose[:60] + "...")
            return purpose, architecture
            
        except Exception as e:
            logger.error("project_purpose_discovery_failed", error=str(e))
            return "Discovery failed", "Manual architectural analysis required"

    async def _create_discovery_canvas(self, file_list: List[Path], config_files: Dict[str, str]) -> str:
        """Collect project metadata for the LLM discovery prompt."""
        # 1. Directory Structure (trimmed for token safety)
        dirs = sorted(list(set(str(f.parent.relative_to(self.project_root)) for f in file_list[:500])))
        dir_tree = "\n".join(f"- {d}" for d in dirs[:40])

        # 2. Dependency Summary
        deps = "\n".join(f"- {f}: {t}" for f, t in list(config_files.items())[:15])

        # 3. Entry point content sampling
        samples = ""
        # Common entry points across languages
        entry_patterns = ["main.py", "app.py", "index.ts", "setup.py", "pyproject.toml", "manage.py", "index.js", "main.go", "Cargo.toml"]
        
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
                content = f.read_text(encoding='utf-8', errors='ignore')[:1500]
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

    def _parse_json(self, content: str) -> Dict[str, Any]:
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
