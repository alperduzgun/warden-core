"""
Pattern Analyzer for Code Quality Issues.

Detects common code patterns that need cleaning:
- Duplicate code
- Complex functions
- Naming issues
- Dead code
- Import problems
"""

import re
from typing import Any, Dict, List

from warden.validation.domain.frame import CodeFile
from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class PatternAnalyzer:
    """
    Analyzes code for quality patterns and anti-patterns.

    Responsibilities:
    - Detect duplicate code blocks
    - Find complex functions
    - Identify naming issues
    - Find dead code and unused imports
    """

    def analyze_code_patterns(
        self,
        code_file: CodeFile,
    ) -> Dict[str, Any]:
        """
        Analyze code for common quality issues.

        Args:
            code_file: Code file to analyze

        Returns:
            Dictionary with detected patterns
        """
        analysis = {}
        content = code_file.content

        # Check for duplicate code
        duplicates = self._find_duplicate_code(content)
        if duplicates:
            analysis["duplicate_code"] = duplicates

        # Check for complex functions (Python specific)
        if code_file.path.endswith('.py'):
            complex_funcs = self._find_complex_functions(content)
            if complex_funcs:
                analysis["complex_functions"] = complex_funcs

            # Check for unused imports
            dead_code = self._find_dead_code(content)
            if dead_code:
                analysis["dead_code"] = dead_code

        # Check for naming issues
        naming_issues = self._find_naming_issues(content)
        if naming_issues:
            analysis["naming_issues"] = naming_issues

        logger.info(
            "pattern_analysis_completed",
            file=code_file.path,
            patterns_found=list(analysis.keys()),
        )

        return analysis

    def _find_duplicate_code(
        self,
        content: str,
    ) -> List:
        """
        Find duplicate lines of code.

        Args:
            content: File content

        Returns:
            List of duplicate code occurrences
        """
        lines = content.split('\n')
        seen_lines = {}
        duplicates = []

        for i, line in enumerate(lines):
            # Only consider meaningful lines (>20 chars, not empty/comment)
            stripped = line.strip()
            if len(stripped) > 20 and not stripped.startswith('#'):
                if line in seen_lines:
                    duplicates.append((seen_lines[line], i, line))
                else:
                    seen_lines[line] = i

        # Return top 5 duplicates
        return duplicates[:5]

    def _find_complex_functions(
        self,
        content: str,
    ) -> List[Dict[str, Any]]:
        """
        Find overly complex functions.

        Args:
            content: Python file content

        Returns:
            List of complex functions
        """
        func_pattern = re.compile(r'^def\s+(\w+)\s*\([^)]*\):', re.MULTILINE)
        functions = list(func_pattern.finditer(content))
        complex_funcs = []

        for i, match in enumerate(functions):
            start_pos = match.start()
            # Find end of function (next function or end of file)
            end_pos = functions[i + 1].start() if i + 1 < len(functions) else len(content)
            func_content = content[start_pos:end_pos]

            # Count lines and complexity metrics
            line_count = func_content.count('\n')

            # Consider function complex if:
            # - More than 50 lines
            # - More than 10 if/for/while statements (cyclomatic complexity)
            if line_count > 50 or self._calculate_cyclomatic_complexity(func_content) > 10:
                complex_funcs.append({
                    "name": match.group(1),
                    "line_count": line_count,
                    "start_line": content[:start_pos].count('\n') + 1,
                    "complexity": self._calculate_cyclomatic_complexity(func_content),
                })

        return complex_funcs

    def _calculate_cyclomatic_complexity(
        self,
        func_content: str,
    ) -> int:
        """
        Calculate simplified cyclomatic complexity.

        Args:
            func_content: Function code

        Returns:
            Complexity score
        """
        complexity = 1  # Base complexity

        # Count decision points
        decision_keywords = [
            r'\bif\b',
            r'\belif\b',
            r'\bfor\b',
            r'\bwhile\b',
            r'\btry\b',
            r'\bexcept\b',
            r'\bwith\b',
            r'\band\b',
            r'\bor\b',
        ]

        for keyword in decision_keywords:
            matches = re.findall(keyword, func_content)
            complexity += len(matches)

        return complexity

    def _find_naming_issues(
        self,
        content: str,
    ) -> List[str]:
        """
        Find poor variable names.

        Args:
            content: File content

        Returns:
            List of bad variable names
        """
        # Find single-letter variables (except common loop counters)
        bad_names = re.findall(r'\b([a-z])\s*=', content)

        # Filter out common acceptable single letters
        acceptable = ['i', 'j', 'k', 'n', 'm', 'x', 'y', 'z']
        bad_names = [n for n in bad_names if n not in acceptable]

        # Also find very short names (2 chars)
        short_names = re.findall(r'\b([a-z]{2})\s*=', content)
        problematic_short = ['aa', 'bb', 'cc', 'dd', 'xx', 'yy', 'zz']
        bad_names.extend([n for n in short_names if n in problematic_short])

        return list(set(bad_names))

    def _find_dead_code(
        self,
        content: str,
    ) -> Dict[str, List[str]]:
        """
        Find dead code and unused imports.

        Args:
            content: Python file content

        Returns:
            Dictionary with dead code categories
        """
        dead_code = {}

        # Find unused imports
        import_pattern = re.compile(r'^(?:from\s+[\w.]+\s+)?import\s+(\w+)', re.MULTILINE)
        imports = []

        for match in import_pattern.finditer(content):
            imported_name = match.group(1)
            imports.append(imported_name)

        unused_imports = []
        for imp in imports:
            # Count occurrences (excluding the import line itself)
            # This is simplified - real analysis would use AST
            occurrences = content.count(imp)
            if occurrences == 1:  # Only appears in import
                unused_imports.append(imp)

        if unused_imports:
            dead_code["unused_imports"] = unused_imports

        # Find unused variables (simplified)
        var_pattern = re.compile(r'^(\w+)\s*=', re.MULTILINE)
        variables = []

        for match in var_pattern.finditer(content):
            var_name = match.group(1)
            if not var_name.isupper():  # Exclude constants
                variables.append(var_name)

        unused_vars = []
        for var in variables:
            # Simple heuristic: if variable only appears once (in assignment)
            if content.count(var) == 1:
                unused_vars.append(var)

        if unused_vars:
            dead_code["unused_variables"] = unused_vars[:5]  # Limit to 5

        return dead_code

    def create_duplication_suggestion(
        self,
        duplicates: List,
    ) -> Dict[str, Any]:
        """Create suggestion for duplicate code."""
        return {
            "title": "Remove Code Duplication",
            "type": "duplication",
            "description": f"Found {len(duplicates)} duplicate code blocks",
            "impact": "high",
            "effort": "medium",
            "recommendation": "Extract duplicate code into reusable functions",
        }

    def create_complexity_suggestion(
        self,
        complex_functions: List,
    ) -> Dict[str, Any]:
        """Create suggestion for complex functions."""
        func_names = [f["name"] for f in complex_functions[:3]]
        return {
            "title": "Simplify Complex Functions",
            "type": "complexity",
            "description": f"Functions too complex: {', '.join(func_names)}",
            "impact": "high",
            "effort": "high",
            "recommendation": "Break down large functions into smaller, focused ones",
            "details": [
                {
                    "function": f["name"],
                    "lines": f["line_count"],
                    "complexity": f.get("complexity", 0),
                }
                for f in complex_functions[:3]
            ],
        }

    def create_naming_suggestion(
        self,
        bad_names: List,
    ) -> Dict[str, Any]:
        """Create suggestion for naming issues."""
        return {
            "title": "Improve Variable Naming",
            "type": "naming",
            "description": f"Poor variable names found: {', '.join(bad_names[:5])}",
            "impact": "medium",
            "effort": "low",
            "recommendation": "Use descriptive variable names",
        }

    def create_dead_code_suggestion(
        self,
        dead_code: Dict,
    ) -> Dict[str, Any]:
        """Create suggestion for dead code."""
        unused_imports = dead_code.get("unused_imports", [])
        unused_vars = dead_code.get("unused_variables", [])

        description_parts = []
        if unused_imports:
            description_parts.append(f"Unused imports: {', '.join(unused_imports[:5])}")
        if unused_vars:
            description_parts.append(f"Unused variables: {', '.join(unused_vars[:3])}")

        return {
            "title": "Remove Dead Code",
            "type": "dead_code",
            "description": "; ".join(description_parts),
            "impact": "low",
            "effort": "low",
            "recommendation": "Remove unused imports and variables",
        }

    def create_import_suggestion(
        self,
        import_issues: Dict,
    ) -> Dict[str, Any]:
        """Create suggestion for import organization."""
        return {
            "title": "Organize Imports",
            "type": "imports",
            "description": "Imports need organization",
            "impact": "low",
            "effort": "low",
            "recommendation": "Group and sort imports according to PEP 8",
        }