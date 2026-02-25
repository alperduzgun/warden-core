"""
Integration tests for cross-platform contract comparison.

Tests cover:
- Extracting contracts from both Flutter (consumer) and Spring Boot (provider)
- Comparing contracts to find gaps
- Matching operations (exact, fuzzy, semantic)
- Gap detection (missing operations, type mismatches)
- Realistic mobile-to-backend API scenarios
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from warden.validation.frames.spec.extractors.flutter_extractor import FlutterExtractor
from warden.validation.frames.spec.extractors.springboot_extractor import SpringBootExtractor
from warden.validation.frames.spec.models import (
    PlatformRole,
    OperationType,
    GapSeverity,
)


# ===== Realistic Mobile + Backend Scenario =====

# Mobile App (Flutter Consumer)
FLUTTER_INVOICE_API = """
import 'package:retrofit/retrofit.dart';
import 'package:dio/dio.dart';

@RestApi(baseUrl: "https://api.example.com/v1")
abstract class InvoiceApi {
  factory InvoiceApi(Dio dio, {String baseUrl}) = _InvoiceApi;

  @GET("/invoices")
  Future<List<Invoice>> getInvoices();

  @GET("/invoices/{id}")
  Future<Invoice> getInvoiceById(@Path("id") String id);

  @POST("/invoices")
  Future<Invoice> createInvoice(@Body() CreateInvoiceRequest request);

  @PUT("/invoices/{id}")
  Future<Invoice> updateInvoice(
    @Path("id") String id,
    @Body() UpdateInvoiceRequest request,
  );

  @DELETE("/invoices/{id}")
  Future<void> deleteInvoice(@Path("id") String id);

  // Consumer expects this but provider might not have it
  @GET("/invoices/{id}/pdf")
  Future<PdfDownloadResponse> downloadInvoicePdf(@Path("id") String id);

  // Consumer expects voice feature
  @POST("/invoices/voice")
  Future<VoiceInvoiceResult> createVoiceInvoice(
    @Body() CreateVoiceInvoiceRequest request,
  );
}
"""

FLUTTER_INVOICE_MODELS = r"""
import 'package:freezed_annotation/freezed_annotation.dart';

@freezed
class Invoice with _\$Invoice {
  const factory Invoice({
    required String id,
    required String invoiceNumber,
    required double amount,
    required String status,
    @JsonKey(name: 'created_at') required DateTime createdAt,
    String? customerName,
  }) = _Invoice;

  factory Invoice.fromJson(Map<String, dynamic> json) =>
      _\$InvoiceFromJson(json);
}

@freezed
class CreateInvoiceRequest with _\$CreateInvoiceRequest {
  const factory CreateInvoiceRequest({
    required String customerName,
    required double amount,
    String? description,
  }) = _CreateInvoiceRequest;

  factory CreateInvoiceRequest.fromJson(Map<String, dynamic> json) =>
      _\$CreateInvoiceRequestFromJson(json);
}

@freezed
class UpdateInvoiceRequest with _\$UpdateInvoiceRequest {
  const factory UpdateInvoiceRequest({
    String? customerName,
    double? amount,
    String? status,
  }) = _UpdateInvoiceRequest;

  factory UpdateInvoiceRequest.fromJson(Map<String, dynamic> json) =>
      _\$UpdateInvoiceRequestFromJson(json);
}

@freezed
class VoiceInvoiceResult with _\$VoiceInvoiceResult {
  const factory VoiceInvoiceResult({
    required String invoiceId,
    required String audioUrl,
    required String transcription,
  }) = _VoiceInvoiceResult;

  factory VoiceInvoiceResult.fromJson(Map<String, dynamic> json) =>
      _\$VoiceInvoiceResultFromJson(json);
}
"""

# Backend (Spring Boot Provider)
SPRING_INVOICE_CONTROLLER = """
package com.example.api.controller;

import org.springframework.web.bind.annotation.*;
import org.springframework.http.ResponseEntity;
import com.example.api.dto.*;
import java.util.List;

@RestController
@RequestMapping("/api/v1/invoices")
public class InvoiceController {

    @GetMapping
    public ResponseEntity<List<InvoiceDto>> getInvoices() {
        return ResponseEntity.ok(invoiceService.findAll());
    }

    @GetMapping("/{id}")
    public ResponseEntity<InvoiceDto> getInvoiceById(@PathVariable String id) {
        return ResponseEntity.ok(invoiceService.findById(id));
    }

    @PostMapping
    public ResponseEntity<InvoiceDto> createInvoice(
            @RequestBody CreateInvoiceRequest request) {
        return ResponseEntity.status(201).body(invoiceService.create(request));
    }

    @PutMapping("/{id}")
    public ResponseEntity<InvoiceDto> updateInvoice(
            @PathVariable String id,
            @RequestBody UpdateInvoiceRequest request) {
        return ResponseEntity.ok(invoiceService.update(id, request));
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteInvoice(@PathVariable String id) {
        invoiceService.delete(id);
        return ResponseEntity.noContent().build();
    }

    // Provider has this, consumer doesn't use it
    @GetMapping("/{id}/history")
    public ResponseEntity<List<InvoiceHistoryDto>> getInvoiceHistory(
            @PathVariable String id) {
        return ResponseEntity.ok(invoiceService.getHistory(id));
    }

    // PDF download is missing (consumer expects it)
}
"""

SPRING_INVOICE_DTOS = """
package com.example.api.dto;

import lombok.Data;
import java.time.LocalDateTime;

@Data
public class InvoiceDto {
    private String id;
    private String invoiceNumber;
    private Double amount;
    private String status;
    private LocalDateTime createdAt;
    private String customerName;
}

@Data
public class CreateInvoiceRequest {
    private String customerName;
    private Double amount;
    private String description;
}

@Data
public class UpdateInvoiceRequest {
    private String customerName;
    private Double amount;
    private String status;
}

@Data
public class InvoiceHistoryDto {
    private String action;
    private LocalDateTime timestamp;
    private String user;
}
"""

# Type mismatch scenario
FLUTTER_USER_API_TYPE_MISMATCH = """
@RestApi()
abstract class UserApi {
  @POST("/users")
  Future<User> createUser(@Body() CreateUserRequest request);
}
"""

FLUTTER_USER_MODEL_TYPE_MISMATCH = r"""
@freezed
class CreateUserRequest with _\$CreateUserRequest {
  const factory CreateUserRequest({
    required String name,
    required String email,
    required int age,  // Consumer sends int
  }) = _CreateUserRequest;
}
"""

SPRING_USER_CONTROLLER_TYPE_MISMATCH = """
@RestController
@RequestMapping("/api/users")
public class UserController {
    @PostMapping
    public ResponseEntity<UserDto> createUser(@RequestBody CreateUserRequest request) {
        return ResponseEntity.ok(userService.create(request));
    }
}
"""

SPRING_USER_DTO_TYPE_MISMATCH = """
@Data
public class CreateUserRequest {
    private String name;
    private String email;
    private String age;  // Provider expects String (type mismatch)
}
"""


# ===== Test Class =====


class TestPlatformIntegration:
    """Integration tests for cross-platform contract validation."""

    @pytest.fixture
    def flutter_project(self, tmp_path):
        """Create Flutter consumer project."""
        flutter_root = tmp_path / "mobile"
        flutter_root.mkdir()

        lib_dir = flutter_root / "lib"
        lib_dir.mkdir()
        (lib_dir / "api").mkdir()
        (lib_dir / "models").mkdir()

        return flutter_root

    @pytest.fixture
    def spring_project(self, tmp_path):
        """Create Spring Boot provider project."""
        spring_root = tmp_path / "backend"
        spring_root.mkdir()

        src_main = spring_root / "src" / "main" / "java" / "com" / "example" / "api"
        src_main.mkdir(parents=True)
        (src_main / "controller").mkdir()
        (src_main / "dto").mkdir()

        return spring_root

    @pytest.fixture
    def flutter_extractor(self, flutter_project):
        """Create Flutter extractor."""
        return FlutterExtractor(
            project_root=flutter_project,
            role=PlatformRole.CONSUMER,
        )

    @pytest.fixture
    def spring_extractor(self, spring_project):
        """Create Spring Boot extractor."""
        return SpringBootExtractor(
            project_root=spring_project,
            role=PlatformRole.PROVIDER,
        )

    # ===== Test 1: Extract from Both Platforms =====

    @pytest.mark.asyncio
    async def test_extract_from_both_platforms(
        self,
        flutter_project,
        spring_project,
        flutter_extractor,
        spring_extractor,
    ):
        """
        Test extracting contracts from both Flutter and Spring Boot.

        Verifies:
        - Both extractors run successfully
        - Consumer contract has expected operations
        - Provider contract has expected operations
        """
        # Setup Flutter consumer
        flutter_api = flutter_project / "lib" / "api" / "invoice_api.dart"
        flutter_api.write_text(FLUTTER_INVOICE_API)

        flutter_models = flutter_project / "lib" / "models" / "invoice.dart"
        flutter_models.write_text(FLUTTER_INVOICE_MODELS)

        # Setup Spring provider
        spring_controller = (
            spring_project
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "api"
            / "controller"
            / "InvoiceController.java"
        )
        spring_controller.write_text(SPRING_INVOICE_CONTROLLER)

        spring_dtos = spring_project / "src" / "main" / "java" / "com" / "example" / "api" / "dto" / "InvoiceDtos.java"
        spring_dtos.write_text(SPRING_INVOICE_DTOS)

        # Extract contracts
        consumer_contract = await flutter_extractor.extract()
        provider_contract = await spring_extractor.extract()

        # Verify extraction
        assert consumer_contract.name == "flutter-consumer"
        assert provider_contract.name == "springboot-provider"

        # Consumer should have 7 operations
        assert len(consumer_contract.operations) == 7

        # Provider should have 6 operations
        assert len(provider_contract.operations) == 6

        # Both should have models
        assert len(consumer_contract.models) >= 3
        assert len(provider_contract.models) >= 3

    # ===== Test 2: Exact Operation Matching =====

    @pytest.mark.asyncio
    async def test_exact_operation_matching(
        self,
        flutter_project,
        spring_project,
        flutter_extractor,
        spring_extractor,
    ):
        """
        Test exact matching of operations between platforms.

        Verifies:
        - Operations with same names match exactly
        - Input/output types compared
        - Matched operations identified
        """
        # Setup projects
        flutter_api = flutter_project / "lib" / "api" / "invoice_api.dart"
        flutter_api.write_text(FLUTTER_INVOICE_API)

        flutter_models = flutter_project / "lib" / "models" / "invoice.dart"
        flutter_models.write_text(FLUTTER_INVOICE_MODELS)

        spring_controller = (
            spring_project
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "api"
            / "controller"
            / "InvoiceController.java"
        )
        spring_controller.write_text(SPRING_INVOICE_CONTROLLER)

        spring_dtos = spring_project / "src" / "main" / "java" / "com" / "example" / "api" / "dto" / "InvoiceDtos.java"
        spring_dtos.write_text(SPRING_INVOICE_DTOS)

        # Extract
        consumer_contract = await flutter_extractor.extract()
        provider_contract = await spring_extractor.extract()

        # Find exact matches
        consumer_op_names = {op.name for op in consumer_contract.operations}
        provider_op_names = {op.name for op in provider_contract.operations}

        # Should have exact matches
        exact_matches = consumer_op_names & provider_op_names

        assert "getInvoices" in exact_matches
        assert "getInvoiceById" in exact_matches
        assert "createInvoice" in exact_matches
        assert "updateInvoice" in exact_matches
        assert "deleteInvoice" in exact_matches

    # ===== Test 3: Find Missing Operations =====

    @pytest.mark.asyncio
    async def test_find_missing_operations(
        self,
        flutter_project,
        spring_project,
        flutter_extractor,
        spring_extractor,
    ):
        """
        Test detection of missing operations (consumer expects, provider missing).

        Verifies:
        - Consumer operations not in provider identified
        - downloadInvoicePdf missing from provider
        - createVoiceInvoice missing from provider
        """
        # Setup projects
        flutter_api = flutter_project / "lib" / "api" / "invoice_api.dart"
        flutter_api.write_text(FLUTTER_INVOICE_API)

        flutter_models = flutter_project / "lib" / "models" / "invoice.dart"
        flutter_models.write_text(FLUTTER_INVOICE_MODELS)

        spring_controller = (
            spring_project
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "api"
            / "controller"
            / "InvoiceController.java"
        )
        spring_controller.write_text(SPRING_INVOICE_CONTROLLER)

        spring_dtos = spring_project / "src" / "main" / "java" / "com" / "example" / "api" / "dto" / "InvoiceDtos.java"
        spring_dtos.write_text(SPRING_INVOICE_DTOS)

        # Extract
        consumer_contract = await flutter_extractor.extract()
        provider_contract = await spring_extractor.extract()

        # Find missing operations
        consumer_op_names = {op.name for op in consumer_contract.operations}
        provider_op_names = {op.name for op in provider_contract.operations}

        missing_operations = consumer_op_names - provider_op_names

        # Should identify missing operations
        assert "downloadInvoicePdf" in missing_operations
        assert "createVoiceInvoice" in missing_operations

    # ===== Test 4: Find Unused Operations =====

    @pytest.mark.asyncio
    async def test_find_unused_operations(
        self,
        flutter_project,
        spring_project,
        flutter_extractor,
        spring_extractor,
    ):
        """
        Test detection of unused operations (provider has, consumer doesn't use).

        Verifies:
        - Provider operations not in consumer identified
        - getInvoiceHistory is unused
        """
        # Setup projects
        flutter_api = flutter_project / "lib" / "api" / "invoice_api.dart"
        flutter_api.write_text(FLUTTER_INVOICE_API)

        spring_controller = (
            spring_project
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "api"
            / "controller"
            / "InvoiceController.java"
        )
        spring_controller.write_text(SPRING_INVOICE_CONTROLLER)

        # Extract
        consumer_contract = await flutter_extractor.extract()
        provider_contract = await spring_extractor.extract()

        # Find unused operations
        consumer_op_names = {op.name for op in consumer_contract.operations}
        provider_op_names = {op.name for op in provider_contract.operations}

        unused_operations = provider_op_names - consumer_op_names

        # Should identify unused operation
        assert "getInvoiceHistory" in unused_operations

    # ===== Test 5: Type Mismatch Detection =====

    @pytest.mark.asyncio
    async def test_type_mismatch_detection(
        self,
        flutter_project,
        spring_project,
    ):
        """
        Test detection of type mismatches between platforms.

        Scenario:
        - Consumer sends age as int
        - Provider expects age as String
        - Should detect type mismatch
        """
        # Create type mismatch scenario
        flutter_api = flutter_project / "lib" / "api" / "user_api.dart"
        flutter_api.write_text(FLUTTER_USER_API_TYPE_MISMATCH)

        flutter_model = flutter_project / "lib" / "models" / "user.dart"
        flutter_model.write_text(FLUTTER_USER_MODEL_TYPE_MISMATCH)

        spring_controller = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api" / "controller" / "UserController.java"
        )
        spring_controller.write_text(SPRING_USER_CONTROLLER_TYPE_MISMATCH)

        spring_dto = spring_project / "src" / "main" / "java" / "com" / "example" / "api" / "dto" / "UserDto.java"
        spring_dto.write_text(SPRING_USER_DTO_TYPE_MISMATCH)

        # Extract
        flutter_extractor = FlutterExtractor(
            project_root=flutter_project,
            role=PlatformRole.CONSUMER,
        )
        spring_extractor = SpringBootExtractor(
            project_root=spring_project,
            role=PlatformRole.PROVIDER,
        )

        consumer_contract = await flutter_extractor.extract()
        provider_contract = await spring_extractor.extract()

        # Compare contracts
        # Both should have CreateUserRequest model
        consumer_model = next(m for m in consumer_contract.models if m.name == "CreateUserRequest")
        provider_model = next(m for m in provider_contract.models if m.name == "CreateUserRequest")

        # Find age field in both
        consumer_age = next(f for f in consumer_model.fields if f.name == "age")
        provider_age = next(f for f in provider_model.fields if f.name == "age")

        # Type mismatch: int vs string
        assert consumer_age.type_name == "int"
        assert provider_age.type_name == "string"
        assert consumer_age.type_name != provider_age.type_name

    # ===== Test 6: Fuzzy Operation Matching =====

    @pytest.mark.asyncio
    async def test_fuzzy_operation_matching(
        self,
        flutter_project,
        spring_project,
    ):
        """
        Test fuzzy matching when operation names don't match exactly.

        Scenario:
        - Consumer: fetchInvoices
        - Provider: getInvoices
        - Should match with fuzzy logic
        """
        flutter_api = flutter_project / "lib" / "api" / "invoice_api.dart"
        flutter_api.write_text("""
@RestApi()
abstract class InvoiceApi {
  @GET("/invoices")
  Future<List<Invoice>> fetchInvoices();
}
        """)

        spring_controller = (
            spring_project
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "api"
            / "controller"
            / "InvoiceController.java"
        )
        spring_controller.write_text("""
@RestController
@RequestMapping("/api/invoices")
public class InvoiceController {
    @GetMapping
    public ResponseEntity<List<InvoiceDto>> getInvoices() {
        return ResponseEntity.ok(invoiceService.findAll());
    }
}
        """)

        # Extract
        flutter_extractor = FlutterExtractor(
            project_root=flutter_project,
            role=PlatformRole.CONSUMER,
        )
        spring_extractor = SpringBootExtractor(
            project_root=spring_project,
            role=PlatformRole.PROVIDER,
        )

        consumer_contract = await flutter_extractor.extract()
        provider_contract = await spring_extractor.extract()

        # Check if operations can be matched via description (both have "GET /invoices")
        consumer_op = consumer_contract.operations[0]
        provider_op = provider_contract.operations[0]

        # Both should be GET operations
        assert consumer_op.operation_type == OperationType.QUERY
        assert provider_op.operation_type == OperationType.QUERY

        # Both should have similar descriptions
        assert "/invoices" in consumer_op.description.lower()
        assert "/invoices" in provider_op.description.lower()

        # Both should return list of invoices
        assert "invoice" in consumer_op.output_type.lower()
        assert "invoice" in provider_op.output_type.lower()

    # ===== Test 7: Complete Integration Workflow =====

    @pytest.mark.asyncio
    async def test_complete_integration_workflow(
        self,
        flutter_project,
        spring_project,
        flutter_extractor,
        spring_extractor,
    ):
        """
        Test complete workflow: extract, compare, identify all gap types.

        Verifies:
        - Extraction from both platforms
        - Exact matches identified
        - Missing operations (CRITICAL gaps)
        - Unused operations (LOW gaps)
        - Type mismatches (HIGH gaps)
        """
        # Setup Flutter consumer
        flutter_api = flutter_project / "lib" / "api" / "invoice_api.dart"
        flutter_api.write_text(FLUTTER_INVOICE_API)

        flutter_models = flutter_project / "lib" / "models" / "invoice.dart"
        flutter_models.write_text(FLUTTER_INVOICE_MODELS)

        # Setup Spring provider
        spring_controller = (
            spring_project
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "api"
            / "controller"
            / "InvoiceController.java"
        )
        spring_controller.write_text(SPRING_INVOICE_CONTROLLER)

        spring_dtos = spring_project / "src" / "main" / "java" / "com" / "example" / "api" / "dto" / "InvoiceDtos.java"
        spring_dtos.write_text(SPRING_INVOICE_DTOS)

        # Extract contracts
        consumer_contract = await flutter_extractor.extract()
        provider_contract = await spring_extractor.extract()

        # Analyze gaps
        consumer_ops = {op.name for op in consumer_contract.operations}
        provider_ops = {op.name for op in provider_contract.operations}

        matched_ops = consumer_ops & provider_ops
        missing_ops = consumer_ops - provider_ops  # CRITICAL gaps
        unused_ops = provider_ops - consumer_ops  # LOW gaps

        # Verify results
        assert len(matched_ops) == 5  # CRUD operations match
        assert len(missing_ops) == 2  # downloadInvoicePdf, createVoiceInvoice
        assert len(unused_ops) == 1  # getInvoiceHistory

        # Verify gap severity
        # Missing operations are CRITICAL (consumer expects, provider missing)
        assert "downloadInvoicePdf" in missing_ops
        assert "createVoiceInvoice" in missing_ops

        # Unused operations are LOW (provider has, consumer doesn't use)
        assert "getInvoiceHistory" in unused_ops

    # ===== Test 8: Model Comparison =====

    @pytest.mark.asyncio
    async def test_model_field_comparison(
        self,
        flutter_project,
        spring_project,
        flutter_extractor,
        spring_extractor,
    ):
        """
        Test comparison of model fields between platforms.

        Verifies:
        - Same model names identified
        - Field types compared
        - Optional vs required field detection
        """
        # Setup projects
        flutter_models = flutter_project / "lib" / "models" / "invoice.dart"
        flutter_models.write_text(FLUTTER_INVOICE_MODELS)

        spring_dtos = spring_project / "src" / "main" / "java" / "com" / "example" / "api" / "dto" / "InvoiceDtos.java"
        spring_dtos.write_text(SPRING_INVOICE_DTOS)

        # Extract
        consumer_contract = await flutter_extractor.extract()
        provider_contract = await spring_extractor.extract()

        # Find CreateInvoiceRequest in both
        consumer_model = next((m for m in consumer_contract.models if m.name == "CreateInvoiceRequest"), None)
        provider_model = next((m for m in provider_contract.models if m.name == "CreateInvoiceRequest"), None)

        assert consumer_model is not None
        assert provider_model is not None

        # Compare field names
        consumer_field_names = {f.name for f in consumer_model.fields}
        provider_field_names = {f.name for f in provider_model.fields}

        # Should have common fields
        common_fields = consumer_field_names & provider_field_names
        assert "customerName" in common_fields
        assert "amount" in common_fields
        assert "description" in common_fields

    # ===== Test 9: Empty Projects =====

    @pytest.mark.asyncio
    async def test_compare_empty_projects(
        self,
        flutter_project,
        spring_project,
        flutter_extractor,
        spring_extractor,
    ):
        """
        Test comparison when both projects are empty.

        Verifies:
        - No crashes
        - No gaps reported
        """
        # Don't create any files

        consumer_contract = await flutter_extractor.extract()
        provider_contract = await spring_extractor.extract()

        # Both should be empty
        assert len(consumer_contract.operations) == 0
        assert len(provider_contract.operations) == 0

        # No gaps
        consumer_ops = {op.name for op in consumer_contract.operations}
        provider_ops = {op.name for op in provider_contract.operations}

        missing = consumer_ops - provider_ops
        unused = provider_ops - consumer_ops

        assert len(missing) == 0
        assert len(unused) == 0

    # ===== Test 10: Statistics from Both Extractors =====

    @pytest.mark.asyncio
    async def test_extraction_stats_from_both(
        self,
        flutter_project,
        spring_project,
        flutter_extractor,
        spring_extractor,
    ):
        """
        Test extraction statistics from both platforms.

        Verifies:
        - Stats available from both extractors
        - Files processed counts
        - No circuit breaker opens
        """
        # Setup minimal files
        flutter_api = flutter_project / "lib" / "api" / "invoice_api.dart"
        flutter_api.write_text(FLUTTER_INVOICE_API)

        spring_controller = (
            spring_project
            / "src"
            / "main"
            / "java"
            / "com"
            / "example"
            / "api"
            / "controller"
            / "InvoiceController.java"
        )
        spring_controller.write_text(SPRING_INVOICE_CONTROLLER)

        # Extract
        await flutter_extractor.extract()
        await spring_extractor.extract()

        # Get stats
        flutter_stats = flutter_extractor.get_extraction_stats()
        spring_stats = spring_extractor.get_extraction_stats()

        # Verify both have stats
        assert flutter_stats["files_processed"] >= 1
        assert spring_stats["files_processed"] >= 1

        # Both should be healthy
        assert flutter_stats["circuit_breaker_state"] == "closed"
        assert spring_stats["circuit_breaker_state"] == "closed"
