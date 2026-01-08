import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Tuple
import yaml
from enum import Enum, auto
from rich.console import Console
from warden.services.package_manager.fetcher import FrameFetcher
from warden.services.package_manager.exceptions import WardenPackageError
from warden.shared.infrastructure.config import settings

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)
console = Console()

class CheckStatus(Enum):
    SUCCESS = auto()
    WARNING = auto()
    ERROR = auto()

class WardenDoctor:
    """
    Diagnostic service to verify project health and environment readiness.
    Distinguishes between Critical Errors (Blockers) and Warnings (Degraded Experience).
    """

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.warden_dir = project_path / ".warden"
        self.config_path = project_path / "warden.yaml"
        self.fetcher = None

    def run_all(self) -> bool:
        """
        Run all diagnostic checks.
        Returns True if the project is usable (Success or Warnings only).
        Returns False if there are Critical Errors.
        """
        has_critical_error = False
        
        checks = [
            ("Python Version", self.check_python_version),
            ("Core Configuration", self.check_config),
            ("Warden Directory", self.check_warden_dir),
            ("Installed Frames", self.check_frames),
            ("Custom Rules", self.check_rules),
            ("Environment & API Keys", self.check_env),
            ("Tooling (LSP/Git)", self.check_tools),
            ("Semantic Index", self.check_vector_db),
        ]

        for name, check_fn in checks:
            console.print(f"\n[bold white]🔍 Checking {name}...[/bold white]")
            status, msg = check_fn()
            
            if status == CheckStatus.SUCCESS:
                console.print(f"  [green]✔[/green] {msg}")
            
            elif status == CheckStatus.WARNING:
                console.print(f"  [yellow]⚠️  {msg} (Degraded Experience)[/yellow]")
            
            elif status == CheckStatus.ERROR:
                console.print(f"  [red]✘ {msg}[/red]")
                has_critical_error = True

        return not has_critical_error

    def check_python_version(self) -> Tuple[CheckStatus, str]:
        """Check if Python version meets minimum requirements."""
        min_version = (3, 9)
        current_version = sys.version_info[:2]
        
        if current_version < min_version:
            return CheckStatus.ERROR, f"Python {current_version[0]}.{current_version[1]} detected. Warden requires Python {min_version[0]}.{min_version[1]}+"
        
        return CheckStatus.SUCCESS, f"Python {current_version[0]}.{current_version[1]} (compatible)"

    def check_config(self) -> Tuple[CheckStatus, str]:
        if not self.config_path.exists():
            return CheckStatus.ERROR, "warden.yaml not found at root. Run 'warden init' to start."
        return CheckStatus.SUCCESS, "warden.yaml found."

    def check_warden_dir(self) -> Tuple[CheckStatus, str]:
        if not self.warden_dir.exists():
            return CheckStatus.ERROR, ".warden directory not found. Project not initialized."
        return CheckStatus.SUCCESS, ".warden directory exists."

    def check_env(self) -> Tuple[CheckStatus, str]:
        # Settings already loads .env in config.py
        missing = []
        
        # Check for at least one LLM/Embedding provider key
        has_key = any([
            settings.openai_api_key,
            settings.azure_openai_api_key,
            settings.deepseek_api_key
        ])
        
        if not has_key:
            missing.append("LLM API Key (OpenAI/Azure/DeepSeek)")
        
        if missing:
            # LLM is not strictly required for basic static analysis, but required for advanced features
            return CheckStatus.WARNING, f"Missing: {', '.join(missing)}. AI features will be disabled."
        return CheckStatus.SUCCESS, "Environment variables loaded and API keys present."

    def check_frames(self) -> Tuple[CheckStatus, str]:
        if not self.config_path.exists():
            return CheckStatus.ERROR, "Cannot check frames without warden.yaml"
            
        with open(self.config_path, "r") as f:
            config = yaml.safe_load(f)
            deps = config.get("dependencies", {})

        missing_frames = []
        drifted_frames = []
        
        for name in deps:
            frame_path = self.warden_dir / "frames" / name
            if not frame_path.exists():
                logger.error("frame_missing", name=name, path=str(frame_path))
                missing_frames.append(name)
            else:
                # Check integrity - Drift is Critical because code execution relies on trust
                # Lazy load fetcher only if needed
                try:
                    if not self.fetcher:
                        self.fetcher = FrameFetcher(self.warden_dir)
                        
                    if not self.fetcher.verify_integrity(name):
                        drifted_frames.append(name)
                except WardenPackageError as e:
                    return CheckStatus.ERROR, f"Package Manager Error: {e}"
                except Exception as e:
                    return CheckStatus.ERROR, f"Unexpected error checking frames: {e}"

        if missing_frames:
            logger.error("frames_missing_check_failed", count=len(missing_frames))
            return CheckStatus.ERROR, f"Missing frames: {', '.join(missing_frames)}. Run 'warden install'."
        if drifted_frames:
            logger.error("frames_drift_detected", count=len(drifted_frames), frames=drifted_frames)
            return CheckStatus.ERROR, f"Drift detected in frames: {', '.join(drifted_frames)}. Run 'warden install -U' to repair."
            
        return CheckStatus.SUCCESS, f"All {len(deps)} dependent frames are installed and verified."

    def check_rules(self) -> Tuple[CheckStatus, str]:
        if not self.config_path.exists():
            return CheckStatus.WARNING, "Skipping rule check (no config)."

        with open(self.config_path, "r") as f:
            config = yaml.safe_load(f) or {}

        # 1. Check Global Custom Rules (root level)
        custom_rules = config.get("custom_rules", [])
        
        # 2. Check Frame-specific Rules (frames_config)
        # Structure: frames_config: { architectural: { rules: [...] } }
        frames_config = config.get("frames_config", {})
        for frame_tools in frames_config.values():
            if isinstance(frame_tools, dict):
                custom_rules.extend(frame_tools.get("rules", []))
                # Also check 'custom_rules' key if used there
                custom_rules.extend(frame_tools.get("custom_rules", []))

        if not custom_rules:
            return CheckStatus.SUCCESS, "No custom rules configured."

        missing_rules = []
        for rule_path_str in custom_rules:
            # Handle relative paths from project root
            rule_path = self.project_path / rule_path_str
            if not rule_path.exists():
                missing_rules.append(rule_path_str)

        if missing_rules:
            return CheckStatus.ERROR, f"Missing rule files: {', '.join(missing_rules)}"

        return CheckStatus.SUCCESS, f"All {len(custom_rules)} configured rules are present."

    def check_tools(self) -> Tuple[CheckStatus, str]:
        git_path = shutil.which("git")
        if not git_path:
            return CheckStatus.ERROR, "git not found. Package manager will not work."
            
        # Check for LSP
        lsp_found = False
        for lsp in ["pyright-langserver", "typescript-language-server", "rust-analyzer"]:
            if shutil.which(lsp):
                lsp_found = True
                break
        
        if not lsp_found:
            return CheckStatus.WARNING, "No common LSP servers found. Precision analysis limited to AST."
            
        return CheckStatus.SUCCESS, "Core tools (git, LSP) are available."

    def check_vector_db(self) -> Tuple[CheckStatus, str]:
        # Simple connectivity check
        # For now, just check if the directory exists and is writable
        index_path = self.warden_dir / "embeddings"
        if not index_path.exists():
            return CheckStatus.WARNING, "Semantic index not found. Run 'warden index' for context-aware analysis."
        return CheckStatus.SUCCESS, "Semantic index found."
