"""Input validation for CLI/Bridge (ID 14)."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CodeFileInput(BaseModel):
    """Validated code file input."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., min_length=1, max_length=1024)
    content: str = Field(..., max_length=10_000_000)
    language: str | None = Field(default=None, max_length=64)

    @field_validator("path")
    @classmethod
    def validate_path(cls, v):
        if "\x00" in v:
            raise ValueError("Path must not contain null bytes")
        if ".." in v or v.startswith("/"):
            raise ValueError("Invalid path")
        return v


class FrameExecutionInput(BaseModel):
    """Validated frame execution request."""

    model_config = ConfigDict(extra="forbid")

    frame_ids: list[Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")]] = Field(..., min_length=1, max_length=100)
    analysis_level: str | None = Field(default="standard", pattern="^(basic|standard|deep)$")


class PipelineInput(BaseModel):
    """Validated pipeline configuration."""

    model_config = ConfigDict(extra="forbid")

    max_files: int = Field(default=1000, ge=1, le=10000)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    enable_fortification: bool = True
