"""
Optional capability mixins for ValidationFrame.

These mixins provide optional functionality that frames can opt into
by inheriting from them, reducing the surface area of the base ValidationFrame class.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, List

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
    async def execute_batch_async(
        self,
        code_files: list["CodeFile"],
        context: Any = None
    ) -> list["FrameResult"]:
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
