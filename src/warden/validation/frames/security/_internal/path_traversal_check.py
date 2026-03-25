"""
Path Traversal Detection Check (CWE-22).

Detects cases where user-controlled input is used in file paths
without proper sanitization, enabling directory traversal attacks.
"""

import re

from warden.shared.infrastructure.logging import get_logger
from warden.validation.domain.check import (
    CheckFinding,
    CheckResult,
    CheckSeverity,
    ValidationCheck,
)
from warden.validation.domain.frame import CodeFile

logger = get_logger(__name__)

# User-controlled input sources (reused from open redirect logic)
_USER_SOURCES = re.compile(
    r"request\.(args|form|json|values|get_json|data|params|query)\b"
    r"|req\.(query|body|params)\b"
    r"|params\[|request\.GET\b|request\.POST\b"
    r"|getParameter\(|@RequestParam|@PathVariable"
    r"|c\.Query\(|c\.Param\(|r\.URL\.Query\(\)"
    r"|context\.params|event\.(queryStringParameters|pathParameters)",
)

# File operation sinks (opening / reading / writing user-derived paths)
_FILE_SINK_PATTERNS = [
    # Python
    (re.compile(r"\bopen\s*\("), "Python open()"),
    (re.compile(r"\bpathlib\.Path\s*\("), "pathlib.Path()"),
    (re.compile(r"\bos\.path\.join\s*\("), "os.path.join()"),
    (re.compile(r"\bos\.(open|stat|listdir|scandir|makedirs|remove|unlink)\s*\("), "os file operation"),
    # JavaScript / Node.js
    (re.compile(r"\bfs\.(readFile|writeFile|readFileSync|writeFileSync|stat|exists|unlink)\s*\("), "Node.js fs operation"),
    (re.compile(r"\bpath\.join\s*\("), "path.join()"),
    (re.compile(r"\bpath\.resolve\s*\("), "path.resolve()"),
    # Go
    (re.compile(r"\bos\.(Open|Create|ReadFile|WriteFile|Stat|Remove)\s*\("), "Go os file operation"),
    (re.compile(r"\bioutil\.(ReadFile|WriteFile)\s*\("), "Go ioutil file operation"),
    (re.compile(r"\bfilepath\.Join\s*\("), "Go filepath.Join()"),
    # Java
    (re.compile(r"\bnew\s+File\s*\("), "Java new File()"),
    (re.compile(r"\bnew\s+FileInputStream\s*\("), "Java FileInputStream"),
    (re.compile(r"\bPaths\.get\s*\("), "Java Paths.get()"),
]

# Known sanitizers — suppress if visible nearby
_SAFE_SANITIZERS = re.compile(
    r"os\.path\.basename\s*\("
    r"|path\.basename\s*\("
    r"|pathlib\.PurePath\s*\("
    r"|re\.sub.*\.\."       # stripping ../
    r"|replace\s*\(\s*['\"]\.\./"
    r"|sanitize_path|safe_path|validate_path"
    r"|filepath\.Clean\s*\("
    r"|filepath\.Abs\s*\("
    r"|Paths\.get.*\.normalize\s*\("
    r"|realpath\s*\(",
    re.IGNORECASE,
)

# Suspicious variable names that suggest user-derived path.
# Match the name as a whole word anywhere on the line (not just at assignment).
_SUSPICIOUS_PATH_VARS = re.compile(
    r"\b(filename|file_name|filepath|file_path|dir_path|dirname|"
    r"basepath|base_path|upload_path|download_path|resource_path|"
    r"document_path|media_path)\b",
    re.IGNORECASE,
)


def _lines_around(lines: list[str], idx: int, window: int = 4) -> str:
    start = max(0, idx - window)
    end = min(len(lines), idx + window + 1)
    return "\n".join(lines[start:end])


class PathTraversalCheck(ValidationCheck):
    """
    Detects path traversal vulnerabilities (CWE-22).

    Patterns detected:
    - open(request.args['file']) without path normalization
    - fs.readFile(req.query.path) without basename sanitization
    - os.Open(c.Query("file")) without filepath.Clean
    - File operations with suspicious user-derived path variables

    Severity: HIGH (can expose arbitrary server files)
    """

    id = "path-traversal"
    name = "Path Traversal Detection"
    description = "Detects unvalidated user-controlled file paths (CWE-22)"
    severity = CheckSeverity.HIGH
    version = "1.0.0"
    author = "Warden Security Team"
    enabled_by_default = True

    async def execute_async(self, code_file: CodeFile) -> CheckResult:
        """Execute path traversal detection."""
        findings: list[CheckFinding] = []
        lines = code_file.content.split("\n")

        for idx, line in enumerate(lines):
            line_num = idx + 1

            # Skip comment lines
            stripped = line.strip()
            if stripped.startswith(("#", "//", "*", "/*")):
                continue

            # Must be a file operation sink
            sink_label = None
            for pattern, label in _FILE_SINK_PATTERNS:
                if pattern.search(line):
                    sink_label = label
                    break
            if not sink_label:
                continue

            # Check user source on same line OR suspicious path variable
            has_user_source = bool(_USER_SOURCES.search(line))
            has_suspicious_var = bool(_SUSPICIOUS_PATH_VARS.search(line))

            if not has_user_source and not has_suspicious_var:
                continue

            # Suppress if sanitizer visible in a tight context window (2 lines).
            # Narrow window prevents cross-function false suppression.
            context = _lines_around(lines, idx, window=2)
            if _SAFE_SANITIZERS.search(context):
                logger.debug(
                    "path_traversal_suppressed_by_sanitizer",
                    file=str(code_file.path),
                    line=line_num,
                )
                continue

            # Inline suppression
            suppression_matcher = self._get_suppression_matcher(code_file.path)
            if suppression_matcher and suppression_matcher.is_suppressed(
                line=line_num,
                rule=self.id,
                file_path=str(code_file.path),
                code=code_file.content,
            ):
                continue

            reason = (
                f"User-controlled input passed to {sink_label}"
                if has_user_source
                else f"Suspicious path variable in {sink_label}"
            )

            findings.append(
                CheckFinding(
                    check_id=self.id,
                    check_name=self.name,
                    severity=self.severity,
                    message=f"Path traversal risk: {reason}",
                    location=f"{code_file.path}:{line_num}",
                    code_snippet=line.strip(),
                    suggestion=(
                        "Sanitize file paths before using them:\n"
                        "✅ GOOD: safe = os.path.basename(user_input)  # strip directory components\n"
                        "✅ GOOD: safe = pathlib.Path(base_dir / user_input).resolve().relative_to(base_dir)\n"
                        "✅ GOOD: Go: filepath.Clean(filepath.Join(baseDir, userInput))\n"
                        "❌ BAD:  open(request.args['file'])  # no sanitization"
                    ),
                    documentation_url="https://cwe.mitre.org/data/definitions/22.html",
                )
            )

        return CheckResult(
            check_id=self.id,
            check_name=self.name,
            passed=len(findings) == 0,
            findings=findings,
        )
