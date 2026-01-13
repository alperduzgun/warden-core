"""
Base domain model using Pydantic.

Provides Panel JSON compatibility via Pydantic aliasing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Type, TypeVar
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

T = TypeVar("T", bound="BaseDomainModel")


class BaseDomainModel(BaseModel):
    """
    Base class for all domain models using Pydantic.
    
    Provides Panel JSON compatibility:
    - Automatically converts snake_case fields to camelCase for API/JSON
    - Allows initialization with either snake_case or camelCase
    """
    
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        json_encoders={
            datetime: lambda v: v.isoformat()
        }
    )

    def to_json(self) -> Dict[str, Any]:
        """
        Serialize to Panel-compatible JSON (camelCase).
        
        Backward compatibility wrapper for model_dump().
        """
        return self.model_dump(by_alias=True, mode='json')

    def to_dict(self) -> Dict[str, Any]:
        """Alias for to_json."""
        return self.to_json()

    @classmethod
    def from_json(cls: Type[T], data: Dict[str, Any]) -> T:
        """
        Deserialize from Panel JSON (camelCase).
        
        Backward compatibility wrapper for model_validate().
        """
        return cls.model_validate(data)

    @classmethod
    def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
        """Alias for from_json."""
        return cls.from_json(data)
