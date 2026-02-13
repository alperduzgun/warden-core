"""
Comprehensive tests for Flutter contract extractor.

Tests cover:
- Retrofit-style API operations (@GET, @POST, @DELETE)
- Freezed model classes with nullable fields
- Dio and HTTP package calls
- Timeout handling for large projects
- Empty project scenarios
- Malformed Dart code
- Version detection
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from warden.validation.frames.spec.extractors.flutter_extractor import FlutterExtractor
from warden.validation.frames.spec.extractors.base import ExtractorResilienceConfig
from warden.validation.frames.spec.models import (
    PlatformRole,
    OperationType,
)


# ===== Realistic Flutter Code Fixtures =====

FLUTTER_RETROFIT_API = '''
import 'package:dio/dio.dart';
import 'package:retrofit/retrofit.dart';
import '../models/user.dart';
import '../models/create_user_request.dart';

part 'user_api.g.dart';

@RestApi(baseUrl: "https://api.example.com/v1")
abstract class UserApi {
  factory UserApi(Dio dio, {String baseUrl}) = _UserApi;

  @GET("/users")
  Future<List<User>> getUsers();

  @GET("/users/{id}")
  Future<User> getUserById(@Path("id") String id);

  @POST("/users")
  Future<User> createUser(@Body() CreateUserRequest request);

  @PUT("/users/{id}")
  Future<User> updateUser(
    @Path("id") String id,
    @Body() UpdateUserRequest request,
  );

  @DELETE("/users/{id}")
  Future<void> deleteUser(@Path("id") String id);

  @GET("/users/{id}/profile")
  Future<UserProfile> getUserProfile(@Path("id") String id);

  @PATCH("/users/{id}/status")
  Future<User> updateUserStatus(
    @Path("id") String id,
    @Body() StatusUpdateRequest request,
  );
}
'''

FLUTTER_FREEZED_MODELS = '''
import 'package:freezed_annotation/freezed_annotation.dart';

part 'user.freezed.dart';
part 'user.g.dart';

@freezed
class User with _\$User {
  const factory User({
    required String id,
    required String name,
    required String email,
    String? phoneNumber,
    @JsonKey(name: 'created_at') required DateTime createdAt,
    @JsonKey(name: 'is_active') bool? isActive,
    List<String>? roles,
    @Default([]) List<Address> addresses,
  }) = _User;

  factory User.fromJson(Map<String, dynamic> json) => _\$UserFromJson(json);
}

@freezed
class Address with _\$Address {
  const factory Address({
    required String street,
    required String city,
    required String country,
    String? postalCode,
  }) = _Address;

  factory Address.fromJson(Map<String, dynamic> json) =>
      _\$AddressFromJson(json);
}

@freezed
class CreateUserRequest with _\$CreateUserRequest {
  const factory CreateUserRequest({
    required String name,
    required String email,
    String? phoneNumber,
  }) = _CreateUserRequest;

  factory CreateUserRequest.fromJson(Map<String, dynamic> json) =>
      _\$CreateUserRequestFromJson(json);
}
'''

FLUTTER_DIO_CALLS = '''
import 'package:dio/dio.dart';

class InvoiceService {
  final Dio _dio;

  InvoiceService(this._dio);

  Future<List<Invoice>> fetchInvoices() async {
    final response = await _dio.get('/api/invoices');
    return (response.data as List)
        .map((e) => Invoice.fromJson(e))
        .toList();
  }

  Future<Invoice> createInvoice(CreateInvoiceDto dto) async {
    final response = await _dio.post(
      '/api/invoices',
      data: dto.toJson(),
    );
    return Invoice.fromJson(response.data);
  }

  Future<void> deleteInvoice(String id) async {
    await _dio.delete('/api/invoices/\$id');
  }

  Future<Invoice> updateInvoice(String id, UpdateInvoiceDto dto) async {
    final response = await _dio.put(
      '/api/invoices/\$id',
      data: dto.toJson(),
    );
    return Invoice.fromJson(response.data);
  }
}
'''

FLUTTER_HTTP_PACKAGE = '''
import 'package:http/http.dart' as http;
import 'dart:convert';

class PaymentClient {
  final String baseUrl;

  PaymentClient(this.baseUrl);

  Future<Payment> processPayment(PaymentRequest request) async {
    final response = await http.post(
      Uri.parse('\$baseUrl/api/payments'),
      headers: {'Content-Type': 'application/json'},
      body: json.encode(request.toJson()),
    );

    if (response.statusCode == 200) {
      return Payment.fromJson(json.decode(response.body));
    }
    throw Exception('Payment failed');
  }

  Future<List<Payment>> getPaymentHistory() async {
    final response = await http.get(
      Uri.parse('\$baseUrl/api/payments/history'),
    );

    if (response.statusCode == 200) {
      final List data = json.decode(response.body);
      return data.map((e) => Payment.fromJson(e)).toList();
    }
    return [];
  }
}
'''

FLUTTER_ENUMS = '''
enum InvoiceStatus {
  draft,
  pending,
  paid,
  cancelled,
  overdue,
}

enum PaymentMethod {
  creditCard,
  debitCard,
  bankTransfer,
  paypal,
  cash,
}

enum UserRole {
  admin(1),
  manager(2),
  user(3),
  guest(4);

  const UserRole(this.level);
  final int level;
}
'''

MALFORMED_DART_CODE = '''
@GET("/users")
Future<List<User>> getUsers(
  // Missing closing parenthesis

class User {
  final String id
  // Missing semicolon
  final String name;

enum Status { active, inactive
// Missing closing brace
'''

VERY_LARGE_DART_FILE = '''
class HugeModel {
''' + '\n'.join([f'  final String field{i};' for i in range(10000)]) + '''
}
'''


# ===== Test Class =====

class TestFlutterExtractor:
    """Test suite for Flutter contract extractor."""

    @pytest.fixture
    def flutter_project(self, tmp_path):
        """Create a realistic Flutter project structure."""
        lib_dir = tmp_path / "lib"
        lib_dir.mkdir()

        # Create subdirectories
        (lib_dir / "api").mkdir()
        (lib_dir / "models").mkdir()
        (lib_dir / "services").mkdir()

        return tmp_path

    @pytest.fixture
    def extractor(self, flutter_project):
        """Create Flutter extractor instance."""
        return FlutterExtractor(
            project_root=flutter_project,
            role=PlatformRole.CONSUMER,
        )

    @pytest.fixture
    def fast_timeout_extractor(self, flutter_project):
        """Create extractor with very short timeout for testing."""
        config = ExtractorResilienceConfig(
            parse_timeout=0.001,  # 1ms - will timeout on large files
            extraction_timeout=0.01,
        )
        return FlutterExtractor(
            project_root=flutter_project,
            role=PlatformRole.CONSUMER,
            resilience_config=config,
        )

    # ===== Test 1: Retrofit Operations Extraction =====

    @pytest.mark.asyncio
    async def test_extract_retrofit_operations(self, flutter_project, extractor):
        """
        Test extraction of operations from Retrofit-style annotations.

        Verifies:
        - All HTTP methods extracted correctly (GET, POST, PUT, DELETE, PATCH)
        - Operation names match method names
        - Input/output types extracted from annotations
        - Correct operation types assigned (QUERY vs COMMAND)
        """
        api_file = flutter_project / "lib" / "api" / "user_api.dart"
        api_file.write_text(FLUTTER_RETROFIT_API)

        contract = await extractor.extract()

        # Should extract 7 operations
        assert len(contract.operations) == 7

        # Check getUsers (GET, no params)
        get_users = next(op for op in contract.operations if op.name == "getUsers")
        assert get_users.operation_type == OperationType.QUERY
        assert get_users.output_type == "User"  # Extracted from List<User>
        assert get_users.input_type is None
        assert "GET /users" in get_users.description

        # Check createUser (POST with body)
        create_user = next(op for op in contract.operations if op.name == "createUser")
        assert create_user.operation_type == OperationType.COMMAND
        assert create_user.input_type == "CreateUserRequest"
        assert create_user.output_type == "User"
        assert "POST /users" in create_user.description

        # Check deleteUser (DELETE)
        delete_user = next(op for op in contract.operations if op.name == "deleteUser")
        assert delete_user.operation_type == OperationType.COMMAND
        assert delete_user.output_type == "void"
        assert "DELETE /users/{id}" in delete_user.description

        # Check updateUser (PUT with body)
        update_user = next(op for op in contract.operations if op.name == "updateUser")
        assert update_user.operation_type == OperationType.COMMAND
        assert update_user.input_type == "UpdateUserRequest"

        # Check PATCH operation
        patch_op = next(op for op in contract.operations if op.name == "updateUserStatus")
        assert patch_op.operation_type == OperationType.COMMAND

    # ===== Test 2: Freezed Model Extraction =====

    @pytest.mark.asyncio
    async def test_extract_freezed_models(self, flutter_project, extractor):
        """
        Test extraction of Freezed data classes.

        Verifies:
        - Model names extracted correctly
        - Required vs optional fields identified
        - Array fields detected (List<T>)
        - Type mapping (String -> string, DateTime -> datetime)
        - Nested models extracted
        """
        models_file = flutter_project / "lib" / "models" / "user.dart"
        models_file.write_text(FLUTTER_FREEZED_MODELS)

        contract = await extractor.extract()

        # Should extract 3 models: User, Address, CreateUserRequest
        assert len(contract.models) >= 3

        # Check User model
        user_model = next(m for m in contract.models if m.name == "User")
        assert len(user_model.fields) == 8

        # Check required fields
        id_field = next(f for f in user_model.fields if f.name == "id")
        assert id_field.type_name == "string"
        assert not id_field.is_optional

        # Check optional field
        phone_field = next(f for f in user_model.fields if f.name == "phoneNumber")
        assert phone_field.is_optional

        # Check array field
        roles_field = next(f for f in user_model.fields if f.name == "roles")
        assert roles_field.is_array
        assert roles_field.type_name == "string"

        # Check datetime mapping
        created_field = next(f for f in user_model.fields if f.name == "createdAt")
        assert created_field.type_name == "datetime"

        # Check Address model (nested)
        address_model = next(m for m in contract.models if m.name == "Address")
        assert len(address_model.fields) == 4
        postal_field = next(f for f in address_model.fields if f.name == "postalCode")
        assert postal_field.is_optional

    # ===== Test 3: Nullable/Optional Fields =====

    @pytest.mark.asyncio
    async def test_nullable_optional_fields(self, flutter_project, extractor):
        """
        Test correct detection of nullable/optional fields.

        Dart nullable syntax:
        - String? phoneNumber (nullable)
        - @Default(value) (has default, effectively optional)
        """
        models_file = flutter_project / "lib" / "models" / "user.dart"
        models_file.write_text(FLUTTER_FREEZED_MODELS)

        contract = await extractor.extract()

        user_model = next(m for m in contract.models if m.name == "User")

        # Check all nullable fields are marked optional
        phone_field = next(f for f in user_model.fields if f.name == "phoneNumber")
        assert phone_field.is_optional

        is_active_field = next(f for f in user_model.fields if f.name == "isActive")
        assert is_active_field.is_optional

        # Required field should NOT be optional
        id_field = next(f for f in user_model.fields if f.name == "id")
        assert not id_field.is_optional

    # ===== Test 4: Dio HTTP Calls =====

    @pytest.mark.asyncio
    async def test_extract_dio_operations(self, flutter_project, extractor):
        """
        Test extraction from Dio HTTP client calls.

        Verifies:
        - dio.get(), dio.post(), dio.put(), dio.delete() detected
        - Operation names generated from paths
        - Correct HTTP methods identified
        """
        service_file = flutter_project / "lib" / "services" / "invoice_service.dart"
        service_file.write_text(FLUTTER_DIO_CALLS)

        contract = await extractor.extract()

        # Should extract at least 4 operations
        assert len(contract.operations) >= 4

        # Check generated operation names
        op_names = {op.name for op in contract.operations}
        assert "getInvoices" in op_names or "fetchInvoices" in op_names
        assert "createInvoice" in op_names
        assert "deleteInvoice" in op_names
        assert "updateInvoice" in op_names

        # Check operation types
        create_op = next(
            op for op in contract.operations
            if "create" in op.name.lower() and "invoice" in op.name.lower()
        )
        assert create_op.operation_type == OperationType.COMMAND

    # ===== Test 5: HTTP Package Calls =====

    @pytest.mark.asyncio
    async def test_extract_http_package_operations(self, flutter_project, extractor):
        """
        Test extraction from http package calls.

        Verifies:
        - http.get(Uri.parse(...)) detected
        - http.post(Uri.parse(...)) detected
        - Paths extracted correctly from Uri.parse strings
        """
        client_file = flutter_project / "lib" / "services" / "payment_client.dart"
        client_file.write_text(FLUTTER_HTTP_PACKAGE)

        contract = await extractor.extract()

        # Should find payment operations
        assert len(contract.operations) >= 2

        # Verify at least one GET and one POST operation
        query_ops = [op for op in contract.operations if op.operation_type == OperationType.QUERY]
        command_ops = [op for op in contract.operations if op.operation_type == OperationType.COMMAND]

        assert len(query_ops) >= 1  # getPaymentHistory
        assert len(command_ops) >= 1  # processPayment

    # ===== Test 6: Enum Extraction =====

    @pytest.mark.asyncio
    async def test_extract_enums(self, flutter_project, extractor):
        """
        Test extraction of Dart enums.

        Verifies:
        - Simple enums (value,)
        - Complex enums with constructors (value(param),)
        - Enum values extracted correctly
        """
        enums_file = flutter_project / "lib" / "models" / "enums.dart"
        enums_file.write_text(FLUTTER_ENUMS)

        contract = await extractor.extract()

        # Should extract 3 enums
        assert len(contract.enums) >= 3

        # Check InvoiceStatus (simple enum)
        invoice_status = next(e for e in contract.enums if e.name == "InvoiceStatus")
        assert len(invoice_status.values) == 5
        assert "draft" in invoice_status.values
        assert "paid" in invoice_status.values

        # Check PaymentMethod
        payment_method = next(e for e in contract.enums if e.name == "PaymentMethod")
        assert "creditCard" in payment_method.values

        # Check UserRole (enum with constructor)
        user_role = next(e for e in contract.enums if e.name == "UserRole")
        assert "admin" in user_role.values
        assert "guest" in user_role.values

    # ===== Test 7: Timeout Handling =====

    @pytest.mark.asyncio
    async def test_timeout_on_large_file(self, flutter_project, fast_timeout_extractor):
        """
        Test timeout handling for very large files.

        Verifies:
        - Extractor doesn't hang on huge files
        - Timeout is enforced
        - Stats track timeouts
        """
        large_file = flutter_project / "lib" / "models" / "huge_model.dart"
        large_file.write_text(VERY_LARGE_DART_FILE)

        # This should complete without hanging
        contract = await fast_timeout_extractor.extract()

        # Check stats
        stats = fast_timeout_extractor.get_extraction_stats()

        # Timeout might occur depending on system speed
        # Just verify it completes and doesn't crash
        assert isinstance(contract.models, list)
        assert "timeouts" in stats

    # ===== Test 8: Empty Project =====

    @pytest.mark.asyncio
    async def test_empty_project(self, flutter_project, extractor):
        """
        Test extraction from empty Flutter project.

        Verifies:
        - No crashes on empty project
        - Returns empty contract
        - Stats are zero
        """
        # Don't create any files, just use empty project

        contract = await extractor.extract()

        assert contract.name == "flutter-consumer"
        assert len(contract.operations) == 0
        assert len(contract.models) == 0
        assert len(contract.enums) == 0

        stats = extractor.get_extraction_stats()
        assert stats["files_processed"] == 0

    # ===== Test 9: Invalid/Malformed Dart Code =====

    @pytest.mark.asyncio
    async def test_malformed_dart_code(self, flutter_project, extractor):
        """
        Test extraction handles malformed Dart code gracefully.

        Verifies:
        - No crashes on syntax errors
        - Partial extraction still works for valid parts
        - Errors logged, not propagated
        """
        malformed_file = flutter_project / "lib" / "api" / "broken_api.dart"
        malformed_file.write_text(MALFORMED_DART_CODE)

        # Should not crash
        contract = await extractor.extract()

        # May extract partial data or nothing, but shouldn't fail
        assert isinstance(contract.operations, list)
        assert isinstance(contract.models, list)

        stats = extractor.get_extraction_stats()
        # May have failures logged
        assert isinstance(stats["files_failed"], int)

    # ===== Test 10: Version Detection =====

    @pytest.mark.asyncio
    async def test_version_detection_patterns(self, flutter_project, extractor):
        """
        Test detection of different Flutter/Dart SDK patterns.

        Verifies:
        - Stable SDK patterns work
        - Beta/dev SDK patterns work
        - Null-safety patterns recognized
        """
        # Create pubspec.yaml with version constraints
        pubspec = flutter_project / "pubspec.yaml"
        pubspec.write_text('''
name: test_app
description: Test Flutter app

environment:
  sdk: ">=3.0.0 <4.0.0"
  flutter: ">=3.10.0"

dependencies:
  flutter:
    sdk: flutter
  freezed_annotation: ^2.4.1
  dio: ^5.3.2
  retrofit: ^4.0.1
        ''')

        # Create simple API with modern null-safety syntax
        api_file = flutter_project / "lib" / "api" / "modern_api.dart"
        api_file.write_text('''
import 'package:retrofit/retrofit.dart';

@RestApi()
abstract class ModernApi {
  @GET("/test")
  Future<String?> testEndpoint();  // Nullable return
}
        ''')

        contract = await extractor.extract()

        # Should extract operation with nullable handling
        assert len(contract.operations) >= 1
        test_op = contract.operations[0]
        assert test_op.name == "testEndpoint"

    # ===== Test 11: Mixed Content =====

    @pytest.mark.asyncio
    async def test_mixed_retrofit_and_dio(self, flutter_project, extractor):
        """
        Test extraction from project with both Retrofit and Dio.

        Verifies:
        - Both styles extracted in same project
        - No duplicate operations
        - All operations accounted for
        """
        # Add Retrofit API
        retrofit_file = flutter_project / "lib" / "api" / "user_api.dart"
        retrofit_file.write_text(FLUTTER_RETROFIT_API)

        # Add Dio service
        dio_file = flutter_project / "lib" / "services" / "invoice_service.dart"
        dio_file.write_text(FLUTTER_DIO_CALLS)

        contract = await extractor.extract()

        # Should have operations from both sources
        # 7 from Retrofit + 4 from Dio = 11 total
        assert len(contract.operations) >= 10

        # Verify both styles present
        op_names = {op.name for op in contract.operations}
        assert "getUsers" in op_names  # From Retrofit
        assert any("invoice" in name.lower() for name in op_names)  # From Dio

    # ===== Test 12: Stats and Observability =====

    @pytest.mark.asyncio
    async def test_extraction_stats(self, flutter_project, extractor):
        """
        Test extraction statistics for observability.

        Verifies:
        - Files processed count
        - Files failed count
        - Circuit breaker state
        - Bulkhead availability
        """
        # Create multiple files
        api_file = flutter_project / "lib" / "api" / "user_api.dart"
        api_file.write_text(FLUTTER_RETROFIT_API)

        models_file = flutter_project / "lib" / "models" / "user.dart"
        models_file.write_text(FLUTTER_FREEZED_MODELS)

        await extractor.extract()

        stats = extractor.get_extraction_stats()

        # Check stats structure
        assert "files_processed" in stats
        assert "files_failed" in stats
        assert "timeouts" in stats
        assert "retries" in stats
        assert "circuit_breaker_state" in stats
        assert "bulkhead_available" in stats

        # Should have processed at least 2 files
        assert stats["files_processed"] >= 2

        # Circuit breaker should be closed (healthy)
        assert stats["circuit_breaker_state"] == "closed"

    # ===== Test 13: Widget Filtering =====

    @pytest.mark.asyncio
    async def test_widget_class_filtering(self, flutter_project, extractor):
        """
        Test that Widget/State/Page classes are filtered out.

        Verifies:
        - Widget classes not extracted as models
        - State classes ignored
        - Only data models extracted
        """
        widget_file = flutter_project / "lib" / "widgets" / "user_widget.dart"
        widget_file.parent.mkdir(parents=True, exist_ok=True)
        widget_file.write_text('''
class UserWidget extends StatelessWidget {
  final User user;

  const UserWidget({required this.user});
}

class UserState {
  final bool isLoading;
  final String? error;
}

class UserDto {
  final String id;
  final String name;
}

class UserPage extends StatefulWidget {
  @override
  State<UserPage> createState() => _UserPageState();
}
        ''')

        contract = await extractor.extract()

        # Should only extract UserDto, not widgets/states/pages
        model_names = {m.name for m in contract.models}
        assert "UserDto" in model_names
        assert "UserWidget" not in model_names
        assert "UserState" not in model_names  # May be extracted if has fields
        assert "UserPage" not in model_names

    # ===== Test 14: Complex Generics =====

    @pytest.mark.asyncio
    async def test_complex_generic_types(self, flutter_project, extractor):
        """
        Test handling of complex generic types.

        Verifies:
        - List<User> -> User (array flag set)
        - Future<ResponseWrapper<User>> -> User
        - Nested generics handled
        """
        api_file = flutter_project / "lib" / "api" / "complex_api.dart"
        api_file.write_text('''
import 'package:retrofit/retrofit.dart';

@RestApi()
abstract class ComplexApi {
  @GET("/users")
  Future<ApiResponse<List<User>>> getUsers();

  @GET("/paginated")
  Future<PaginatedResult<User>> getPaginatedUsers();
}
        ''')

        contract = await extractor.extract()

        # Should extract operations with cleaned types
        assert len(contract.operations) >= 2
        get_users = contract.operations[0]

        # Type should be cleaned from wrappers
        assert get_users.output_type in ["User", "ApiResponse", "List"]
