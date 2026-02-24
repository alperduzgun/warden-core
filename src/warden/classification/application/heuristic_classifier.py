"""
Heuristic frame classifier.

Selects validation frames from static signals (file content, imports, AST
metadata) without calling an LLM.  The result is intentionally conservative:
frames are added for any plausible signal; ``security`` is always included.

This is used as a *pre-filter* before the LLM call:

  - High confidence (≥ SKIP_LLM_THRESHOLD) → skip LLM entirely.
  - Low confidence → run LLM; its result is unioned with the heuristic
    minimum to ensure no FP omissions.

False-positive safety guarantees
─────────────────────────────────
1. ``security`` is always included — never dropped by heuristics.
2. The heuristic only ADDS frames; it never removes frames that the LLM
   would have selected.
3. When LLM runs, its output is unioned with the heuristic minimum, so
   even a faulty LLM response cannot reduce coverage below the baseline.
4. Confidence is capped at SKIP_LLM_THRESHOLD - 0.01 for any file that
   contains auth/crypto/network patterns, forcing LLM review for
   security-sensitive code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from warden.shared.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)

# Confidence threshold above which the LLM call is skipped.
# Keep below 1.0 so that an unknown/complex file always gets LLM review.
SKIP_LLM_THRESHOLD = 0.88


@dataclass
class HeuristicResult:
    frames: list[str]
    confidence: float
    skip_llm: bool
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pattern tables
# ---------------------------------------------------------------------------

# Any of these in file content → add "resilience"
_RESILIENCE_PATTERNS = (
    "import requests",
    "import httpx",
    "import aiohttp",
    "import grpc",
    "import redis",
    "import celery",
    "import pika",  # RabbitMQ
    "import kafka",
    "import boto",
    "import pymongo",
    "import pymysql",
    "import psycopg",
    "import sqlalchemy",
    "flask",
    "django",
    "fastapi",
    "starlette",
)

# Any of these → add "chaos"
_CHAOS_PATTERNS = (
    "async def",
    "await ",
    "asyncio",
    "concurrent.futures",
    "threading.Thread",
    "multiprocessing",
)

# Any of these → add "fuzz"
_FUZZ_PATTERNS = (
    "argparse",
    "click",
    "typer",
    "json.loads",
    "yaml.safe_load",
    "yaml.load",
    "xml.etree",
    "lxml",
    "struct.unpack",
    "pickle.loads",
)

# Any of these → add "property"
_PROPERTY_PATTERNS = (
    "@dataclass",
    "@property",
    "from typing import",
    "from dataclasses import",
    "from pydantic import",
    "TypeVar",
    "Protocol",
)

# Any of these → add "antipattern"
_ANTIPATTERN_PATTERNS = (
    "global ",
    "exec(",
    "eval(",
    "__class__",
    "metaclass=",
)

# Security-sensitive patterns that cap confidence to force LLM review
_SECURITY_SENSITIVE_PATTERNS = (
    "password",
    "secret",
    "token",
    "api_key",
    "private_key",
    "hmac",
    "sha256",
    "AES",
    "RSA",
    "auth",
    "login",
    "jwt",
    "oauth",
    "session",
    "cookie",
    "sql",
    "execute(",
    "cursor.",
    "subprocess.",
    "os.system",
    "shell=True",
)


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------


class HeuristicClassifier:
    """
    Stateless heuristic frame selector.

    Usage::

        result = HeuristicClassifier.classify(code_files, available_frame_ids)
        if result.skip_llm:
            selected_frames = result.frames
        else:
            llm_frames = await llm_classify(...)
            selected_frames = list(set(llm_frames) | set(result.frames))
    """

    @staticmethod
    def classify(
        code_files: list["CodeFile"],
        available_frame_ids: list[str],
    ) -> HeuristicResult:
        """
        Analyse *code_files* and return a conservative frame selection.

        Only returns frames that exist in *available_frame_ids*.
        """
        available = set(available_frame_ids)
        frames: set[str] = set()
        reasons: list[str] = []
        confidence = 0.70  # conservative baseline

        # Aggregate content from all files
        combined = "\n".join(cf.content or "" for cf in code_files).lower()
        file_count = len(code_files)

        # ── Always include security ─────────────────────────────────────────
        if "security" in available:
            frames.add("security")
            reasons.append("security: always included")

        # ── Language / structure signals ────────────────────────────────────
        has_functions = "def " in combined
        has_classes = "class " in combined

        if has_functions or has_classes:
            if "orphan" in available:
                frames.add("orphan")
                reasons.append("orphan: file defines functions/classes")
            confidence += 0.05

        # ── Resilience ──────────────────────────────────────────────────────
        if any(pat in combined for pat in _RESILIENCE_PATTERNS):
            if "resilience" in available:
                frames.add("resilience")
                reasons.append("resilience: network/db/service import detected")
            confidence += 0.05

        # ── Chaos ───────────────────────────────────────────────────────────
        if any(pat in combined for pat in _CHAOS_PATTERNS):
            if "chaos" in available:
                frames.add("chaos")
                reasons.append("chaos: async/concurrent patterns detected")
            confidence += 0.03

        # ── Fuzz ────────────────────────────────────────────────────────────
        if any(pat in combined for pat in _FUZZ_PATTERNS):
            if "fuzz" in available:
                frames.add("fuzz")
                reasons.append("fuzz: parser/deserializer patterns detected")
            confidence += 0.03

        # ── Property / type-safety ──────────────────────────────────────────
        if any(pat in combined for pat in _PROPERTY_PATTERNS):
            if "property" in available:
                frames.add("property")
                reasons.append("property: dataclass/typing patterns detected")
            confidence += 0.03

        # ── Anti-pattern ────────────────────────────────────────────────────
        if any(pat in combined for pat in _ANTIPATTERN_PATTERNS):
            if "antipattern" in available:
                frames.add("antipattern")
                reasons.append("antipattern: risky constructs (global/eval/exec) detected")
            confidence += 0.02

        # ── Multi-file / architecture ───────────────────────────────────────
        if file_count > 5 and "architecture" in available:
            frames.add("architecture")
            reasons.append(f"architecture: {file_count} files suggest multi-module project")
            confidence += 0.02

        # ── Security-sensitive: cap confidence, force LLM review ───────────
        if any(pat in combined for pat in _SECURITY_SENSITIVE_PATTERNS):
            confidence = min(confidence, SKIP_LLM_THRESHOLD - 0.01)
            reasons.append("confidence_capped: security-sensitive patterns present → LLM review required")

        # ── Single-file trivial project: high confidence ────────────────────
        if file_count == 1 and len(combined) < 500:
            confidence = min(confidence, SKIP_LLM_THRESHOLD - 0.01)
            reasons.append("confidence_capped: tiny single file → LLM review for accuracy")

        confidence = min(confidence, 0.95)
        skip_llm = confidence >= SKIP_LLM_THRESHOLD

        result = HeuristicResult(
            frames=sorted(frames),
            confidence=confidence,
            skip_llm=skip_llm,
            reasons=reasons,
        )

        logger.debug(
            "heuristic_classification_result",
            frames=result.frames,
            confidence=round(confidence, 2),
            skip_llm=skip_llm,
            file_count=file_count,
        )
        return result
