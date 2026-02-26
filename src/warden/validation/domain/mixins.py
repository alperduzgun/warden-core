"""
Optional capability mixins for ValidationFrame.

These mixins provide optional functionality that frames can opt into
by inheriting from them, reducing the surface area of the base ValidationFrame class.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from warden.validation.domain.frame import CodeFile, FrameResult


class BatchExecutable(ABC):
    """
    Mixin for frames that need custom batch execution logic.

    Frames implementing this mixin can override the default batch execution
    strategy for performance optimization or custom processing logic.

    Example:
        class MyFrame(ValidationFrame, BatchExecutable):
            async def execute_batch_async(self, code_files, context=None):
                # Custom batch logic here
                pass
    """

    @abstractmethod
    async def execute_batch_async(self, code_files: list["CodeFile"], context: Any = None) -> list["FrameResult"]:
        """
        Execute validation on multiple files in batch.

        Args:
            code_files: List of code files to validate
            context: Optional execution context

        Returns:
            List of FrameResult objects
        """
        raise NotImplementedError


class ProjectContextAware(ABC):
    """
    Mixin for frames that need project-level context information.

    Frames implementing this mixin can receive and use project context
    for context-aware validation (e.g., service abstractions, architecture patterns).

    Example:
        class MyFrame(ValidationFrame, ProjectContextAware):
            def set_project_context(self, context):
                self.project_context = context
                # Use context for validation
    """

    @abstractmethod
    def set_project_context(self, context: Any) -> None:
        """
        Inject project context for context-aware checks.

        Args:
            context: ProjectContext object with architecture info
        """
        raise NotImplementedError


class Cleanable(ABC):
    """
    Mixin for frames that need resource cleanup after execution.

    Frames implementing this mixin can release large objects, close connections,
    or perform other cleanup operations after validation.

    Example:
        class MyFrame(ValidationFrame, Cleanable):
            async def cleanup(self):
                # Release AST nodes, close connections, etc.
                self.large_data = None
    """

    @abstractmethod
    async def cleanup(self) -> None:
        """
        Release resources and perform cleanup after frame execution.

        This is called automatically by the frame executor after batch execution.
        Subclasses should override this to nullify large objects, close connections, etc.
        """
        raise NotImplementedError


class LSPAware(ABC):
    """
    Mixin for frames that consume LSP-based semantic analysis results.

    Frames implementing this mixin receive call chains, type hierarchies,
    and dead symbol data from the ``LSPAuditService``.  The pipeline's
    ``FrameRunner`` calls ``set_lsp_context`` before frame execution.

    Example:
        class MyFrame(ValidationFrame, LSPAware):
            def set_lsp_context(self, lsp_context):
                self._lsp_context = lsp_context
    """

    @abstractmethod
    def set_lsp_context(self, lsp_context: dict[str, Any]) -> None:
        """
        Inject LSP audit context for semantic analysis.

        Args:
            lsp_context: Dict with keys like 'call_chains', 'type_hierarchy',
                         'dead_symbols', 'chain_validation'.
        """
        raise NotImplementedError


class TaintAware(ABC):
    """
    Mixin for frames that consume pre-computed taint analysis results.

    Frames implementing this mixin receive taint paths (source-to-sink flows)
    from the shared ``TaintAnalysisService``.  The pipeline's ``FrameRunner``
    calls ``set_taint_paths`` before frame execution.

    Example:
        class MyFrame(ValidationFrame, TaintAware):
            def set_taint_paths(self, taint_paths):
                self._taint_paths = taint_paths
    """

    @abstractmethod
    def set_taint_paths(self, taint_paths: dict[str, list[Any]]) -> None:
        """
        Inject pre-computed taint paths for all files.

        Args:
            taint_paths: Mapping of file_path to list of TaintPath objects.
        """
        raise NotImplementedError


class DataFlowAware(ABC):
    """
    Mixin for frames that consume Data Dependency Graph information.

    Frames implementing this mixin receive the project-wide DDG
    populated during PRE-ANALYSIS phase (contract_mode=True).
    The pipeline's ``FrameRunner`` calls ``set_data_dependency_graph``
    before frame execution.

    Usage:
        class DeadDataFrame(ValidationFrame, DataFlowAware):
            def set_data_dependency_graph(self, ddg):
                self._ddg = ddg
    """

    @abstractmethod
    def set_data_dependency_graph(self, ddg: Any) -> None:
        """
        Inject the DataDependencyGraph into this frame.

        Args:
            ddg: DataDependencyGraph instance with writes, reads, and
                 init_fields populated by DataDependencyService.
        """
        raise NotImplementedError


class CodeGraphAware(ABC):
    """
    Mixin for frames that consume CodeGraph and GapReport data.

    Frames implementing this mixin receive the pre-computed CodeGraph
    (module dependency graph) and its associated GapReport (coverage gaps,
    broken imports, circular dependencies) from Phase 0.7 (PRE-ANALYSIS).
    The pipeline's ``FrameRunner`` calls ``set_code_graph`` before frame
    execution.

    Example:
        class MyFrame(ValidationFrame, CodeGraphAware):
            def set_code_graph(self, code_graph, gap_report):
                self._code_graph = code_graph
                self._gap_report = gap_report
    """

    @abstractmethod
    def set_code_graph(self, code_graph: Any, gap_report: Any) -> None:
        """
        Inject CodeGraph and GapReport for structural analysis.

        Args:
            code_graph: CodeGraph instance with module nodes and edges
                        representing the project's import/dependency structure.
            gap_report: GapReport instance with coverage metrics, broken
                        imports, circular dependencies, and orphan files.
        """
        raise NotImplementedError
