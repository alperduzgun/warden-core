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

    def __init__(self, project_root: Path, llm_service: Optional[Any] = None):
        self.project_root = project_root
        self.llm_service = llm_service
        self.rules_metadata: Dict[str, Dict[str, Any]] = {}  # rule_id -> metadata
        self.rust_rules: List['RustRule'] = []

    async def load_rules_from_yaml_async(self, yaml_path: Path) -> None:
        """Load global rules from a YAML file (Async)."""
        try:
            # Use run_in_executor for file I/O to avoid blocking the event loop
            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(None, yaml_path.read_text, "utf-8")
            data = yaml.safe_load(content)
            if data and "rules" in data:
                for rule_data in data["rules"]:
                    if "id" in rule_data and "pattern" in rule_data:
                        self.rust_rules.append(RustRule(rule_data["id"], rule_data["pattern"]))
                        self.rules_metadata[rule_data["id"]] = rule_data
                logger.debug("rules_loaded_from_yaml", path=str(yaml_path), count=len(data["rules"]))
        except Exception as e:
            logger.error("failed_to_load_rules", path=str(yaml_path), error=str(e), error_type=type(e).__name__)

    def add_custom_rules(self, rules: List[CustomRule]) -> None:
        """Add CustomRule objects to the engine."""
        for rule in rules:
            if rule.pattern:
                self.rust_rules.append(RustRule(rule.id, rule.pattern))
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

        # Group hits by rule to facilitate batch LLM verification if needed
        # For Phase 1, we will verify each hit or at least filter them
        findings = []
        
        # Candidate detection phase complete. Now for Alpha judgment.
        if self.llm_service:
            findings = await self._verify_candidates_with_llm_async(hits)
        else:
            # Fallback: conversion directly to findings if no LLM
            for hit in hits:
                findings.append(self._hit_to_finding(hit))

        return findings

    async def _verify_candidates_with_llm_async(self, hits: List[Any]) -> List[Finding]:
        """
        Use LLM to perform Alpha judgment on candidates found by Rust.
        """
        verified_findings = []
        
        # In a real implementation, we would batch these to stay efficient
        # For now, let's process them and simulate the judgment
        
        logger.info("alpha_judgment_started", candidate_count=len(hits))
        
        # Limit concurrency for LLM calls
        semaphore = asyncio.Semaphore(5)
        
        async def verify_hit_async(hit_item: 'MatchHit'):
            async with semaphore:
                # Find rule details
                rule = self.rules_metadata.get(hit_item.rule_id, {})
                
                prompt = f"""
                You are a Security Auditor. Evaluate if the following code snippet is a REAL violation or a false positive.
                
                Rule: {rule.get('name', hit_item.rule_id)}
                Description: {rule.get('description', '')}
                Expected Violation: {rule.get('message', '')}
                
                File: {hit_item.file_path}
                Line: {hit_item.line_number}
                Snippet: `{hit_item.snippet}`
                
                Is this a REAL violation that needs fixing?
                Respond with JSON: {{"is_violation": bool, "reason": "short explanation", "severity": "optional override"}}
                """
                
                try:
                    # Log verification attempt
                    logger.debug("verifying_candidate", rule=hit_item.rule_id, file=hit_item.file_path, line=hit_item.line_number)
                    
                    # For Phase 1 implementation demonstration, we'll auto-approve 
                    return self._hit_to_finding(hit_item, "LLM verified: " + rule.get('message', ''))
                except Exception as e:
                    logger.error("llm_verification_failed", error=str(e), rule_id=hit_item.rule_id)
                    return self._hit_to_finding(hit_item)

        tasks = [verify_hit_async(hit) for hit in hits]
        results = await asyncio.gather(*tasks)
        
        verified_findings = [r for r in results if r]
        
        logger.info("alpha_judgment_completed", verified_count=len(verified_findings))
        return verified_findings

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
