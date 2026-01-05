"""
Pipeline Context Model.

Shared context that flows through all pipeline phases.
Each phase reads from and writes to this context.

Thread-safe and memory-bounded implementation for production use.
"""

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from warden.analysis.domain.file_context import FileContext
from warden.analysis.domain.project_context import Framework, ProjectType
from warden.analysis.domain.quality_metrics import QualityMetrics


@dataclass
class PipelineContext:
    """
    Shared context for all pipeline phases.

    This context accumulates information as it flows through:
    0. PRE-ANALYSIS → Project/File understanding
    1. ANALYSIS → Quality metrics
    2. CLASSIFICATION → Frame selection & suppressions
    3. VALIDATION → Findings & issues
    4. FORTIFICATION → Security fixes
    5. CLEANING → Quality improvements

    Features:
    - Thread-safe operations with locks
    - Memory-bounded collections (FIFO eviction)
    - Configurable size limits
    """

    # Basic Information
    pipeline_id: str
    started_at: datetime
    file_path: Path
    source_code: str
    project_root: Optional[Path] = None  # NEW: Root directory of the project
    use_gitignore: bool = True  # NEW: Respect .gitignore patterns
    language: str = "python"

    # Memory limits (class variables)
    MAX_LLM_HISTORY: int = field(default=100, init=False)
    MAX_FINDINGS: int = field(default=1000, init=False)
    MAX_LIST_SIZE: int = field(default=500, init=False)

    # Thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    # Phase 0: PRE-ANALYSIS Results
    project_type: Optional[ProjectType] = None
    framework: Optional[Framework] = None
    file_context: Optional[FileContext] = None
    file_contexts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    project_metadata: Dict[str, Any] = field(default_factory=dict)

    # Phase 1: ANALYSIS Results
    quality_metrics: Optional[QualityMetrics] = None
    quality_score_before: float = 0.0
    quality_confidence: float = 0.0
    hotspots: List[Dict[str, Any]] = field(default_factory=list)
    quick_wins: List[Dict[str, Any]] = field(default_factory=list)
    technical_debt_hours: float = 0.0

    # Phase 2: CLASSIFICATION Results
    selected_frames: List[str] = field(default_factory=list)
    suppression_rules: List[Dict[str, Any]] = field(default_factory=list)
    frame_priorities: Dict[str, str] = field(default_factory=dict)
    classification_reasoning: str = ""
    learned_patterns: List[Dict[str, Any]] = field(default_factory=list)

    # Phase 3: VALIDATION Results
    findings: List[Dict[str, Any]] = field(default_factory=list)
    validated_issues: List[Dict[str, Any]] = field(default_factory=list)
    false_positives: List[str] = field(default_factory=list)
    true_positives: List[str] = field(default_factory=list)
    frame_results: Dict[str, Any] = field(default_factory=dict)

    # Phase 4: FORTIFICATION Results
    fortifications: List[Dict[str, Any]] = field(default_factory=list)
    applied_fixes: List[Dict[str, Any]] = field(default_factory=list)
    security_improvements: Dict[str, Any] = field(default_factory=dict)

    # Phase 5: CLEANING Results
    cleaning_suggestions: List[Dict[str, Any]] = field(default_factory=list)
    refactorings: List[Dict[str, Any]] = field(default_factory=list)
    quality_score_after: float = 0.0
    code_improvements: Dict[str, Any] = field(default_factory=dict)

    # LLM Context (accumulated prompts and responses)
    llm_history: List[Dict[str, Any]] = field(default_factory=list)

    # Artifacts
    artifacts: List[Dict[str, Any]] = field(default_factory=list)

    # LLM Usage Statistics
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Cross-Phases Cache (New)
    # Stores parsed ASTs to avoid re-parsing in multiple phases (DRY)
    ast_cache: Dict[str, Any] = field(default_factory=dict)

    def add_phase_result(self, phase: str, result: Dict[str, Any]) -> None:
        """
        Add results from a phase execution (thread-safe).

        Args:
            phase: Phase name (PRE_ANALYSIS, ANALYSIS, etc.)
            result: Phase execution results
        """
        with self._lock:
            phase_key = f"phase_{phase.lower()}_result"
            self.metadata[phase_key] = result
            self.metadata[f"{phase_key}_timestamp"] = datetime.now().isoformat()

    def add_llm_interaction(
        self,
        phase: str,
        prompt: str,
        response: str,
        confidence: float = 0.0,
        usage: Optional[Dict[str, int]] = None,
    ) -> None:
        """
        Record LLM interaction for audit trail (thread-safe, memory-bounded).

        Args:
            phase: Phase where LLM was used
            prompt: Prompt sent to LLM
            response: LLM response
            confidence: Confidence in response
            usage: Token usage statistics
        """
        with self._lock:
            # Memory-bounded: Remove oldest if at limit
            if len(self.llm_history) >= self.MAX_LLM_HISTORY:
                self.llm_history.pop(0)  # FIFO eviction

            # Aggregate token usage if provided
            if usage:
                self.total_tokens += usage.get("total_tokens", 0)
                self.prompt_tokens += usage.get("prompt_tokens", 0)
                self.completion_tokens += usage.get("completion_tokens", 0)

            self.llm_history.append({
                "phase": phase,
                "timestamp": datetime.now().isoformat(),
                "prompt": prompt[:500],  # Truncate for storage
                "response": response[:500],  # Truncate for storage
                "confidence": confidence,
                "usage": usage or {},
            })

    def _add_to_bounded_list(self, target_list: List, item: Any, max_size: int = None) -> None:
        """
        Add item to list with memory bounds (internal helper).

        Args:
            target_list: List to append to
            item: Item to add
            max_size: Maximum list size (uses MAX_LIST_SIZE if not specified)
        """
        max_size = max_size or self.MAX_LIST_SIZE
        with self._lock:
            if len(target_list) >= max_size:
                target_list.pop(0)  # FIFO eviction
            target_list.append(item)

    def get_context_for_phase(self, phase: str) -> Dict[str, Any]:
        """
        Get relevant context for a specific phase.

        Each phase gets cumulative context from all previous phases.

        Args:
            phase: Phase name requesting context

        Returns:
            Relevant context dictionary
        """
        context = {
            "pipeline_id": self.pipeline_id,
            "file_path": str(self.file_path),
            "project_root": str(self.project_root) if self.project_root else None,
            "use_gitignore": self.use_gitignore,
            "source_code": self.source_code,
            "language": self.language,
        }

        # PRE-ANALYSIS gets basic context
        if phase == "PRE_ANALYSIS":
            return context

        # ANALYSIS gets PRE-ANALYSIS results
        if phase in ["ANALYSIS", "CLASSIFICATION", "VALIDATION", "FORTIFICATION", "CLEANING"]:
            # Check if project_type is a ProjectContext object or an enum
            if hasattr(self.project_type, 'project_type'):
                # It's a ProjectContext object
                project_type_value = self.project_type.project_type.value if self.project_type.project_type else None
                framework_value = self.project_type.framework.value if self.project_type.framework else None
            else:
                # It's already an enum
                project_type_value = self.project_type.value if self.project_type else None
                framework_value = self.framework.value if self.framework else None

            context.update({
                "project_type": project_type_value,
                "framework": framework_value,
                "file_context": self.file_context.value if self.file_context else None,
                "file_contexts": self.file_contexts,
                "project_metadata": self.project_metadata,
            })

        # CLASSIFICATION gets ANALYSIS results too
        if phase in ["CLASSIFICATION", "VALIDATION", "FORTIFICATION", "CLEANING"]:
            context.update({
                "quality_metrics": self.quality_metrics.to_json() if self.quality_metrics else None,
                "quality_score": self.quality_score_before,
                "quality_score_before": self.quality_score_before,
                "quality_confidence": self.quality_confidence,
                "hotspots": self.hotspots,
                "quick_wins": self.quick_wins,
                "technical_debt_hours": self.technical_debt_hours,
            })

        # VALIDATION gets CLASSIFICATION results too
        if phase in ["VALIDATION", "FORTIFICATION", "CLEANING"]:
            context.update({
                "selected_frames": self.selected_frames,
                "suppression_rules": self.suppression_rules,
                "frame_priorities": self.frame_priorities,
                "classification_reasoning": self.classification_reasoning,
                "learned_patterns": self.learned_patterns,
            })

        # FORTIFICATION gets VALIDATION results too
        if phase in ["FORTIFICATION", "CLEANING"]:
            context.update({
                "findings": self.findings,
                "validated_issues": self.validated_issues,
                "false_positives": self.false_positives,
                "true_positives": self.true_positives,
                "frame_results": self.frame_results,
            })

        # CLEANING gets FORTIFICATION results too
        if phase == "CLEANING":
            context.update({
                "fortifications": self.fortifications,
                "applied_fixes": self.applied_fixes,
                "security_improvements": self.security_improvements,
            })

        # Add LLM history for context continuity
        context["previous_llm_interactions"] = [
            h for h in self.llm_history if h["phase"] != phase
        ][-5:]  # Last 5 interactions from other phases

        return context

    def get_llm_context_prompt(self, phase: str) -> str:
        """
        Generate a context summary prompt for LLM.

        Args:
            phase: Current phase

        Returns:
            Context summary for LLM prompt
        """
        context_parts = []

        # Add project context
        if self.project_type:
            # Check if project_type is a ProjectContext object or an enum
            if hasattr(self.project_type, 'project_type'):
                pt = self.project_type.project_type.value if self.project_type.project_type else "unknown"
                fw = self.project_type.framework.value if self.project_type.framework else "unknown"
            else:
                pt = self.project_type.value if self.project_type else "unknown"
                fw = self.framework.value if self.framework else "unknown"
            context_parts.append(
                f"PROJECT: {pt} application using {fw}"
            )

        # Add file context
        if self.file_context:
            context_parts.append(
                f"FILE TYPE: {self.file_context.value} ({self.language})"
            )

        # Add quality context
        if self.quality_score_before > 0:
            context_parts.append(
                f"QUALITY SCORE: {self.quality_score_before:.1f}/10"
            )

        # Add issues context
        if self.findings:
            severity_counts = {}
            for finding in self.findings:
                sev = finding.get("severity", "unknown")
                severity_counts[sev] = severity_counts.get(sev, 0) + 1
            context_parts.append(
                f"ISSUES FOUND: {severity_counts}"
            )

        # Add frame selection
        if self.selected_frames:
            context_parts.append(
                f"VALIDATION FRAMES: {', '.join(self.selected_frames)}"
            )

        # Add fixes applied
        if self.fortifications:
            context_parts.append(
                f"FIXES GENERATED: {len(self.fortifications)}"
            )

        # Add phase-specific context
        phase_summaries = {
            "ANALYSIS": "Now analyzing code quality...",
            "CLASSIFICATION": "Now selecting validation frames...",
            "VALIDATION": "Now running security validation...",
            "FORTIFICATION": "Now generating security fixes...",
            "CLEANING": "Now suggesting quality improvements...",
        }

        if phase in phase_summaries:
            context_parts.append(phase_summaries[phase])

        return "\n".join(context_parts)

    def to_json(self) -> Dict[str, Any]:
        """Convert context to JSON for serialization."""
        # Determine project type and framework values
        if hasattr(self.project_type, 'project_type'):
            project_type_value = self.project_type.project_type.value if self.project_type.project_type else None
            framework_value = self.project_type.framework.value if self.project_type.framework else None
        else:
            project_type_value = self.project_type.value if self.project_type else None
            framework_value = self.framework.value if self.framework else None

        return {
            "pipeline_id": self.pipeline_id,
            "started_at": self.started_at.isoformat(),
            "file_path": str(self.file_path),
            "language": self.language,
            "project_type": project_type_value,
            "framework": framework_value,
            "file_context": self.file_context.value if self.file_context else None,
            "quality_score_before": self.quality_score_before,
            "quality_score_after": self.quality_score_after,
            "findings_count": len(self.findings),
            "fortifications_count": len(self.fortifications),
            "cleaning_suggestions_count": len(self.cleaning_suggestions),
            "llm_interactions": len(self.llm_history),
            "metadata": self.metadata,
        }

    def get_summary(self) -> str:
        """Get human-readable summary of pipeline execution."""
        summary_parts = [
            f"Pipeline {self.pipeline_id} Summary:",
            f"File: {self.file_path}",
        ]

        if self.project_type:
            # Check if project_type is a ProjectContext object or an enum
            if hasattr(self.project_type, 'project_type'):
                pt = self.project_type.project_type.value if self.project_type.project_type else "unknown"
                fw = self.project_type.framework.value if self.project_type.framework else "unknown"
            else:
                pt = self.project_type.value if self.project_type else "unknown"
                fw = self.framework.value if self.framework else "unknown"
            summary_parts.append(
                f"Project: {pt} / {fw}"
            )

        if self.file_context:
            summary_parts.append(f"File Type: {self.file_context.value}")

        if self.quality_score_before > 0:
            summary_parts.append(
                f"Quality: {self.quality_score_before:.1f} → {self.quality_score_after:.1f}"
            )

        if self.findings:
            summary_parts.append(f"Issues Found: {len(self.findings)}")

        if self.fortifications:
            summary_parts.append(f"Fixes Generated: {len(self.fortifications)}")

        if self.cleaning_suggestions:
            summary_parts.append(
                f"Improvements Suggested: {len(self.cleaning_suggestions)}"
            )

        return "\n".join(summary_parts)