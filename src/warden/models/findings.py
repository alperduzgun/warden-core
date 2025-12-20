"""
Finding, Fortification, and Cleaning models for Panel compatibility.

These models represent pipeline execution outputs:
- Finding: Issues/vulnerabilities discovered
- Fortification: Applied fixes and improvements
- Cleaning: Code quality improvements

Panel JSON format: camelCase
Python internal format: snake_case
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, Literal

from warden.shared.domain.base_model import BaseDomainModel


# Type aliases for Panel compatibility
FindingSeverity = Literal['critical', 'high', 'medium', 'low']


@dataclass
class Finding(BaseDomainModel):
    """
    Issue or vulnerability discovered during validation.

    Panel TypeScript equivalent:
    ```typescript
    export interface Finding {
      id: string
      severity: 'critical' | 'high' | 'medium' | 'low'
      message: string
      location: string  // "file.py:45"
      detail?: string
      code?: string
    }
    ```

    Displayed in the "Findings" tab of the Pipeline UI.
    """

    id: str
    severity: FindingSeverity
    message: str
    location: str  # e.g., "user_service.py:45"
    detail: Optional[str] = None
    code: Optional[str] = None  # Code snippet showing the issue

    def __post_init__(self) -> None:
        """Validate severity."""
        valid_severities = ('critical', 'high', 'medium', 'low')
        if self.severity not in valid_severities:
            raise ValueError(f"Invalid severity: {self.severity}. Must be one of {valid_severities}")


@dataclass
class Fortification(BaseDomainModel):
    """
    Applied fix or improvement to code.

    Panel TypeScript equivalent:
    ```typescript
    export interface Fortification {
      id: string
      title: string
      detail: string  // HTML allowed
    }
    ```

    Displayed in the "Fortifications" tab of the Pipeline UI.
    Examples:
    - "Added null check for user_id parameter"
    - "Implemented retry mechanism with exponential backoff"
    - "Added input sanitization for SQL query"
    """

    id: str
    title: str
    detail: str  # HTML allowed for formatting


@dataclass
class Cleaning(BaseDomainModel):
    """
    Code quality improvement applied.

    Panel TypeScript equivalent:
    ```typescript
    export interface Cleaning {
      id: string
      title: string
      detail: string  // HTML allowed
    }
    ```

    Displayed in the "Cleanings" tab of the Pipeline UI.
    Examples:
    - "Renamed variable 'x' to 'user_id' for clarity"
    - "Extracted duplicate code into reusable function"
    - "Removed unused imports"
    """

    id: str
    title: str
    detail: str  # HTML allowed for formatting
