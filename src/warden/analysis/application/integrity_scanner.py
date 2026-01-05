"""
Integrity Scanner for Pre-Analysis Phase.

Provides validation for code syntax and basic build verification.
"""

import asyncio
import shlex
import structlog
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from warden.validation.domain.frame import CodeFile
from warden.analysis.domain.project_context import ProjectContext, ProjectType, Framework
from warden.ast.application.provider_registry import ASTProviderRegistry
from warden.ast.domain.enums import CodeLanguage

logger = structlog.get_logger()

class IntegrityIssue:
    def __init__(self, file_path: str, message: str, severity: str = "error"):
        self.file_path = file_path
        self.message = message
        self.severity = severity
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file_path,
            "message": self.message,
            "severity": self.severity
        }

class IntegrityScanner:
    """
    Scans codebase for integrity issues (syntax, build).
    """

    def __init__(
        self, 
        project_root: Path,
        ast_registry: ASTProviderRegistry,
        config: Optional[Dict[str, Any]] = None
    ):
        self.project_root = project_root
        self.ast_registry = ast_registry
        self.config = config or {}

    async def scan(
        self, 
        code_files: List[CodeFile], 
        project_context: ProjectContext, 
        pipeline_context: Optional[Any] = None
    ) -> List[IntegrityIssue]:
        """
        Run integrity scan on code files.
        """
        issues = []
        
        # 1. Syntax Verification (Tree-sitter)
        syntax_issues = await self._check_syntax(code_files, pipeline_context)
        issues.extend(syntax_issues)
        
        # If too many syntax errors, we might want to skip build check to save time
        if len(issues) > 10:
            logger.warning("skipping_build_check_due_to_syntax_errors", count=len(issues))
            return issues

        # 2. Build Verification (Optional/Configured)
        enable_build_check = self.config.get("enable_build_check", True)
        if enable_build_check:
            build_issues = await self._verify_build(project_context)
            issues.extend(build_issues)
            
        return issues

    async def _check_syntax(self, code_files: List[CodeFile], pipeline_context: Optional[Any] = None) -> List[IntegrityIssue]:
        """Check syntax using loaded AST providers."""
        issues = []
        
        for cf in code_files:
            try:
                lang = self._guess_language(cf.path)
                if lang == CodeLanguage.UNKNOWN:
                    continue

                # Parse content
                logger.debug(f"DEBUG_SCAN: Checking {cf.path} with lang {lang}")
                provider = self.ast_registry.get_provider(lang)
                if not provider:
                    logger.debug(f"DEBUG_SCAN: No provider for {lang}")
                    continue
                
                result = await provider.parse(cf.content, lang, cf.path)
                
                if result.status == "failed" or result.errors:
                    for error in result.errors:
                        issues.append(IntegrityIssue(
                            file_path=str(Path(cf.path).relative_to(self.project_root)) if self.project_root in Path(cf.path).parents else cf.path,
                            message=f"Syntax error: {error.message}",
                            severity="error"
                        ))
                elif result.status == "success" and result.ast_root:
                    # CACHE AST IF CONTEXT PROVIDED
                    if pipeline_context and hasattr(pipeline_context, 'ast_cache'):
                        # Store the native AST node if available (provider specific)
                        if result.ast_root.raw_node:
                             pipeline_context.ast_cache[cf.path] = result.ast_root.raw_node
                             logger.debug("ast_cached_in_context", file=cf.path)
                    
            except Exception as e:
                logger.debug("syntax_check_exception", file=cf.path, error=str(e))
                # Don't fail the whole scan for a single file syntax check crash
                
        return issues

    def _find_error_node(self, node):
        """Recursively find the first error node."""
        if node.type == 'ERROR' or node.is_missing:
            return node
        
        for child in node.children:
            if child.has_error: # optimize traversal
                found = self._find_error_node(child)
                if found:
                    return found
        return None

    async def _verify_build(self, context: ProjectContext) -> List[IntegrityIssue]:
        """Verify build using native tools if detected."""
        issues = []
        
        command = self._detect_build_command(context)
        if not command:
            return []
            
        logger.info("executing_build_verification", command=command)
        
        try:
            # Run command with timeout
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_root,
                # Set process group to allow killing entire tree?
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0) # 30s timeout
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except: 
                    pass
                return [IntegrityIssue(
                    file_path="BUILD",
                    message=f"Build command '{command}' timed out after 30s.",
                    severity="error"
                )]

            if proc.returncode != 0:
                # Build failed
                error_msg = stderr.decode().strip() or stdout.decode().strip()
                # Truncate error message
                if len(error_msg) > 500:
                    error_msg = error_msg[:500] + "..."
                    
                issues.append(IntegrityIssue(
                    file_path="BUILD",
                    message=f"Build validation failed: {error_msg}",
                    severity="error"
                ))
                
        except Exception as e:
            logger.warning("build_verification_failed", error=str(e))
            issues.append(IntegrityIssue(
                file_path="BUILD",
                message=f"Build verification execution error: {str(e)}",
                severity="warning"
            ))
            
        return issues

    def _detect_build_command(self, context: ProjectContext) -> Optional[str]:
        """Detect applicable build command."""
        
        # Node/TypeScript
        if context.framework in [Framework.NEXTJS, Framework.REACT, Framework.EXPRESS]:
            package_json = self.project_root / "package.json"
            if package_json.exists():
                # Check if npm is installed
                if not shutil.which("npm"):
                    logger.debug("build_tool_missing", tool="npm")
                    return None
                return "npm run build"

        # Python (Interpreted, but can check compile)
        if context.framework in [Framework.FASTAPI, Framework.DJANGO, Framework.FLASK] or (self.project_root / "requirements.txt").exists() or (self.project_root / "pyproject.toml").exists():
            # Python compiles to bytecode.
            # python3 should be available if we are running warden
            return f"{sys.executable} -m compileall -q ."

        # Go
        if (self.project_root / "go.mod").exists():
            if not shutil.which("go"):
                logger.debug("build_tool_missing", tool="go")
                return None
            return "go build -o /dev/null ./..."

        return None

    def _guess_language(self, path: str) -> CodeLanguage:
        ext = Path(path).suffix.lower()
        mapping = {
            ".py": CodeLanguage.PYTHON,
            ".ts": CodeLanguage.TYPESCRIPT,
            ".tsx": CodeLanguage.TSX,
            ".js": CodeLanguage.JAVASCRIPT,
            ".jsx": CodeLanguage.JAVASCRIPT,
            ".go": CodeLanguage.GO,
            ".java": CodeLanguage.JAVA,
        }
        return mapping.get(ext, CodeLanguage.UNKNOWN)
