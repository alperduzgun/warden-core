"""
LLM-Enhanced Cleaning Generator.

Generates intelligent code quality improvements and refactoring suggestions.
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
class CleaningSuggestion:
    """Code cleaning/improvement suggestion."""

    title: str
    type: str  # dead_code, duplication, complexity, naming, import, documentation
    detail: str
    impact: str
    file_path: str
    line_range: Tuple[int, int]
    original_code: str
    suggested_code: str
    estimated_improvement: float  # 0-1 scale

    def to_json(self) -> Dict[str, Any]:
        """Convert to JSON."""
        return {
            "title": self.title,
            "type": self.type,
            "detail": self.detail,
            "impact": self.impact,
            "filePath": self.file_path,
            "lineRange": list(self.line_range),
            "originalCode": self.original_code,
            "suggestedCode": self.suggested_code,
            "estimatedImprovement": self.estimated_improvement,
        }


class LLMCleaningGenerator(LLMPhaseBase):
    """
    Generates code quality improvements using LLM.

    Suggests refactoring, cleanup, and optimization opportunities.
    """

    @property
    def phase_name(self) -> str:
        """Get phase name."""
        return "CLEANING"

    def get_system_prompt(self) -> str:
        """Get cleaning system prompt."""
        return PromptTemplates.CODE_IMPROVEMENT + """

Code Improvement Categories:

1. DEAD CODE REMOVAL
   - Unused variables, functions, imports
   - Unreachable code
   - Commented-out code blocks

2. DUPLICATION REDUCTION
   - Extract common patterns to functions
   - Create utility modules
   - Use inheritance/composition

3. COMPLEXITY REDUCTION
   - Break down large functions
   - Simplify nested conditionals
   - Extract methods
   - Use guard clauses

4. NAMING IMPROVEMENTS
   - Descriptive variable names
   - Consistent naming conventions
   - Remove abbreviations
   - Clear function names

5. IMPORT OPTIMIZATION
   - Remove unused imports
   - Organize imports properly
   - Avoid circular dependencies

6. DOCUMENTATION
   - Add missing docstrings
   - Update outdated comments
   - Improve inline documentation

7. PERFORMANCE
   - Algorithm improvements
   - Caching opportunities
   - Async optimization

8. MODERNIZATION
   - Use modern language features
   - Update deprecated APIs
   - Apply best practices

Focus on:
- Maintainability over cleverness
- Readability over brevity
- Testability over complexity

Return suggestions as JSON."""

    def format_user_prompt(self, context: Dict[str, Any]) -> str:
        """Format prompt for cleaning suggestions."""
        code = context.get("code", "")
        file_path = context.get("file_path", "")
        language = context.get("language", "python")
        quality_score = context.get("quality_score", 5.0)
        issues = context.get("issues", [])

        prompt = f"""Analyze this code and suggest improvements:

FILE: {file_path}
LANGUAGE: {language}
CURRENT QUALITY SCORE: {quality_score}/10

CODE:
```{language}
{code[:1200]}  # Truncate for token limit
```

KNOWN ISSUES:
{json.dumps(issues[:10], indent=2) if issues else "None identified"}

Please provide improvement suggestions for:
1. Dead code removal
2. Duplication reduction
3. Complexity simplification
4. Naming improvements
5. Import optimization
6. Documentation enhancements
7. Performance optimizations
8. Modernization opportunities

For each suggestion, provide:
- type: Category of improvement
- title: Brief description
- detail: Detailed explanation
- impact: Expected benefit
- original_code: Code to change
- suggested_code: Improved version
- estimated_improvement: Impact score (0-1)

Return top 5-10 most impactful suggestions as JSON array."""

        return prompt

    def parse_llm_response(self, response: str) -> List[Dict[str, Any]]:
        """Parse cleaning suggestions response."""
        try:
            # Extract JSON array
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "[" in response and "]" in response:
                start = response.index("[")
                end = response.rindex("]") + 1
                json_str = response[start:end]
            else:
                raise ValueError("No JSON array found in response")

            suggestions = json.loads(json_str)

            if not isinstance(suggestions, list):
                suggestions = [suggestions]

            # Validate each suggestion
            for suggestion in suggestions:
                suggestion.setdefault("type", "general")
                suggestion.setdefault("title", "Code Improvement")
                suggestion.setdefault("detail", "")
                suggestion.setdefault("impact", "")
                suggestion.setdefault("original_code", "")
                suggestion.setdefault("suggested_code", "")
                suggestion.setdefault("estimated_improvement", 0.5)

            return suggestions

        except Exception as e:
            logger.error(
                "cleaning_parse_failed",
                error=str(e),
                phase=self.phase_name,
            )
            return []

    async def generate_cleaning_suggestions(
        self,
        code: str,
        file_path: Path,
        quality_score: float = 5.0,
        issues: Optional[List[Dict[str, Any]]] = None,
        language: str = "python",
    ) -> List[CleaningSuggestion]:
        """
        Generate cleaning suggestions for code.

        Args:
            code: Source code to analyze
            file_path: Path to the file
            quality_score: Current quality score
            issues: Known issues from analysis
            language: Programming language

        Returns:
            List of cleaning suggestions
        """
        context = {
            "code": code,
            "file_path": str(file_path),
            "quality_score": quality_score,
            "issues": issues or [],
            "language": language,
        }

        # Try LLM generation
        llm_results = await self.analyze_with_llm(context)

        suggestions = []
        if llm_results:
            for result in llm_results:
                suggestion = CleaningSuggestion(
                    title=result["title"],
                    type=result["type"],
                    detail=result["detail"],
                    impact=result["impact"],
                    file_path=str(file_path),
                    line_range=(0, 0),  # Would need line detection
                    original_code=result["original_code"],
                    suggested_code=result["suggested_code"],
                    estimated_improvement=result["estimated_improvement"],
                )
                suggestions.append(suggestion)

            logger.info(
                "cleaning_suggestions_generated",
                count=len(suggestions),
                file=str(file_path),
            )

        # Add rule-based suggestions if LLM fails or as supplement
        if not suggestions or len(suggestions) < 3:
            rule_suggestions = self._generate_rule_based_suggestions(
                code, file_path, language
            )
            suggestions.extend(rule_suggestions)

        return suggestions[:10]  # Limit to top 10

    async def generate_batch_suggestions(
        self,
        files: List[Tuple[str, Path, float]],
        issues_by_file: Optional[Dict[Path, List[Dict[str, Any]]]] = None,
        language: str = "python",
    ) -> Dict[Path, List[CleaningSuggestion]]:
        """
        Generate suggestions for multiple files.

        Args:
            files: List of (code, path, quality_score) tuples
            issues_by_file: Known issues by file
            language: Programming language

        Returns:
            Dictionary of path to suggestions
        """
        all_suggestions = {}

        # Process in batches
        contexts = []
        for code, path, quality_score in files:
            context = {
                "code": code,
                "file_path": str(path),
                "quality_score": quality_score,
                "issues": issues_by_file.get(path, []) if issues_by_file else [],
                "language": language,
            }
            contexts.append(context)

        # Batch LLM processing
        llm_results = await self.analyze_batch_with_llm(contexts)

        # Process results
        for i, (code, path, quality_score) in enumerate(files):
            suggestions = []
            llm_result = llm_results[i]

            if llm_result:
                for result in llm_result:
                    suggestion = CleaningSuggestion(
                        title=result["title"],
                        type=result["type"],
                        detail=result["detail"],
                        impact=result["impact"],
                        file_path=str(path),
                        line_range=(0, 0),
                        original_code=result["original_code"],
                        suggested_code=result["suggested_code"],
                        estimated_improvement=result["estimated_improvement"],
                    )
                    suggestions.append(suggestion)

            # Add rule-based if needed
            if len(suggestions) < 3:
                rule_suggestions = self._generate_rule_based_suggestions(
                    code, path, language
                )
                suggestions.extend(rule_suggestions)

            all_suggestions[path] = suggestions[:10]

        return all_suggestions

    def _generate_rule_based_suggestions(
        self,
        code: str,
        file_path: Path,
        language: str,
    ) -> List[CleaningSuggestion]:
        """Generate rule-based cleaning suggestions."""
        suggestions = []

        # Check for common issues
        lines = code.split("\n")

        # Dead code: Commented code blocks
        commented_blocks = self._find_commented_blocks(lines)
        if commented_blocks:
            suggestions.append(
                CleaningSuggestion(
                    title="Remove Commented Code",
                    type="dead_code",
                    detail=f"Found {len(commented_blocks)} commented code blocks",
                    impact="Improves readability and reduces clutter",
                    file_path=str(file_path),
                    line_range=(0, len(lines)),
                    original_code="# Commented code blocks present",
                    suggested_code="# Remove commented code blocks",
                    estimated_improvement=0.3,
                )
            )

        # Complexity: Long functions
        long_functions = self._find_long_functions(lines, language)
        for func_name, length in long_functions:
            suggestions.append(
                CleaningSuggestion(
                    title=f"Refactor Long Function: {func_name}",
                    type="complexity",
                    detail=f"Function has {length} lines, consider breaking it down",
                    impact="Reduces complexity and improves testability",
                    file_path=str(file_path),
                    line_range=(0, 0),
                    original_code=f"def {func_name}(): # {length} lines",
                    suggested_code=f"# Break into smaller functions",
                    estimated_improvement=0.5,
                )
            )

        # Naming: Short variable names
        short_vars = self._find_short_variable_names(code, language)
        if short_vars:
            suggestions.append(
                CleaningSuggestion(
                    title="Improve Variable Names",
                    type="naming",
                    detail=f"Found {len(short_vars)} single-letter or unclear variable names",
                    impact="Improves code readability",
                    file_path=str(file_path),
                    line_range=(0, 0),
                    original_code=f"Variables: {', '.join(short_vars[:5])}",
                    suggested_code="Use descriptive variable names",
                    estimated_improvement=0.4,
                )
            )

        # Imports: Check for organization
        if language == "python" and self._check_import_organization(lines):
            suggestions.append(
                CleaningSuggestion(
                    title="Organize Imports",
                    type="import",
                    detail="Imports are not properly organized",
                    impact="Improves code organization",
                    file_path=str(file_path),
                    line_range=(0, 20),
                    original_code="# Disorganized imports",
                    suggested_code="# Group: standard lib, third-party, local",
                    estimated_improvement=0.2,
                )
            )

        return suggestions

    def _find_commented_blocks(self, lines: List[str]) -> List[Tuple[int, int]]:
        """Find commented code blocks."""
        blocks = []
        in_block = False
        block_start = 0

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("#") and any(
                keyword in stripped
                for keyword in ["def ", "class ", "if ", "for ", "while "]
            ):
                if not in_block:
                    in_block = True
                    block_start = i
            elif in_block and not stripped.startswith("#"):
                blocks.append((block_start, i))
                in_block = False

        return blocks

    def _find_long_functions(
        self,
        lines: List[str],
        language: str,
    ) -> List[Tuple[str, int]]:
        """Find functions that are too long."""
        long_functions = []

        if language == "python":
            for i, line in enumerate(lines):
                if line.strip().startswith("def "):
                    func_name = line.split("(")[0].replace("def ", "").strip()
                    # Count lines until next def or class
                    length = 0
                    for j in range(i + 1, len(lines)):
                        if lines[j].strip().startswith(("def ", "class ")):
                            break
                        if lines[j].strip():
                            length += 1

                    if length > 50:  # Threshold for long function
                        long_functions.append((func_name, length))

        return long_functions

    def _find_short_variable_names(
        self,
        code: str,
        language: str,
    ) -> List[str]:
        """Find single-letter or unclear variable names."""
        import re

        short_vars = []

        if language == "python":
            # Find variable assignments
            pattern = r"^\s*([a-z])\s*="
            for match in re.finditer(pattern, code, re.MULTILINE):
                var_name = match.group(1)
                # Exclude common acceptable single letters
                if var_name not in ["i", "j", "k", "n", "x", "y", "z"]:
                    short_vars.append(var_name)

        return short_vars

    def _check_import_organization(self, lines: List[str]) -> bool:
        """Check if imports need organization."""
        import_lines = []
        for line in lines:
            if line.strip().startswith(("import ", "from ")):
                import_lines.append(line)
            elif line.strip() and not line.strip().startswith("#"):
                break  # Stop at first non-import, non-comment line

        if len(import_lines) < 3:
            return False

        # Check if they're grouped (standard, third-party, local)
        has_std = any("os" in l or "sys" in l for l in import_lines)
        has_third = any(
            pkg in l
            for l in import_lines
            for pkg in ["numpy", "pandas", "requests"]
        )
        has_local = any("." in l and "from ." in l for l in import_lines)

        # If mixed without blank lines, needs organization
        return has_std and (has_third or has_local) and len(import_lines) > 5