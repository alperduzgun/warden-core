from warden.validation.domain.frame import (
    ValidationFrame,
    FrameResult,
    CodeFile,
)
from warden.validation.domain.enums import (
    FrameCategory,
    FramePriority,
    FrameScope,
    FrameApplicability,
)

class ChaosFrame(ValidationFrame):
    """A frame that deliberately crashes to test error isolation."""
    name = "Chaos Frame"
    description = "Test frame that raises an exception"
    category = FrameCategory.GLOBAL
    priority = FramePriority.LOW
    scope = FrameScope.FILE_LEVEL
    applicability = [FrameApplicability.ALL]

    async def execute_async(self, code_file: CodeFile) -> FrameResult:
        raise RuntimeError("Chaos and destruction! (This is a test of error isolation)")
