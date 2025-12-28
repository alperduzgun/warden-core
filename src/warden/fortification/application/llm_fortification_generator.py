"""
LLM-Enhanced Fortification Generator.

Generates intelligent security fixes and suggestions.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from warden.analysis.application.llm_phase_base import (
    LLMPhaseBase,
    LLMPhaseConfig,
    PromptTemplates,
)
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class Fortification:
    """Security fortification suggestion."""

    title: str
    detail: str
    file_path: str
    line_number: int
    severity: str
    original_code: str
    suggested_code: str
    explanation: str
    confidence: float

    def to_json(self) -> Dict[str, Any]:
        """Convert to JSON."""
        return {
            "title": self.title,
            "detail": self.detail,
            "filePath": self.file_path,
            "lineNumber": self.line_number,
            "severity": self.severity,
            "originalCode": self.original_code,
            "suggestedCode": self.suggested_code,
            "explanation": self.explanation,
            "confidence": self.confidence,
        }


class LLMFortificationGenerator(LLMPhaseBase):
    """
    Generates security fortifications using LLM.

    Creates production-ready fixes for identified vulnerabilities.
    """

    @property
    def phase_name(self) -> str:
        """Get phase name."""
        return "FORTIFICATION"

    def get_system_prompt(self) -> str:
        """Get fortification system prompt."""
        return PromptTemplates.FIX_GENERATION + """

Fix Generation Guidelines:
1. SECURITY FIRST: Fixes must completely resolve the vulnerability
2. MAINTAIN FUNCTIONALITY: Don't break existing features
3. FOLLOW BEST PRACTICES: Use industry-standard solutions
4. FRAMEWORK-SPECIFIC: Use framework's built-in security features
5. MINIMAL CHANGES: Make the smallest secure change possible
6. BACKWARD COMPATIBLE: Avoid breaking changes when possible

Common Fixes by Vulnerability Type:

SQL Injection:
- Use parameterized queries
- Use ORM query builders
- Never concatenate user input

XSS (Cross-Site Scripting):
- HTML escape all output
- Use framework's template engine
- Content Security Policy headers

Hardcoded Secrets:
- Move to environment variables
- Use secret management services
- Implement key rotation

Authentication Issues:
- Use secure session management
- Implement proper password hashing
- Add rate limiting

Path Traversal:
- Validate and sanitize file paths
- Use safe path joining functions
- Implement access control

Return fixes as JSON with code examples."""

    def format_user_prompt(self, context: Dict[str, Any]) -> str:
        """Format prompt for fortification generation."""
        finding = context.get("finding", {})
        code_context = context.get("code_context", "")
        framework = context.get("framework", "none")
        language = context.get("language", "python")

        prompt = f"""Generate a security fix for this vulnerability:

VULNERABILITY:
Type: {finding.get('type', 'unknown')}
Severity: {finding.get('severity', 'medium')}
Message: {finding.get('message', '')}
File: {finding.get('file_path', '')}
Line: {finding.get('line_number', 0)}

VULNERABLE CODE:
```{language}
{finding.get('code_snippet', '')}
```

SURROUNDING CODE CONTEXT:
```{language}
{code_context}
```

FRAMEWORK: {framework}
LANGUAGE: {language}

Generate a secure fix that:
1. Completely resolves the vulnerability
2. Maintains functionality
3. Uses {framework} best practices
4. Is production-ready

Provide:
1. Fixed code snippet
2. Explanation of the fix
3. Any additional configuration needed
4. Testing recommendations

Return as JSON with:
- title: Brief description
- original_code: The vulnerable code
- suggested_code: The fixed code
- explanation: Why this fixes the issue
- additional_config: Any config changes needed
- testing_notes: How to verify the fix"""

        return prompt

    def parse_llm_response(self, response: str) -> Dict[str, Any]:
        """Parse fortification response."""
        try:
            # Extract JSON
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "{" in response and "}" in response:
                start = response.index("{")
                end = response.rindex("}") + 1
                json_str = response[start:end]
            else:
                raise ValueError("No JSON found in response")

            result = json.loads(json_str)

            # Ensure required fields
            result.setdefault("title", "Security Fix")
            result.setdefault("original_code", "")
            result.setdefault("suggested_code", "")
            result.setdefault("explanation", "")
            result.setdefault("additional_config", "")
            result.setdefault("testing_notes", "")

            return result

        except Exception as e:
            logger.error(
                "fortification_parse_failed",
                error=str(e),
                phase=self.phase_name,
            )
            return self._get_default_fix()

    async def generate_fortification(
        self,
        finding: Dict[str, Any],
        code_context: str,
        framework: str = "none",
        language: str = "python",
    ) -> Optional[Fortification]:
        """
        Generate fortification for a vulnerability.

        Args:
            finding: Vulnerability finding
            code_context: Surrounding code context
            framework: Framework being used
            language: Programming language

        Returns:
            Fortification suggestion or None
        """
        context = {
            "finding": finding,
            "code_context": code_context,
            "framework": framework,
            "language": language,
        }

        # Try LLM generation
        llm_result = await self.analyze_with_llm(context)

        if llm_result:
            fortification = Fortification(
                title=llm_result["title"],
                detail=f"Fix for {finding.get('type', 'vulnerability')}",
                file_path=finding.get("file_path", ""),
                line_number=finding.get("line_number", 0),
                severity=finding.get("severity", "medium"),
                original_code=llm_result["original_code"],
                suggested_code=llm_result["suggested_code"],
                explanation=llm_result["explanation"],
                confidence=0.85,
            )

            logger.info(
                "fortification_generated",
                type=finding.get("type"),
                confidence=0.85,
            )

            return fortification

        # Fallback to template-based fix
        return self._generate_template_fix(finding, framework, language)

    async def generate_batch_fortifications(
        self,
        findings: List[Dict[str, Any]],
        code_contexts: Dict[str, str],
        framework: str = "none",
        language: str = "python",
    ) -> List[Fortification]:
        """
        Generate fortifications for multiple findings.

        Args:
            findings: List of vulnerability findings
            code_contexts: Code context by file path
            framework: Framework being used
            language: Programming language

        Returns:
            List of fortifications
        """
        fortifications = []

        # Prepare contexts for batch processing
        contexts = []
        for finding in findings:
            file_path = finding.get("file_path", "")
            context = {
                "finding": finding,
                "code_context": code_contexts.get(file_path, ""),
                "framework": framework,
                "language": language,
            }
            contexts.append(context)

        # Batch LLM processing
        llm_results = await self.analyze_batch_with_llm(contexts)

        # Process results
        for i, finding in enumerate(findings):
            llm_result = llm_results[i]

            if llm_result:
                fortification = Fortification(
                    title=llm_result["title"],
                    detail=f"Fix for {finding.get('type', 'vulnerability')}",
                    file_path=finding.get("file_path", ""),
                    line_number=finding.get("line_number", 0),
                    severity=finding.get("severity", "medium"),
                    original_code=llm_result["original_code"],
                    suggested_code=llm_result["suggested_code"],
                    explanation=llm_result["explanation"],
                    confidence=0.85,
                )
                fortifications.append(fortification)
            else:
                # Fallback to template
                template_fix = self._generate_template_fix(finding, framework, language)
                if template_fix:
                    fortifications.append(template_fix)

        return fortifications

    def _generate_template_fix(
        self,
        finding: Dict[str, Any],
        framework: str,
        language: str,
    ) -> Optional[Fortification]:
        """Generate template-based fix as fallback."""
        vuln_type = finding.get("type", "").lower()

        templates = {
            "sql_injection": self._sql_injection_template,
            "xss": self._xss_template,
            "hardcoded_secret": self._hardcoded_secret_template,
            "hardcoded_password": self._hardcoded_secret_template,
            "path_traversal": self._path_traversal_template,
        }

        template_func = templates.get(vuln_type)
        if template_func:
            return template_func(finding, framework, language)

        return None

    def _sql_injection_template(
        self,
        finding: Dict[str, Any],
        framework: str,
        language: str,
    ) -> Fortification:
        """SQL injection fix template."""
        original = finding.get("code_snippet", "")

        if language == "python":
            if framework == "django":
                suggested = """# Use Django ORM
from myapp.models import User

# Safe parameterized query
users = User.objects.filter(username=username)"""
            elif framework == "fastapi":
                suggested = """# Use SQLAlchemy with parameters
from sqlalchemy import text

# Safe parameterized query
query = text("SELECT * FROM users WHERE username = :username")
result = db.execute(query, {"username": username})"""
            else:
                suggested = """# Use parameterized query
cursor.execute(
    "SELECT * FROM users WHERE username = %s",
    (username,)
)"""

        elif language == "javascript":
            suggested = """// Use parameterized query
const query = 'SELECT * FROM users WHERE username = ?';
db.query(query, [username], (err, results) => {
    // Handle results
});"""
        else:
            suggested = "Use parameterized queries or prepared statements"

        return Fortification(
            title="SQL Injection Protection",
            detail="Replace string concatenation with parameterized query",
            file_path=finding.get("file_path", ""),
            line_number=finding.get("line_number", 0),
            severity=finding.get("severity", "critical"),
            original_code=original,
            suggested_code=suggested,
            explanation="Parameterized queries prevent SQL injection by separating SQL logic from data",
            confidence=0.7,
        )

    def _xss_template(
        self,
        finding: Dict[str, Any],
        framework: str,
        language: str,
    ) -> Fortification:
        """XSS fix template."""
        original = finding.get("code_snippet", "")

        if framework == "django":
            suggested = """# Django auto-escapes in templates
# In template: {{ user_input }}
# Or explicitly: {{ user_input|escape }}"""
        elif framework == "fastapi":
            suggested = """# Use Jinja2 with auto-escape
from markupsafe import escape

# Escape user input
safe_input = escape(user_input)"""
        elif framework == "react":
            suggested = """// React auto-escapes by default
// Safe: <div>{userInput}</div>
// Unsafe: <div dangerouslySetInnerHTML={{__html: userInput}} />"""
        else:
            suggested = """# HTML escape user input
import html
safe_input = html.escape(user_input)"""

        return Fortification(
            title="XSS Protection",
            detail="Escape HTML in user-generated content",
            file_path=finding.get("file_path", ""),
            line_number=finding.get("line_number", 0),
            severity=finding.get("severity", "high"),
            original_code=original,
            suggested_code=suggested,
            explanation="HTML escaping prevents XSS by converting special characters to HTML entities",
            confidence=0.7,
        )

    def _hardcoded_secret_template(
        self,
        finding: Dict[str, Any],
        framework: str,
        language: str,
    ) -> Fortification:
        """Hardcoded secret fix template."""
        original = finding.get("code_snippet", "")

        if language == "python":
            suggested = """# Use environment variables
import os
from dotenv import load_dotenv

load_dotenv()

# Get secret from environment
API_KEY = os.getenv('API_KEY')
if not API_KEY:
    raise ValueError('API_KEY environment variable not set')"""
        elif language == "javascript":
            suggested = """// Use environment variables
require('dotenv').config();

// Get secret from environment
const API_KEY = process.env.API_KEY;
if (!API_KEY) {
    throw new Error('API_KEY environment variable not set');
}"""
        else:
            suggested = "Move secrets to environment variables or secret management service"

        return Fortification(
            title="Remove Hardcoded Secret",
            detail="Move sensitive data to environment variables",
            file_path=finding.get("file_path", ""),
            line_number=finding.get("line_number", 0),
            severity=finding.get("severity", "critical"),
            original_code=original,
            suggested_code=suggested,
            explanation="Environment variables keep secrets out of source code and version control",
            confidence=0.7,
        )

    def _path_traversal_template(
        self,
        finding: Dict[str, Any],
        framework: str,
        language: str,
    ) -> Fortification:
        """Path traversal fix template."""
        original = finding.get("code_snippet", "")

        if language == "python":
            suggested = """# Validate and sanitize file paths
import os
from pathlib import Path

# Define safe base directory
BASE_DIR = Path('/safe/directory')

def safe_path_join(user_input):
    # Resolve to absolute path
    requested_path = (BASE_DIR / user_input).resolve()

    # Ensure path is within base directory
    if not str(requested_path).startswith(str(BASE_DIR)):
        raise ValueError('Invalid file path')

    return requested_path"""
        elif language == "javascript":
            suggested = """// Validate and sanitize file paths
const path = require('path');

const BASE_DIR = '/safe/directory';

function safePathJoin(userInput) {
    // Resolve to absolute path
    const requestedPath = path.resolve(BASE_DIR, userInput);

    // Ensure path is within base directory
    if (!requestedPath.startsWith(BASE_DIR)) {
        throw new Error('Invalid file path');
    }

    return requestedPath;
}"""
        else:
            suggested = "Validate paths and ensure they stay within allowed directories"

        return Fortification(
            title="Path Traversal Protection",
            detail="Validate and sanitize file paths",
            file_path=finding.get("file_path", ""),
            line_number=finding.get("line_number", 0),
            severity=finding.get("severity", "high"),
            original_code=original,
            suggested_code=suggested,
            explanation="Path validation prevents directory traversal attacks by restricting file access",
            confidence=0.7,
        )

    def _get_default_fix(self) -> Dict[str, Any]:
        """Get default fix when parsing fails."""
        return {
            "title": "Security Fix Required",
            "original_code": "",
            "suggested_code": "// Review and fix this vulnerability",
            "explanation": "Manual review required",
            "additional_config": "",
            "testing_notes": "",
        }