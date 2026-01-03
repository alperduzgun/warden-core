"""
Universal Secret Scanner Frame.

Detects hardcoded secrets (API keys, tokens, passwords) across all
languages supported by Warden's Universal AST.
"""

import re
import math
import time
from typing import List, Dict, Any, Optional

from warden.validation.application.base_universal_frame import BaseUniversalFrame
from warden.validation.domain.frame import FrameResult, Finding, CodeFile
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
    FrameApplicability,
)
from warden.ast.domain.enums import ASTNodeType
from warden.ast.domain.models import ASTNode
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


# Known secret patterns (regex)
SECRET_PATTERNS = [
    (r"(?:api[_-]?key|apikey)['\"]?\s*[:=]\s*['\"]([a-zA-Z0-9_\-]{20,})['\"]", "API Key"),
    (r"(?:secret|token)['\"]?\s*[:=]\s*['\"]([a-zA-Z0-9_\-]{20,})['\"]", "Secret/Token"),
    (r"(?:password|passwd|pwd)['\"]?\s*[:=]\s*['\"](.{8,})['\"]", "Password"),
    (r"sk_live_[a-zA-Z0-9]{24,}", "Stripe Live Key"),
    (r"sk_test_[a-zA-Z0-9]{24,}", "Stripe Test Key"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token"),
    (r"xox[baprs]-[a-zA-Z0-9\-]{10,}", "Slack Token"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID"),
    (r"AIza[0-9A-Za-z\-_]{35}", "Google API Key"),
]


def calculate_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string."""
    if not s:
        return 0.0
    prob = [float(s.count(c)) / len(s) for c in set(s)]
    return -sum(p * math.log2(p) for p in prob if p > 0)


class UniversalSecretScanner(BaseUniversalFrame):
    """
    Cross-language hardcoded secret detection frame.
    
    Uses Universal AST to find string literals and analyzes them for:
    1. Known secret patterns (API keys, tokens)
    2. High-entropy strings (potential secrets)
    """

    name = "Universal Secret Scanner"
    description = "Detects hardcoded secrets across all supported languages"
    category = FrameCategory.GLOBAL
    priority = FramePriority.HIGH
    scope = FrameScope.FILE_LEVEL
    is_blocker = True  # Secrets are critical
    version = "1.0.0"
    author = "Warden Team"
    applicability = [FrameApplicability.ALL]

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.entropy_threshold = self.config.get("entropy_threshold", 4.5)
        self.min_length = self.config.get("min_length", 16)

    async def execute(self, code_file: CodeFile) -> FrameResult:
        """Execute secret scanning on a single file."""
        start_time = time.perf_counter()
        findings: List[Finding] = []

        logger.info("secret_scan_started", file=code_file.path)

        # Get Universal AST
        ast_root = await self.get_universal_ast(code_file)

        if ast_root:
            # AST-based literal extraction
            literals = self._extract_literals_with_location(ast_root)
            for value, line in literals:
                finding = self._analyze_literal(value, line, code_file)
                if finding:
                    findings.append(finding)
        else:
            # Fallback: regex-based scanning on raw content
            logger.debug("ast_unavailable_using_regex", file=code_file.path)
            findings.extend(self._regex_scan(code_file))

        duration = time.perf_counter() - start_time
        status = "failed" if findings else "passed"

        logger.info(
            "secret_scan_completed",
            file=code_file.path,
            findings_count=len(findings),
            duration=f"{duration:.2f}s"
        )

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status=status,
            duration=duration,
            issues_found=len(findings),
            is_blocker=self.is_blocker and len(findings) > 0,
            findings=findings,
            metadata={"scan_mode": "ast" if ast_root else "regex"}
        )

    def _extract_literals_with_location(self, root: ASTNode) -> List[tuple]:
        """Extract string literals with their line numbers."""
        literals = []

        def walk(node: ASTNode):
            if node.node_type == ASTNodeType.LITERAL:
                if node.value and isinstance(node.value, str):
                    line = node.location.start_line if node.location else 0
                    literals.append((node.value, line))
            for child in node.children:
                walk(child)

        walk(root)
        return literals

    def _analyze_literal(self, value: str, line: int, code_file: CodeFile) -> Optional[Finding]:
        """Analyze a single literal for secret patterns."""
        # Skip short strings
        if len(value) < self.min_length:
            return None

        # Check known patterns
        for pattern, secret_type in SECRET_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                return Finding(
                    id=f"secret-{secret_type.lower().replace(' ', '-')}-{line}",
                    severity="critical",
                    message=f"Potential {secret_type} detected",
                    location=f"{code_file.path}:{line}",
                    detail=f"Found pattern matching {secret_type}. Remove and use environment variables.",
                    code=value[:50] + "..." if len(value) > 50 else value,
                    line=line,
                )

        # Check entropy
        entropy = calculate_entropy(value)
        if entropy >= self.entropy_threshold and len(value) >= 20:
            return Finding(
                id=f"secret-high-entropy-{line}",
                severity="high",
                message="High-entropy string detected (potential secret)",
                location=f"{code_file.path}:{line}",
                detail=f"String has entropy {entropy:.2f} (threshold: {self.entropy_threshold}). Review if this is a secret.",
                code=value[:50] + "..." if len(value) > 50 else value,
                line=line,
            )

        return None

    def _regex_scan(self, code_file: CodeFile) -> List[Finding]:
        """Fallback regex-based scanning."""
        findings = []
        lines = code_file.content.split("\n")

        for i, line in enumerate(lines, 1):
            for pattern, secret_type in SECRET_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    findings.append(Finding(
                        id=f"secret-{secret_type.lower().replace(' ', '-')}-{i}",
                        severity="critical",
                        message=f"Potential {secret_type} detected",
                        location=f"{code_file.path}:{i}",
                        detail=f"Found pattern matching {secret_type}.",
                        code=line.strip()[:80],
                        line=i,
                    ))
                    break  # One finding per line

        return findings
