"""Input validation for CLI/Bridge (ID 14)."""
from pydantic import BaseModel, Field, validator
from typing import Optional, List


class CodeFileInput(BaseModel):
    """Validated code file input."""
    path: str = Field(..., min_length=1, max_length=1024)
    content: str = Field(..., max_length=10_000_000)
    language: Optional[str] = None

    @validator('path')
    def validate_path(cls, v):
        if '..' in v or v.startswith('/'):
            raise ValueError('Invalid path')
        return v


class FrameExecutionInput(BaseModel):
    """Validated frame execution request."""
    frame_ids: List[str] = Field(..., min_length=1, max_length=100)
    analysis_level: Optional[str] = Field(default="standard", pattern="^(basic|standard|advanced)$")


class PipelineInput(BaseModel):
    """Validated pipeline configuration."""
    max_files: int = Field(default=1000, ge=1, le=10000)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    enable_fortification: bool = True
