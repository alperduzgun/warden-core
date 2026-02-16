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
from typing import Any


class PlatformType(str, Enum):
    """Supported platform types for contract extraction."""

    # Universal (language/framework agnostic)
    UNIVERSAL = "universal"  # AI-powered extraction for any language/SDK
    MODULAR = "modular"  # Pre-generated modular contracts from .warden/contracts/modules/

    # Mobile/Frontend platforms
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
    EVENT = "event"  # Real-time events (WebSocket, SSE, Firebase listeners)
    SUBSCRIPTION = "subscription"  # GraphQL subscriptions


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
    description: str | None = None

    # Source tracking
    source_file: str | None = None
    source_line: int | None = None

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
    fields: list[FieldDefinition] = field(default_factory=list)
    description: str | None = None

    # Source tracking
    source_file: str | None = None
    source_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        return {self.name: [f.to_yaml_repr() for f in self.fields]}


@dataclass
class EnumDefinition:
    """
    An enum in the contract.

    Example:
        InvoiceStatus: [draft, pending, paid, cancelled]
    """

    name: str
    values: list[str] = field(default_factory=list)
    description: str | None = None

    # Source tracking
    source_file: str | None = None
    source_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        return {self.name: self.values}


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
    input_type: str | None = None
    output_type: str | None = None
    description: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Source tracking
    source_file: str | None = None
    source_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        # Custom format requested by user
        # endpoint: METHOD PATH
        # request: [fields]
        # response: [fields]
        if self.metadata and "endpoint" in self.metadata:
            result = {}

            # Construct endpoint string
            method = self.metadata.get("http_method", "GET")
            path = self.metadata.get("endpoint", "/")
            result["endpoint"] = f"{method} {path}"

            # Request/Response fields
            if "request_fields" in self.metadata:
                result["request"] = self.metadata["request_fields"]
            elif self.input_type:
                result["request"] = [f"body: {self.input_type}"]

            if "response_fields" in self.metadata:
                result["response"] = self.metadata["response_fields"]
            elif self.output_type:
                result["response"] = [f"body: {self.output_type}"]

            # Include source_file for modularization support
            if self.source_file:
                result["source_file"] = self.source_file

            return result

        # Fallback to standard format
        result = {
            "operation": self.name,
            "type": self.operation_type.value,
        }
        if self.input_type:
            result["input"] = self.input_type
        if self.output_type:
            result["output"] = self.output_type
        if self.description:
            result["description"] = self.description
        if self.metadata:
            result.update(self.metadata)
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
    operations: list[OperationDefinition] = field(default_factory=list)
    models: list[ModelDefinition] = field(default_factory=list)
    enums: list[EnumDefinition] = field(default_factory=list)

    # Metadata
    description: str | None = None
    extracted_from: str | None = None  # Platform name
    metadata: dict[str, Any] = field(default_factory=dict)  # Additional metadata

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        result: dict[str, Any] = {}

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

    def get_operation(self, name: str) -> OperationDefinition | None:
        """Get operation by name."""
        for op in self.operations:
            if op.name == name:
                return op
        return None

    def get_model(self, name: str) -> ModelDefinition | None:
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
    description: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlatformConfig":
        """
        Create from dictionary with comprehensive validation.

        Validates:
        - Required fields: name, path, type, role
        - platform_type is in PlatformType enum
        - role is in PlatformRole enum

        Args:
            data: Dictionary containing platform configuration

        Returns:
            PlatformConfig instance

        Raises:
            ValueError: If required fields are missing or invalid enum values
        """
        # Validate required fields
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("Platform 'name' is required. Example: name: 'mobile'")

        path = data.get("path", "").strip()
        if not path:
            raise ValueError(f"Platform 'path' is required for platform '{name}'. Example: path: '../my-app'")

        platform_type_str = data.get("type", "").strip()
        if not platform_type_str:
            raise ValueError(
                f"Platform 'type' is required for platform '{name}'. "
                f"Valid options: {', '.join([t.value for t in PlatformType])}"
            )

        role_str = data.get("role", "").strip()
        if not role_str:
            raise ValueError(
                f"Platform 'role' is required for platform '{name}'. "
                f"Valid options: {', '.join([r.value for r in PlatformRole])}"
            )

        # Validate platform_type is valid enum
        try:
            platform_type = PlatformType(platform_type_str)
        except ValueError:
            valid_types = ", ".join([t.value for t in PlatformType])
            raise ValueError(
                f"Invalid platform type '{platform_type_str}' for platform '{name}'. Valid options: {valid_types}"
            )

        # Validate role is valid enum
        try:
            role = PlatformRole(role_str)
        except ValueError:
            valid_roles = ", ".join([r.value for r in PlatformRole])
            raise ValueError(f"Invalid platform role '{role_str}' for platform '{name}'. Valid options: {valid_roles}")

        return cls(
            name=name,
            path=path,
            platform_type=platform_type,
            role=role,
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
    detail: str | None = None

    # Context
    consumer_platform: str | None = None
    provider_platform: str | None = None
    operation_name: str | None = None
    field_name: str | None = None

    # Source tracking
    consumer_file: str | None = None
    consumer_line: int | None = None
    provider_file: str | None = None
    provider_line: int | None = None

    def get_suppression_key(self) -> str:
        """
        Generate a suppression key for this gap.

        Format: "spec:{gap_type}:{operation_name}"
        Example: "spec:missing_operation:createUser"
                "spec:type_mismatch:getUserById"

        Returns:
            Suppression key string
        """
        operation = self.operation_name or "unknown"
        return f"spec:{self.gap_type}:{operation}"

    def to_finding_dict(self) -> dict[str, Any]:
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
    gaps: list[ContractGap] = field(default_factory=list)

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
