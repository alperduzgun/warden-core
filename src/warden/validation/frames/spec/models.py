"""
Warden Spec Domain Models.

Core entities for API contract extraction and comparison.

Contract Structure:
    contracts/
      └── invoice.warden.yaml       # Core contract (platform agnostic)

    bindings/
      ├── invoice.rest.yaml         # REST binding
      ├── invoice.graphql.yaml      # GraphQL binding
      └── invoice.grpc.yaml         # gRPC binding
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional


class PlatformType(str, Enum):
    """Supported platform types for contract extraction."""

    FLUTTER = "flutter"
    REACT = "react"
    REACT_NATIVE = "react-native"
    ANGULAR = "angular"
    VUE = "vue"
    SWIFT = "swift"
    KOTLIN = "kotlin"

    # Backend platforms
    SPRING = "spring"
    SPRING_BOOT = "spring-boot"
    NESTJS = "nestjs"
    EXPRESS = "express"
    FASTAPI = "fastapi"
    DJANGO = "django"
    DOTNET = "dotnet"
    ASP_NET_CORE = "aspnetcore"
    GO = "go"
    GIN = "gin"
    ECHO = "echo"


class PlatformRole(str, Enum):
    """Role of the platform in the contract."""

    CONSUMER = "consumer"  # Frontend/Mobile - expects API
    PROVIDER = "provider"  # Backend - provides API
    BOTH = "both"  # Acts as both (e.g., BFF)


class OperationType(str, Enum):
    """Type of operation in the contract."""

    QUERY = "query"  # Read operation (GET)
    COMMAND = "command"  # Write operation (POST, PUT, DELETE)
    SUBSCRIPTION = "subscription"  # Real-time subscription


class PrimitiveType(str, Enum):
    """Primitive types in the contract schema."""

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    DECIMAL = "decimal"
    BOOL = "bool"
    BYTES = "bytes"
    DATETIME = "datetime"
    DATE = "date"
    TIME = "time"


class GapSeverity(str, Enum):
    """Severity of contract gaps."""

    CRITICAL = "critical"  # Consumer expects, provider missing
    HIGH = "high"  # Type mismatch
    MEDIUM = "medium"  # Nullable mismatch
    LOW = "low"  # Unused operation


@dataclass
class FieldDefinition:
    """
    A field in a model or input/output type.

    Examples:
        - amount: decimal
        - language: string?  (optional)
        - items: LineItem[]  (array)
    """

    name: str
    type_name: str  # Primitive type or model reference
    is_optional: bool = False
    is_array: bool = False
    description: Optional[str] = None

    # Source tracking
    source_file: Optional[str] = None
    source_line: Optional[int] = None

    def to_yaml_repr(self) -> str:
        """Convert to YAML representation."""
        type_repr = self.type_name
        if self.is_array:
            type_repr = f"{type_repr}[]"
        if self.is_optional:
            type_repr = f"{type_repr}?"
        return f"{self.name}: {type_repr}"


@dataclass
class ModelDefinition:
    """
    A model (data transfer object) in the contract.

    Example:
        Invoice:
          - id: string
          - amount: decimal
          - status: InvoiceStatus
          - lineItems: LineItem[]
    """

    name: str
    fields: List[FieldDefinition] = field(default_factory=list)
    description: Optional[str] = None

    # Source tracking
    source_file: Optional[str] = None
    source_line: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        return {
            self.name: [f.to_yaml_repr() for f in self.fields]
        }


@dataclass
class EnumDefinition:
    """
    An enum in the contract.

    Example:
        InvoiceStatus: [draft, pending, paid, cancelled]
    """

    name: str
    values: List[str] = field(default_factory=list)
    description: Optional[str] = None

    # Source tracking
    source_file: Optional[str] = None
    source_line: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        return {
            self.name: self.values
        }


@dataclass
class OperationDefinition:
    """
    An operation (API endpoint) in the contract.

    Example:
        - operation: createVoiceInvoice
          type: command
          input: CreateVoiceInvoiceInput
          output: VoiceInvoiceResult
    """

    name: str
    operation_type: OperationType
    input_type: Optional[str] = None
    output_type: Optional[str] = None
    description: Optional[str] = None

    # Source tracking
    source_file: Optional[str] = None
    source_line: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result = {
            "operation": self.name,
            "type": self.operation_type.value,
        }
        if self.input_type:
            result["input"] = self.input_type
        if self.output_type:
            result["output"] = self.output_type
        return result


@dataclass
class Contract:
    """
    Core contract definition (platform agnostic).

    This is the central abstraction that both consumer and provider
    must agree upon.
    """

    name: str
    version: str = "1.0.0"
    operations: List[OperationDefinition] = field(default_factory=list)
    models: List[ModelDefinition] = field(default_factory=list)
    enums: List[EnumDefinition] = field(default_factory=list)

    # Metadata
    description: Optional[str] = None
    extracted_from: Optional[str] = None  # Platform name
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional metadata

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: Dict[str, Any] = {}

        if self.operations:
            result["contracts"] = [op.to_dict() for op in self.operations]

        if self.models:
            result["models"] = {}
            for model in self.models:
                result["models"].update(model.to_dict())

        if self.enums:
            result["enums"] = {}
            for enum in self.enums:
                result["enums"].update(enum.to_dict())

        return result

    def get_operation(self, name: str) -> Optional[OperationDefinition]:
        """Get operation by name."""
        for op in self.operations:
            if op.name == name:
                return op
        return None

    def get_model(self, name: str) -> Optional[ModelDefinition]:
        """Get model by name."""
        for model in self.models:
            if model.name == name:
                return model
        return None


@dataclass
class PlatformConfig:
    """
    Configuration for a platform in the spec analysis.

    Example in .warden/config.yaml:
        platforms:
          - name: mobile
            path: ../invoice-mobile
            type: flutter
            role: consumer
    """

    name: str
    path: str
    platform_type: PlatformType
    role: PlatformRole
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlatformConfig":
        """Create from dictionary."""
        return cls(
            name=data.get("name", ""),
            path=data.get("path", ""),
            platform_type=PlatformType(data.get("type", "unknown")),
            role=PlatformRole(data.get("role", "consumer")),
            description=data.get("description"),
        )


@dataclass
class ContractGap:
    """
    A gap between consumer and provider contracts.

    Represents a mismatch or missing element between what one
    platform expects and what another provides.
    """

    gap_type: str  # "missing_operation", "type_mismatch", "nullable_mismatch", "unused"
    severity: GapSeverity
    message: str
    detail: Optional[str] = None

    # Context
    consumer_platform: Optional[str] = None
    provider_platform: Optional[str] = None
    operation_name: Optional[str] = None
    field_name: Optional[str] = None

    # Source tracking
    consumer_file: Optional[str] = None
    consumer_line: Optional[int] = None
    provider_file: Optional[str] = None
    provider_line: Optional[int] = None

    def to_finding_dict(self) -> Dict[str, Any]:
        """Convert to Finding-compatible dictionary."""
        location = ""
        if self.consumer_file:
            location = self.consumer_file
            if self.consumer_line:
                location += f":{self.consumer_line}"

        return {
            "severity": self.severity.value,
            "message": self.message,
            "location": location,
            "detail": self.detail,
            "gap_type": self.gap_type,
            "consumer_platform": self.consumer_platform,
            "provider_platform": self.provider_platform,
        }


@dataclass
class SpecAnalysisResult:
    """
    Result of spec analysis between platforms.
    """

    consumer_contract: Contract
    provider_contract: Contract
    gaps: List[ContractGap] = field(default_factory=list)

    # Statistics
    total_consumer_operations: int = 0
    total_provider_operations: int = 0
    matched_operations: int = 0
    missing_operations: int = 0
    unused_operations: int = 0
    type_mismatches: int = 0

    def has_critical_gaps(self) -> bool:
        """Check if there are critical gaps."""
        return any(g.severity == GapSeverity.CRITICAL for g in self.gaps)

    def summary(self) -> str:
        """Generate summary text."""
        lines = [
            f"Consumer: {self.consumer_contract.name} ({self.total_consumer_operations} operations)",
            f"Provider: {self.provider_contract.name} ({self.total_provider_operations} operations)",
            f"Matched: {self.matched_operations}",
            f"Missing: {self.missing_operations}",
            f"Unused: {self.unused_operations}",
            f"Type Mismatches: {self.type_mismatches}",
            f"Total Gaps: {len(self.gaps)}",
        ]
        return "\n".join(lines)
