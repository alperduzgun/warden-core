import shutil
import sys
from enum import Enum, auto
from pathlib import Path
from typing import Tuple

import yaml
from rich.console import Console

from warden.services.package_manager.exceptions import WardenPackageError
from warden.services.package_manager.fetcher import FrameFetcher
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

        # Check standard location first, then legacy
        standard_config = project_path / "warden.yaml"
        legacy_config = self.warden_dir / "config.yaml"

        self.config_path = standard_config if standard_config.exists() else legacy_config
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

    def check_python_version(self) -> tuple[CheckStatus, str]:
        """Check if Python version meets minimum requirements."""
        min_version = (3, 9)
        current_version = sys.version_info[:2]

        if current_version < min_version:
            return (
                CheckStatus.ERROR,
                f"Python {current_version[0]}.{current_version[1]} detected. Warden requires Python {min_version[0]}.{min_version[1]}+",
            )

        return CheckStatus.SUCCESS, f"Python {current_version[0]}.{current_version[1]} (compatible)"

    def check_config(self) -> tuple[CheckStatus, str]:
        """
        Validates that warden.yaml exists, is parseable YAML, and conforms
        to the expected structure. Checks for required keys, unknown keys,
        and correct value types for known top-level keys.
        """
        KNOWN_TOP_LEVEL_KEYS = {
            "project",
            "frames",
            "dependencies",
            "llm",
            "frames_config",
            "custom_rules",
            "ci",
            "advanced",
            "spec",
            "analysis",
            "suppression",
            "fortification",
            "cleaning",
            "pipeline",
        }

        EXPECTED_TYPES = {
            "project": dict,
            "frames": list,
            "dependencies": dict,
        }

        if not self.config_path.exists():
            return CheckStatus.ERROR, "warden.yaml not found at root. Run 'warden init' to start."

        try:
            with open(self.config_path) as f:
                data = yaml.safe_load(f)

            if data is None:
                return CheckStatus.ERROR, "warden.yaml is empty."

            if not isinstance(data, dict):
                return CheckStatus.ERROR, "warden.yaml must contain a YAML mapping (dictionary)."

            # Collect warnings — return the first one found at the end
            warnings: list[str] = []

            # 1. Basic sanity checks for required top-level keys
            required_keys = ["project", "frames"]
            missing_keys = [key for key in required_keys if key not in data]

            if missing_keys:
                msg = f"warden.yaml missing recommended keys: {', '.join(missing_keys)}"
                logger.warning("config_missing_recommended_keys", missing_keys=missing_keys)
                warnings.append(msg)

            # 2. Unknown key detection
            unknown_keys = sorted(set(data.keys()) - KNOWN_TOP_LEVEL_KEYS)

            if unknown_keys:
                msg = f"warden.yaml contains unknown top-level keys: {', '.join(unknown_keys)}"
                logger.warning("config_unknown_keys", unknown_keys=unknown_keys)
                warnings.append(msg)

            # 3. Type validation for known keys
            type_mismatches = []
            for key, expected_type in EXPECTED_TYPES.items():
                if key in data and not isinstance(data[key], expected_type):
                    actual_type = type(data[key]).__name__
                    expected_name = expected_type.__name__
                    type_mismatches.append(f"'{key}' should be {expected_name}, got {actual_type}")

            if type_mismatches:
                msg = f"warden.yaml type mismatches: {'; '.join(type_mismatches)}"
                logger.warning("config_type_mismatches", mismatches=type_mismatches)
                warnings.append(msg)

            # Return the first warning if any were collected
            if warnings:
                return CheckStatus.WARNING, warnings[0]

            return CheckStatus.SUCCESS, "warden.yaml is valid YAML with expected structure."

        except yaml.YAMLError as e:
            return CheckStatus.ERROR, f"Invalid YAML syntax: {e}"
        except Exception as e:
            return CheckStatus.ERROR, f"Unexpected error reading config: {e}"

    def check_warden_dir(self) -> tuple[CheckStatus, str]:
        if not self.warden_dir.exists():
            return CheckStatus.ERROR, ".warden directory not found. Project not initialized."
        return CheckStatus.SUCCESS, ".warden directory exists."

    def check_env(self) -> tuple[CheckStatus, str]:
        # Read provider from project config to tailor checks
        configured_provider = self._get_configured_provider()

        if configured_provider == "ollama":
            return self._check_ollama_env()
        elif configured_provider == "claude_code":
            return self._check_claude_code_env()

        # Cloud providers — check for at least one API key
        has_key = any([settings.openai_api_key, settings.azure_openai_api_key, settings.deepseek_api_key])

        if not has_key:
            return (
                CheckStatus.WARNING,
                "Missing: LLM API Key (OpenAI/Azure/DeepSeek). Zombie Mode (Offline) active. Intelligence reduced.",
            )
        return CheckStatus.SUCCESS, "Environment variables loaded and API keys present."

    def _get_configured_provider(self) -> str:
        """Read the LLM provider from the project config."""
        if not self.config_path.exists():
            return ""
        try:
            with open(self.config_path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("llm", {}).get("provider", "")
        except Exception:
            return ""

    def _check_ollama_env(self) -> tuple[CheckStatus, str]:
        """Check Ollama availability and model status."""
        import os

        ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        try:
            import urllib.request

            resp = urllib.request.urlopen(f"{ollama_host}/api/tags", timeout=3)
            import json

            models = [m["name"] for m in json.loads(resp.read()).get("models", [])]

            # Check configured model is installed
            configured_model = ""
            try:
                with open(self.config_path) as f:
                    data = yaml.safe_load(f) or {}
                configured_model = data.get("llm", {}).get("model", "")
            except Exception:
                pass

            if configured_model and configured_model not in models:
                return CheckStatus.WARNING, (
                    f"Ollama running ({len(models)} models) but configured model "
                    f"'{configured_model}' not installed. Run: ollama pull {configured_model}"
                )

            return CheckStatus.SUCCESS, f"Ollama running at {ollama_host} ({len(models)} models available)."
        except Exception:
            return CheckStatus.WARNING, f"Ollama not reachable at {ollama_host}. Start with: ollama serve"

    def _check_claude_code_env(self) -> tuple[CheckStatus, str]:
        """Check Claude Code CLI availability."""
        claude_path = shutil.which("claude")
        if not claude_path:
            return (
                CheckStatus.WARNING,
                "Claude Code CLI not found on PATH. Install: npm install -g @anthropic-ai/claude-code",
            )
        return CheckStatus.SUCCESS, f"Claude Code CLI found at {claude_path}."

    def check_frames(self) -> tuple[CheckStatus, str]:
        if not self.config_path.exists():
            return CheckStatus.ERROR, "Cannot check frames without warden.yaml"

        try:
            with open(self.config_path) as f:
                config = yaml.safe_load(f)
            if not isinstance(config, dict):
                return CheckStatus.ERROR, "Cannot check frames — config.yaml is not a valid mapping."
            deps = config.get("dependencies", {})
        except Exception:
            return CheckStatus.ERROR, "Cannot check frames — config.yaml is invalid."

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
            return (
                CheckStatus.ERROR,
                f"Drift detected in frames: {', '.join(drifted_frames)}. Run 'warden install -U' to repair.",
            )

        return CheckStatus.SUCCESS, f"All {len(deps)} dependent frames are installed and verified."

    def check_rules(self) -> tuple[CheckStatus, str]:
        if not self.config_path.exists():
            return CheckStatus.WARNING, "Skipping rule check (no config)."

        try:
            with open(self.config_path) as f:
                config = yaml.safe_load(f)
            if not isinstance(config, dict):
                return CheckStatus.ERROR, "Cannot check rules — config.yaml is not a valid mapping."
        except Exception:
            return CheckStatus.ERROR, "Cannot check rules — config.yaml is invalid."

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

    def check_tools(self) -> tuple[CheckStatus, str]:
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

    def check_vector_db(self) -> tuple[CheckStatus, str]:
        # Simple connectivity check
        # For now, just check if the directory exists and is writable
        index_path = self.warden_dir / "embeddings"
        if not index_path.exists():
            return CheckStatus.WARNING, "Semantic index not found. Run 'warden index' for context-aware analysis."
        return CheckStatus.SUCCESS, "Semantic index found."
