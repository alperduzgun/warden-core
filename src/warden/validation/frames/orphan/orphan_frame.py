"""
Orphan Frame - Dead code and unused code detection.

Built-in checks:
- Unused imports detection
- Unreferenced functions detection
- Unreferenced classes detection
- Dead code (unreachable statements) detection

NEW: LLM-powered intelligent filtering (optional)
- Removes false positives using LLM context awareness
- Works for ANY programming language
- Configurable via use_llm_filter option

Priority: MEDIUM (warning)
"""

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from warden.validation.domain.enums import (
    FrameApplicability,
    FrameCategory,
    FramePriority,
    FrameScope,
)
from warden.validation.domain.frame import (
    CodeFile,
    Finding,
    FrameResult,
    ValidationFrame,
)
from warden.validation.domain.mixins import BatchExecutable

# Add current directory to path to allow importing sibling modules
current_dir = str(Path(__file__).parent)
if current_dir not in sys.path:
    sys.path.append(current_dir)

from llm_orphan_filter import LLMOrphanFilter
from orphan_detector import OrphanDetectorFactory, OrphanFinding

from warden.shared.infrastructure.logging import get_logger

logger = get_logger(__name__)


class OrphanFrame(ValidationFrame, BatchExecutable):
    """
    Orphan code validation frame - Detects dead and unused code.

    This frame detects:
    - Unused imports (imported but never referenced)
    - Unreferenced functions (defined but never called)
    - Unreferenced classes (defined but never used)
    - Dead code (unreachable statements after return/break/continue)

    Priority: MEDIUM (informational warning)
    Applicability: Python only (AST-based analysis)

    Implements:
    - BatchExecutable: For intelligent batch processing with LLM filtering
    """

    # Required metadata
    name = "Orphan Code Analysis"
    description = "Detects unused imports, unreferenced functions/classes, and dead code"
    category = FrameCategory.LANGUAGE_SPECIFIC
    priority = FramePriority.MEDIUM
    scope = FrameScope.FILE_LEVEL
    is_blocker = False  # Dead code is warning, not blocker
    version = "2.0.0"  # Upgraded: LLM filtering support
    author = "Warden Team"
    applicability = [
        FrameApplicability.PYTHON,
        FrameApplicability.TYPESCRIPT,
        FrameApplicability.JAVASCRIPT,
        FrameApplicability.GO,
        FrameApplicability.JAVA,
        FrameApplicability.CSHARP,
    ]

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialize OrphanFrame.

        Args:
            config: Frame configuration
                - use_llm_filter: bool (default: False) - Use LLM for intelligent filtering
                - ignore_private: bool (default: True) - Ignore private functions/classes
                - ignore_test_files: bool (default: True) - Ignore test files
                - ignore_imports: List[str] - Import names to ignore
        """
        super().__init__(config)

        # Configuration options
        self.use_llm_filter = self.config.get("use_llm_filter", False)
        self.ignore_private = self.config.get("ignore_private", True)
        self.ignore_test_files = self.config.get("ignore_test_files", True)
        self.ignore_imports = set(self.config.get("ignore_imports", []))

        # LLM filter (lazy initialization)
        self.llm_filter: LLMOrphanFilter | None = None

        # Log if enabled but defer creation until execution (when llm_service is injected)
        if self.use_llm_filter:
            logger.info("llm_orphan_filter_enabled", mode="intelligent_filtering")

    async def execute_batch_async(self, code_files: list[CodeFile]) -> list[FrameResult]:
        """
        Execute orphan detection on multiple files with Smart Batching.
        """
        start_time = time.perf_counter()
        logger.info("orphan_batch_execution_started", file_count=len(code_files))

        # 1. AST Analysis Phase (CPU Bound - fast)
        findings_map: dict[str, list[OrphanFinding]] = {}
        valid_files_map: dict[str, CodeFile] = {}

        results: list[FrameResult] = []

        for code_file in code_files:
            # Skip non-applicable
            if not self._is_applicable(code_file):
                results.append(self._create_skipped_result(time.perf_counter())) # duration approx 0
                continue

            try:
                # Check if LSP should be used from config
                use_lsp = self.config.get("use_lsp", False)
                project_root = getattr(self, 'project_root', None)

                detector = await OrphanDetectorFactory.create_detector(
                    code_file.content,
                    code_file.path,
                    use_lsp=use_lsp,
                    project_root=str(project_root) if project_root else None
                )
                if not detector:
                    # Language not supported
                    results.append(FrameResult(
                        frame_id=self.frame_id,
                        frame_name=self.name,
                        status="skipped",
                        duration=0.0,
                        issues_found=0,
                        is_blocker=False,
                        findings=[],
                        metadata={"reason": "unsupported_language"}
                    ))
                    continue

                # Call appropriate detection method (async for LSP, sync for others)
                from orphan_detector import LSPOrphanDetector
                if isinstance(detector, LSPOrphanDetector):
                    orphan_findings = await detector.detect_all_async()
                else:
                    orphan_findings = detector.detect_all()

                if orphan_findings:
                    findings_map[code_file.path] = orphan_findings
                    valid_files_map[code_file.path] = code_file
                else:
                    # No orphans found by AST, create passed result immediately
                    # Reuse helper or create new
                    results.append(FrameResult(
                        frame_id=self.frame_id,
                        frame_name=self.name,
                        status="passed",
                        duration=0.0,
                        issues_found=0,
                        is_blocker=False,
                        findings=[]
                    ))
            except Exception as e:
                logger.error("orphan_ast_error", file=code_file.path, error=str(e))
                # Add error result
                results.append(FrameResult(
                     frame_id=self.frame_id,
                     frame_name=self.name,
                     status="error",
                     duration=0.0,
                     issues_found=0,
                     is_blocker=False,
                     findings=[],
                     metadata={"error": str(e)}
                ))

        # 2. Filtering Phase (LLM or Basic)
        final_findings_map = {}

        llm_filter = self._get_or_create_filter()
        if self.use_llm_filter and llm_filter and findings_map:
            # Smart Batch LLM Filtering
            logger.info("starting_smart_batch_filter", total_candidates=sum(len(f_list) for f_list in findings_map.values()))
            final_findings_map = await llm_filter.filter_findings_batch(
                findings_map,
                valid_files_map,
                self.project_context
            )
        else:
            # Basic Filtering per file
            for path, findings in findings_map.items():
                code_file = valid_files_map[path]
                final_findings_map[path] = self._filter_findings(findings, code_file)

        # 3. Result Construction Phase
        for path, filtered_findings in final_findings_map.items():
            code_file = valid_files_map[path]

            # Convert to Frame Findings
            frame_findings = self._convert_to_findings(filtered_findings, code_file)
            status = self._determine_status(frame_findings)

            # Metadata construction (simplified for batch)
            metadata = {
                 "total_orphans": len(findings_map.get(path, [])),
                 "final_orphans": len(filtered_findings),
                 "batch_processed": True
            }

            results.append(FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status=status,
                duration=time.perf_counter() - start_time, # Total batch duration average? Or just total
                issues_found=len(frame_findings),
                is_blocker=False,
                findings=frame_findings,
                metadata=metadata
            ))

        # Calculate aggregate stats for CLI summary
        total_candidates = sum(len(f_list) for f_list in findings_map.values())
        final_count = sum(len(f_list) for f_list in final_findings_map.values())
        filtered_count = total_candidates - final_count

        # Build LLM filter summary for CLI display
        llm_filter = self._get_or_create_filter()
        llm_filter_summary = {
            "total_files_analyzed": len(valid_files_map),
            "ast_candidates_found": total_candidates,
            "llm_filtered_out": filtered_count,
            "final_findings": final_count,
            "used_llm_filter": self.use_llm_filter and llm_filter is not None,
            "reasoning": self._generate_filter_summary(
                total_candidates,
                final_count,
                len(valid_files_map),
                list(findings_map.keys())[:5]  # Sample files
            )
        }

        # Store for pipeline context access
        self.batch_summary = llm_filter_summary

        logger.info(
            "orphan_batch_completed",
            processed=len(results),
            duration=time.perf_counter() - start_time,
            ast_candidates=total_candidates,
            final_findings=final_count,
            llm_filtered=filtered_count
        )
        return results

    def _generate_filter_summary(
        self,
        candidates: int,
        final: int,
        file_count: int,
        sample_files: list[str]
    ) -> str:
        """Generate human-readable summary of LLM filtering decision."""
        if candidates == 0:
            return "No orphan candidates detected in codebase."

        filtered = candidates - final
        if final == 0 and candidates > 0:
            samples = ", ".join([f.split("/")[-1] for f in sample_files[:3]])
            return (
                f"{candidates} potential orphans from {file_count} files were analyzed. "
                f"All {filtered} were determined to be false positives (exported utilities, "
                f"type guards, or externally-consumed functions). "
                f"Sample files: {samples}"
            )
        elif final > 0:
            return (
                f"{candidates} candidates analyzed, {final} confirmed as true orphans. "
                f"{filtered} filtered as false positives."
            )
        else:
            return f"Analyzed {candidates} candidates from {file_count} files."

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        """
        Execute orphan code detection on code file.

        Args:
            code_file: Code file to validate

        Returns:
            FrameResult with orphan code findings
        """
        start_time = time.perf_counter()

        logger.info(
            "orphan_frame_started",
            file_path=code_file.path,
            language=code_file.language,
        )

        # Check if file is applicable
        if not self._is_applicable(code_file):
            logger.info(
                "orphan_frame_skipped",
                file_path=code_file.path,
                reason="Not a Python file",
            )
            return self._create_skipped_result(start_time)

        # Run orphan detection
        try:
            # STAGE 1: AST-based detection (fast, language-specific)
            # Check if LSP should be used from config
            use_lsp = self.config.get("use_lsp", False)
            project_root = getattr(self, 'project_root', None)

            detector = await OrphanDetectorFactory.create_detector(
                code_file.content,
                code_file.path,
                use_lsp=use_lsp,
                project_root=str(project_root) if project_root else None
            )

            if not detector:
                logger.info(
                    "orphan_frame_skipped",
                    file_path=code_file.path,
                    reason="Unsupported language for orphan detection",
                )
                return FrameResult(
                    frame_id=self.frame_id,
                    frame_name=self.name,
                    status="skipped",
                    duration=time.perf_counter() - start_time,
                    issues_found=0,
                    is_blocker=False,
                    findings=[],
                    metadata={"reason": "unsupported_language", "skipped": True}
                )

            # Call appropriate detection method (async for LSP, sync for others)
            from orphan_detector import LSPOrphanDetector
            if isinstance(detector, LSPOrphanDetector):
                orphan_findings = await detector.detect_all_async()
            else:
                orphan_findings = detector.detect_all()

            logger.debug(
                "ast_detection_complete",
                total_findings=len(orphan_findings),
                file=code_file.path,
            )

            # STAGE 2: Filter findings (basic OR intelligent)
            llm_filter = self._get_or_create_filter()
            if self.use_llm_filter and llm_filter and orphan_findings:
                # Intelligent filtering using LLM (recommended)
                logger.info(
                    "llm_filtering_started",
                    ast_findings=len(orphan_findings),
                    file=code_file.path,
                )

                llm_start = time.perf_counter()
                filtered_findings = await llm_filter.filter_findings(
                    findings=orphan_findings,
                    code_file=code_file,
                    language=code_file.language,
                )
                llm_duration = time.perf_counter() - llm_start

                false_positives_removed = len(orphan_findings) - len(filtered_findings)
                false_positive_rate = (
                    (false_positives_removed / len(orphan_findings) * 100)
                    if len(orphan_findings) > 0
                    else 0
                )

                logger.info(
                    "llm_filtering_complete",
                    ast_findings=len(orphan_findings),
                    llm_findings=len(filtered_findings),
                    false_positives_removed=false_positives_removed,
                    false_positive_rate=f"{false_positive_rate:.1f}%",
                    llm_duration=f"{llm_duration:.2f}s",
                )

                filtering_metadata = {
                    "filtering_mode": "llm",
                    "ast_findings": len(orphan_findings),
                    "llm_findings": len(filtered_findings),
                    "false_positives_removed": false_positives_removed,
                    "false_positive_rate": f"{false_positive_rate:.1f}%",
                    "llm_duration": f"{llm_duration:.2f}s",
                }

            else:
                # Basic filtering (fast, but may have false positives)
                filtered_findings = self._filter_findings(orphan_findings, code_file)

                logger.debug(
                    "basic_filtering_complete",
                    ast_findings=len(orphan_findings),
                    filtered_findings=len(filtered_findings),
                )

                filtering_metadata = {
                    "filtering_mode": "basic",
                    "ast_findings": len(orphan_findings),
                    "filtered_findings": len(filtered_findings),
                }

            # Convert to Frame findings
            findings = self._convert_to_findings(filtered_findings, code_file)

            # Determine status
            status = self._determine_status(findings)

            duration = time.perf_counter() - start_time

            logger.info(
                "orphan_frame_completed",
                file_path=code_file.path,
                status=status,
                total_findings=len(findings),
                duration=f"{duration:.2f}s",
            )

            # Build comprehensive metadata
            metadata = {
                **filtering_metadata,
                "total_orphans": len(orphan_findings),
                "final_orphans": len(filtered_findings),
                "unused_imports": sum(
                    1 for f in filtered_findings if f.orphan_type == "unused_import"
                ),
                "unreferenced_functions": sum(
                    1
                    for f in filtered_findings
                    if f.orphan_type == "unreferenced_function"
                ),
                "unreferenced_classes": sum(
                    1
                    for f in filtered_findings
                    if f.orphan_type == "unreferenced_class"
                ),
                "dead_code": sum(
                    1 for f in filtered_findings if f.orphan_type == "dead_code"
                ),
            }

            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status=status,
                duration=duration,
                issues_found=len(findings),
                is_blocker=False,  # Orphan code is never a blocker
                findings=findings,
                metadata=metadata,
            )

        except Exception as e:
            logger.error(
                "orphan_frame_error",
                file_path=code_file.path,
                error=str(e),
            )

            duration = time.perf_counter() - start_time
            return FrameResult(
                frame_id=self.frame_id,
                frame_name=self.name,
                status="failed",
                duration=duration,
                issues_found=0,
                is_blocker=False,
                findings=[],
                metadata={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

    def _is_applicable(self, code_file: CodeFile) -> bool:
        """
        Check if frame is applicable to code file.

        Args:
            code_file: Code file to check

        Returns:
            True if frame should run
        """
        # Check if we have a detector for this language (delegate to factory)

        # Get file extension
        import os
        _, ext = os.path.splitext(code_file.path)
        ext = ext.lower()

        # Supported extensions: Python (native) + Universal AST languages
        supported_extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".cs"}
        if self.ignore_test_files:
            if "test_" in code_file.path or "_test." in code_file.path or ".test." in code_file.path:
                logger.debug("orphan_skipped_test", file=code_file.path, ignored=True)
                return False

        if ext not in supported_extensions:
            logger.debug("orphan_skipped_ext", file=code_file.path, ext=ext, supported=supported_extensions)
            return False

        return True

    def _filter_findings(
        self, findings: list[OrphanFinding], code_file: CodeFile
    ) -> list[OrphanFinding]:
        """
        Filter findings based on configuration.

        Args:
            findings: Raw orphan findings
            code_file: Code file context

        Returns:
            Filtered findings
        """
        filtered: list[OrphanFinding] = []

        for finding in findings:
            # Filter ignored imports
            if finding.orphan_type == "unused_import" and finding.name in self.ignore_imports:
                continue

            # Filter private functions/classes if configured
            if self.ignore_private and finding.orphan_type in [
                "unreferenced_function",
                "unreferenced_class",
            ] and finding.name.startswith("_"):
                continue

            # Filter entry points
            if finding.name == "main":
                continue

            filtered.append(finding)

        return filtered

    def _convert_to_findings(
        self, orphan_findings: list[OrphanFinding], code_file: CodeFile
    ) -> list[Finding]:
        """
        Convert OrphanFinding objects to Frame Finding objects.

        Args:
            orphan_findings: List of orphan findings
            code_file: Code file context

        Returns:
            List of Frame Finding objects
        """
        findings: list[Finding] = []

        for i, orphan in enumerate(orphan_findings):
            # Determine severity based on orphan type
            severity = self._get_severity(orphan.orphan_type)

            # Create suggestion
            suggestion = self._get_suggestion(orphan.orphan_type)

            finding = Finding(
                id=f"{self.frame_id}-{orphan.orphan_type}-{i}",
                severity=severity,
                message=orphan.reason,
                location=f"{code_file.path}:{orphan.line_number}",
                detail=suggestion,
                code=orphan.code_snippet,
            )
            findings.append(finding)

        return findings

    def _get_severity(self, orphan_type: str) -> str:
        """
        Get severity for orphan type.

        Args:
            orphan_type: Type of orphan code

        Returns:
            Severity level ('low' | 'medium')
        """
        severity_map = {
            "unused_import": "low",  # Cleanup only
            "unreferenced_function": "medium",  # Potential maintenance issue
            "unreferenced_class": "medium",  # Potential maintenance issue
            "dead_code": "medium",  # Likely a bug
        }

        return severity_map.get(orphan_type, "low")

    def _get_suggestion(self, orphan_type: str) -> str:
        """
        Get suggestion for fixing orphan code.

        Args:
            orphan_type: Type of orphan code

        Returns:
            Suggestion text
        """
        suggestions = {
            "unused_import": (
                "Remove this unused import to keep the code clean.\n"
                "Unused imports increase file size and may cause confusion."
            ),
            "unreferenced_function": (
                "This function is never called in the codebase.\n"
                "Consider:\n"
                "1. Remove it if it's truly unused\n"
                "2. Export it if it's meant to be a public API\n"
                "3. Add tests if it's meant to be used"
            ),
            "unreferenced_class": (
                "This class is never instantiated in the codebase.\n"
                "Consider:\n"
                "1. Remove it if it's truly unused\n"
                "2. Export it if it's meant to be a public API\n"
                "3. Add tests if it's meant to be used"
            ),
            "dead_code": (
                "This code is unreachable and will never execute.\n"
                "Remove it or restructure the logic to make it reachable."
            ),
        }

        return suggestions.get(orphan_type, "Consider removing or refactoring this code.")

    def _determine_status(self, findings: list[Finding]) -> str:
        """
        Determine frame status based on findings.

        Args:
            findings: All findings from analysis

        Returns:
            Status: 'passed' | 'warning'
        """
        if not findings:
            return "passed"

        # Orphan code is always a warning, never a failure
        return "warning"

    def _create_skipped_result(self, start_time: float) -> FrameResult:
        """
        Create result for skipped execution.

        Args:
            start_time: Start time for duration calculation

        Returns:
            FrameResult indicating skip
        """
        duration = time.perf_counter() - start_time

        return FrameResult(
            frame_id=self.frame_id,
            frame_name=self.name,
            status="passed",
            duration=duration,
            issues_found=0,
            is_blocker=False,
            findings=[],
            metadata={
                "skipped": True,
                "reason": "Not applicable to this file type",
            },
        )

    def _get_or_create_filter(self) -> LLMOrphanFilter | None:
        """
        Get or lazy-create LLM filter using injected service.
        """
        if not self.use_llm_filter:
            return None

        if self.llm_filter:
            return self.llm_filter

        try:
            # Check for injected services from FrameExecutor
            llm_service = getattr(self, 'llm_service', None)
            semantic_search_service = getattr(self, 'semantic_search_service', None)

            self.llm_filter = LLMOrphanFilter(
                llm_service=llm_service,
                semantic_search_service=semantic_search_service
            )
            return self.llm_filter
        except Exception as e:
            logger.warning(
                "llm_orphan_filter_initialization_failed",
                error=str(e),
                fallback="basic filtering",
            )
            self.use_llm_filter = False
            return None
