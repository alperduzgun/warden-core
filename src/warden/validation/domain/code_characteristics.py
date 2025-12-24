"""
Code characteristics model.

Detected characteristics of code that influence validation strategy.
Used by classifier to determine which validation frames to run.
"""

from typing import List
from dataclasses import dataclass, field


@dataclass
class CodeCharacteristics:
    """
    Detected characteristics of code that influence validation strategy.

    This model is used by the code classifier to determine which validation
    frames should be executed based on the detected patterns in the code.
    """

    # Async/concurrency patterns
    has_async_operations: bool = False

    # External integrations
    has_external_api_calls: bool = False
    has_network_operations: bool = False

    # Data handling
    has_user_input: bool = False
    has_database_operations: bool = False
    has_file_operations: bool = False
    has_collection_processing: bool = False

    # Security-sensitive operations
    has_financial_calculations: bool = False
    has_authentication_logic: bool = False
    has_cryptographic_operations: bool = False

    # Code complexity
    complexity_score: int = 0  # 1-10 scale

    # Additional characteristics detected by LLM or static analysis
    additional_characteristics: List[str] = field(default_factory=list)

    @property
    def is_high_risk(self) -> bool:
        """
        Determine if code is high-risk based on characteristics.

        Returns:
            True if code has high-risk patterns (auth, crypto, finance, user input)
        """
        return (
            self.has_authentication_logic or
            self.has_cryptographic_operations or
            self.has_financial_calculations or
            (self.has_user_input and self.has_database_operations)
        )

    @property
    def requires_security_frame(self) -> bool:
        """
        Determine if security validation frame should run.

        Returns:
            True if code has security-sensitive patterns
        """
        return (
            self.has_user_input or
            self.has_authentication_logic or
            self.has_cryptographic_operations or
            self.has_database_operations
        )

    @property
    def requires_chaos_testing(self) -> bool:
        """
        Determine if chaos engineering validation should run.

        Returns:
            True if code has async/network operations that benefit from chaos testing
        """
        return (
            self.has_async_operations or
            self.has_external_api_calls or
            self.has_network_operations
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "has_async_operations": self.has_async_operations,
            "has_external_api_calls": self.has_external_api_calls,
            "has_network_operations": self.has_network_operations,
            "has_user_input": self.has_user_input,
            "has_database_operations": self.has_database_operations,
            "has_file_operations": self.has_file_operations,
            "has_collection_processing": self.has_collection_processing,
            "has_financial_calculations": self.has_financial_calculations,
            "has_authentication_logic": self.has_authentication_logic,
            "has_cryptographic_operations": self.has_cryptographic_operations,
            "complexity_score": self.complexity_score,
            "additional_characteristics": self.additional_characteristics,
            "is_high_risk": self.is_high_risk,
            "requires_security_frame": self.requires_security_frame,
            "requires_chaos_testing": self.requires_chaos_testing,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CodeCharacteristics":
        """Create from dictionary."""
        return cls(
            has_async_operations=data.get("has_async_operations", False),
            has_external_api_calls=data.get("has_external_api_calls", False),
            has_network_operations=data.get("has_network_operations", False),
            has_user_input=data.get("has_user_input", False),
            has_database_operations=data.get("has_database_operations", False),
            has_file_operations=data.get("has_file_operations", False),
            has_collection_processing=data.get("has_collection_processing", False),
            has_financial_calculations=data.get("has_financial_calculations", False),
            has_authentication_logic=data.get("has_authentication_logic", False),
            has_cryptographic_operations=data.get("has_cryptographic_operations", False),
            complexity_score=data.get("complexity_score", 0),
            additional_characteristics=data.get("additional_characteristics", []),
        )

    @classmethod
    def empty(cls) -> "CodeCharacteristics":
        """Create empty characteristics (no patterns detected)."""
        return cls()
