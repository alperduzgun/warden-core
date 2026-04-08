"""
Timeout Configuration Check.

Detects missing or inadequate timeout configurations on:
- HTTP requests
- Database connections
- External API calls
- Async operations
"""

import re

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.check import (
    CheckFinding,
    CheckResult,
    CheckSeverity,
    ValidationCheck,
)
from warden.validation.domain.fp_exclusions import FPExclusionRegistry
from warden.validation.domain.frame import CodeFile

_fp_registry = FPExclusionRegistry()

logger = get_logger(__name__)


class TimeoutCheck(ValidationCheck):
    """
    Detects missing timeout configurations.

    Network calls without timeouts can hang indefinitely,
    causing thread starvation and cascading failures.

    Patterns detected:
    - HTTP requests without timeout parameter
    - Database connections without timeout
    - Async operations without timeout
    - External API calls without timeout

    Severity: HIGH (can cause production outages)
    """

    id = "timeout"
    name = "Timeout Configuration Check"
    description = "Detects network calls without timeout configuration"
    severity = CheckSeverity.HIGH
    version = "1.0.0"
    author = "Warden Chaos Team"
    enabled_by_default = True

    # Patterns for network calls without timeout
    RISKY_PATTERNS = [
        # Python requests - looks for requests.method(...) where 'timeout' is NOT in args
        (
            r"requests\.(?:get|post|put|delete|patch)\((?:(?!timeout).)*?\)",
            "requests HTTP call without timeout parameter",
            "requests.get(url, timeout=30)",
        ),
        # Python httpx
        (
            r"httpx\.(?:get|post|put|delete|patch)\((?:(?!timeout).)*?\)",
            "httpx HTTP call without timeout parameter",
            "httpx.get(url, timeout=30.0)",
        ),
        # Python aiohttp
        (
            r"aiohttp\.ClientSession\((?:(?!timeout).)*?\)",
            "aiohttp session without timeout",
            "aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))",
        ),
        # JavaScript/TypeScript fetch
        (
            r"fetch\((?:(?!signal).)*?\)",
            "fetch() without AbortSignal timeout",
            "fetch(url, { signal: AbortSignal.timeout(30000) })",
        ),
        # JavaScript axios
        (
            r"axios\.(?:get|post|put|delete|patch)\((?:(?!timeout).)*?\)",
            "axios HTTP call without timeout",
            "axios.get(url, { timeout: 30000 })",
        ),
        # Database connections
        (
            r"psycopg2\.connect\((?:(?!connect_timeout).)*?\)",
            "PostgreSQL connection without timeout",
            "psycopg2.connect(..., connect_timeout=10)",
        ),
        (
            r"pymongo\.MongoClient\((?:(?!serverSelectionTimeoutMS).)*?\)",
            "MongoDB connection without timeout",
            "pymongo.MongoClient(..., serverSelectionTimeoutMS=5000)",
        ),
        # Go — net/http client without timeout
        # http.Get/Post without a custom client that has Timeout set
        (
            r"\bhttp\.(?:Get|Post|PostForm)\s*\(",
            "Go http.Get/Post without custom client timeout",
            "client := &http.Client{Timeout: 30 * time.Second}; client.Get(url)",
        ),
        # Go — http.Client literal without Timeout field
        (
            r"&http\.Client\s*\{(?:[^}](?!Timeout))*\}",
            "Go http.Client without Timeout field",
            "&http.Client{Timeout: 30 * time.Second}",
        ),
        # Java — HttpURLConnection without setConnectTimeout
        (
            r"new\s+URL\s*\(.*\)\s*\.openConnection\s*\(",
            "Java URLConnection without connect/read timeout",
            "conn.setConnectTimeout(10000); conn.setReadTimeout(30000);",
        ),
        # Java — OkHttp without timeout builder
        (
            r"new\s+OkHttpClient\s*\(\s*\)",
            "OkHttp client without timeout configuration",
            "new OkHttpClient.Builder().callTimeout(30, TimeUnit.SECONDS).build()",
        ),
        # Node.js — http.request / https.request without timeout
        (
            r"\b(?:http|https)\.request\s*\((?:(?!timeout).)*?\)",
            "Node.js http.request without timeout",
            "http.request({ ..., timeout: 30000 }, callback)",
        ),
        # got (Node.js) without timeout
        (
            r"\bgot\s*\((?:(?!timeout).)*?\)",
            "got HTTP call without timeout",
            "got(url, { timeout: { request: 30000 } })",
        ),
    ]

    async def execute_async(self, code_file: CodeFile) -> CheckResult:
        """Execute timeout configuration check."""
        findings: list[CheckFinding] = []

        for pattern_str, description, suggestion in self.RISKY_PATTERNS:
            pattern = re.compile(pattern_str, re.IGNORECASE | re.DOTALL)

            for line_num, line in enumerate(code_file.content.split("\n"), start=1):
                # Skip comments
                if line.strip().startswith("#") or line.strip().startswith("//"):
                    continue

                if "requests" in line:
                    match = pattern.search(line)
                else:
                    match = pattern.search(line)
                if match:
                    lines_list = code_file.content.split("\n")
                    ctx_start = max(0, line_num - 4)
                    ctx_end = min(len(lines_list), line_num + 3)
                    context = lines_list[ctx_start:ctx_end]
                    excl = _fp_registry.check(self.id, line, context)
                    if excl.is_excluded:
                        continue
                    findings.append(
                        CheckFinding(
                            check_id=self.id,
                            check_name=self.name,
                            severity=self.severity,
                            message=f"Missing timeout: {description}",
                            location=f"{code_file.path}:{line_num}",
                            code_snippet=line.strip(),
                            suggestion=(
                                f"Add timeout to prevent indefinite hangs:\n"
                                f"✅ GOOD: {suggestion}\n"
                                f"❌ BAD: {match.group(0)} (no timeout)\n\n"
                                "Recommended timeout: 30s for external APIs, "
                                "10s for internal services, 5s for databases"
                            ),
                            documentation_url="https://www.python-httpx.org/advanced/#timeout-configuration",
                        )
                    )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
            metadata={
                "patterns_checked": len(self.RISKY_PATTERNS),
                "recommended_timeout_external": "30s",
                "recommended_timeout_internal": "10s",
                "recommended_timeout_database": "5s",
            },
        )
