"""
Rust-powered Validation Engine.

Implements high-performance pre-filtering using Rust regex engine
and integrates with LLM for final validation (Alpha judgment).
"""

import asyncio
from pathlib import Path
from typing import List, Dict, Any, Optional
import structlog
import yaml

try:
    import warden_core_rust
    from warden_core_rust import RustRule, MatchHit
    RUST_AVAILABLE = True
except ImportError:
    RUST_AVAILABLE = False

from warden.validation.domain.frame import Finding
from warden.rules.domain.models import CustomRule, CustomRuleViolation

logger = structlog.get_logger(__name__)


class RustValidationEngine:
    """
    Engine for high-performance candidate detection and LLM-based verification.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.rules_metadata: Dict[str, Dict[str, Any]] = {}  # rule_id -> metadata
        self.rust_rules: List['RustRule'] = []

    async def load_rules_from_yaml_async(self, yaml_path: Path) -> None:
        """Load global rules from a YAML file (Async)."""
        if not RUST_AVAILABLE:
            logger.warning("rust_unavailable_skipping_rules", path=str(yaml_path))
            return

        try:
            # Use run_in_executor for file I/O to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(None, yaml_path.read_text, "utf-8")
            data = yaml.safe_load(content)
            if data and "rules" in data:
                for rule_data in data["rules"]:
                    if "id" in rule_data and "pattern" in rule_data:
                        pattern = rule_data["pattern"]
                        if isinstance(pattern, str):
                            pattern = pattern.strip()
                        self.rust_rules.append(RustRule(rule_data["id"], pattern))
                        self.rules_metadata[rule_data["id"]] = rule_data
                logger.debug("rules_loaded_from_yaml", path=str(yaml_path), count=len(data["rules"]))
        except Exception as e:
            logger.error("failed_to_load_rules", path=str(yaml_path), error=str(e), error_type=type(e).__name__)

    def add_custom_rules(self, rules: List[CustomRule]) -> None:
        """Add CustomRule objects to the engine."""
        if not RUST_AVAILABLE:
            return

        for rule in rules:
            if rule.pattern:
                self.rust_rules.append(RustRule(rule.id, rule.pattern.strip()))
                self.rules_metadata[rule.id] = {
                    "id": rule.id,
                    "name": rule.name,
                    "description": rule.description,
                    "severity": rule.severity.value if hasattr(rule.severity, 'value') else str(rule.severity),
                    "message": rule.message,
                }
        logger.debug("custom_rules_added", count=len(rules))

    async def scan_project_async(self, file_paths: List[Path]) -> List[Finding]:
        """
        Scan project files using Rust engine and verify with LLM.
        """
        if not self.rust_rules:
            logger.debug("no_rules_to_scan")
            return []

        # Convert Path to str
        str_files = [str(p) for p in file_paths]

        logger.info("rust_scan_started", file_count=len(str_files), rule_count=len(self.rust_rules))
        
        # Execute Rust scan
        loop = asyncio.get_event_loop()
        hits = await loop.run_in_executor(None, warden_core_rust.match_patterns, str_files, self.rust_rules)
        
        logger.info("rust_scan_completed", hit_count=len(hits))

        if not hits:
            return []

        # Convert hits directly to findings (pure scanning engine)
        findings = []
        for hit in hits:
            findings.append(self._hit_to_finding(hit))

        return findings

    def _hit_to_finding(self, hit_item: 'MatchHit', message_override: Optional[str] = None) -> Finding:
        """Convert a Rust hit to a Warden Finding."""
        rule = self.rules_metadata.get(hit_item.rule_id, {})
        
        rel_path = str(Path(hit_item.file_path).relative_to(self.project_root))
        
        return Finding(
            id=hit_item.rule_id,
            severity=rule.get("severity", "high"),
            message=message_override or rule.get("message", f"Vulnerability detected: {hit_item.rule_id}"),
            location=f"{rel_path}:{hit_item.line_number}",
            code=hit_item.snippet,
            line=hit_item.line_number,
            column=hit_item.column,
            is_blocker=rule.get("severity") == "critical"
        )
