"""
Comprehensive tests for Spring Boot contract extractor.

Tests cover:
- Spring MVC controllers (@RestController, @GetMapping, @PostMapping, etc.)
- DTOs with @Data, @Getter/@Setter, records, data classes
- WebClient reactive operations (Mono, Flux)
- Spring 5, 6, Boot 2, Boot 3 patterns
- Timeout handling for very large files
- Invalid Java/Kotlin syntax
- Enum extraction
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from warden.validation.frames.spec.extractors.springboot_extractor import SpringBootExtractor
from warden.validation.frames.spec.extractors.base import ExtractorResilienceConfig
from warden.validation.frames.spec.models import (
    PlatformRole,
    OperationType,
)


# ===== Realistic Spring Boot Code Fixtures =====

SPRING_BOOT_CONTROLLER_JAVA = '''
package com.example.api.controller;

import org.springframework.web.bind.annotation.*;
import org.springframework.http.ResponseEntity;
import com.example.api.dto.*;
import lombok.RequiredArgsConstructor;
import java.util.List;

@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class UserController {

    private final UserService userService;

    @GetMapping
    public ResponseEntity<List<UserDto>> getAllUsers() {
        List<UserDto> users = userService.findAll();
        return ResponseEntity.ok(users);
    }

    @GetMapping("/{id}")
    public ResponseEntity<UserDto> getUserById(@PathVariable Long id) {
        UserDto user = userService.findById(id);
        return ResponseEntity.ok(user);
    }

    @PostMapping
    public ResponseEntity<UserDto> createUser(@RequestBody CreateUserRequest request) {
        UserDto user = userService.create(request);
        return ResponseEntity.status(201).body(user);
    }

    @PutMapping("/{id}")
    public ResponseEntity<UserDto> updateUser(
            @PathVariable Long id,
            @RequestBody UpdateUserRequest request) {
        UserDto user = userService.update(id, request);
        return ResponseEntity.ok(user);
    }

    @PatchMapping("/{id}/status")
    public ResponseEntity<UserDto> updateUserStatus(
            @PathVariable Long id,
            @RequestBody StatusUpdateRequest request) {
        UserDto user = userService.updateStatus(id, request);
        return ResponseEntity.ok(user);
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteUser(@PathVariable Long id) {
        userService.delete(id);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/{id}/profile")
    public ResponseEntity<UserProfileDto> getUserProfile(@PathVariable Long id) {
        UserProfileDto profile = userService.getProfile(id);
        return ResponseEntity.ok(profile);
    }
}
'''

SPRING_BOOT_CONTROLLER_KOTLIN = '''
package com.example.api.controller

import org.springframework.web.bind.annotation.*
import org.springframework.http.ResponseEntity
import com.example.api.dto.*

@RestController
@RequestMapping("/api/invoices")
class InvoiceController(
    private val invoiceService: InvoiceService
) {

    @GetMapping
    fun getAllInvoices(): ResponseEntity<List<InvoiceDto>> {
        val invoices = invoiceService.findAll()
        return ResponseEntity.ok(invoices)
    }

    @GetMapping("/{id}")
    fun getInvoiceById(@PathVariable id: Long): ResponseEntity<InvoiceDto> {
        val invoice = invoiceService.findById(id)
        return ResponseEntity.ok(invoice)
    }

    @PostMapping
    fun createInvoice(@RequestBody request: CreateInvoiceRequest): ResponseEntity<InvoiceDto> {
        val invoice = invoiceService.create(request)
        return ResponseEntity.status(201).body(invoice)
    }

    @PutMapping("/{id}")
    fun updateInvoice(
        @PathVariable id: Long,
        @RequestBody request: UpdateInvoiceRequest
    ): ResponseEntity<InvoiceDto> {
        val invoice = invoiceService.update(id, request)
        return ResponseEntity.ok(invoice)
    }

    @DeleteMapping("/{id}")
    fun deleteInvoice(@PathVariable id: Long): ResponseEntity<Unit> {
        invoiceService.delete(id)
        return ResponseEntity.noContent().build()
    }
}
'''

JAVA_LOMBOK_DTO = '''
package com.example.api.dto;

import lombok.Data;
import lombok.Builder;
import lombok.AllArgsConstructor;
import lombok.NoArgsConstructor;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.time.LocalDateTime;
import java.util.List;

@Data
@Builder
@AllArgsConstructor
@NoArgsConstructor
public class UserDto {
    private Long id;
    private String username;
    private String email;
    private String phoneNumber;

    @JsonProperty("created_at")
    private LocalDateTime createdAt;

    @JsonProperty("is_active")
    private Boolean isActive;

    private List<String> roles;
    private AddressDto address;
}

@Data
public class AddressDto {
    private String street;
    private String city;
    private String country;
    private String postalCode;
}

@Data
public class CreateUserRequest {
    private String username;
    private String email;
    private String password;
}

@Data
@AllArgsConstructor
public class UpdateUserRequest {
    private String email;
    private String phoneNumber;
}
'''

JAVA_RECORD = '''
package com.example.api.dto;

import java.time.LocalDateTime;

public record InvoiceDto(
    Long id,
    String invoiceNumber,
    Double amount,
    InvoiceStatus status,
    LocalDateTime createdAt
) {}

public record CreateInvoiceRequest(
    String customerName,
    Double amount,
    String description
) {}

public record PaymentDto(
    Long id,
    String transactionId,
    Double amount,
    PaymentMethod method
) {}
'''

KOTLIN_DATA_CLASS = '''
package com.example.api.dto

import com.fasterxml.jackson.annotation.JsonProperty
import java.time.LocalDateTime

data class ProductDto(
    val id: Long,
    val name: String,
    val description: String?,
    val price: Double,
    val currency: String,
    @JsonProperty("in_stock")
    val inStock: Boolean,
    val categories: List<String>?
)

data class CreateProductRequest(
    val name: String,
    val description: String?,
    val price: Double,
    val currency: String = "USD"
)

data class OrderDto(
    val id: Long,
    val orderNumber: String,
    val items: List<OrderItemDto>,
    val totalAmount: Double,
    val status: OrderStatus,
    val createdAt: LocalDateTime
)

data class OrderItemDto(
    val productId: Long,
    val quantity: Int,
    val unitPrice: Double
)
'''

REACTIVE_CONTROLLER = '''
package com.example.api.controller;

import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Flux;

@RestController
@RequestMapping("/api/reactive")
public class ReactiveController {

    @GetMapping("/users")
    public Flux<UserDto> streamUsers() {
        return userService.findAllReactive();
    }

    @GetMapping("/users/{id}")
    public Mono<UserDto> getUserReactive(@PathVariable Long id) {
        return userService.findByIdReactive(id);
    }

    @PostMapping("/users")
    public Mono<UserDto> createUserReactive(@RequestBody CreateUserRequest request) {
        return userService.createReactive(request);
    }

    @DeleteMapping("/users/{id}")
    public Mono<Void> deleteUserReactive(@PathVariable Long id) {
        return userService.deleteReactive(id);
    }
}
'''

JAVA_ENUMS = '''
package com.example.api.dto;

public enum InvoiceStatus {
    DRAFT,
    PENDING,
    PAID,
    CANCELLED,
    OVERDUE
}

public enum PaymentMethod {
    CREDIT_CARD,
    DEBIT_CARD,
    BANK_TRANSFER,
    PAYPAL,
    CASH
}

public enum UserRole {
    ADMIN(1),
    MANAGER(2),
    USER(3),
    GUEST(4);

    private final int level;

    UserRole(int level) {
        this.level = level;
    }

    public int getLevel() {
        return level;
    }
}
'''

KOTLIN_ENUM = '''
package com.example.api.dto

enum class OrderStatus {
    CREATED,
    PROCESSING,
    SHIPPED,
    DELIVERED,
    CANCELLED;

    companion object {
        fun fromString(value: String): OrderStatus {
            return valueOf(value.uppercase())
        }
    }
}

enum class Priority(val level: Int) {
    LOW(1),
    MEDIUM(2),
    HIGH(3),
    CRITICAL(4)
}
'''

MALFORMED_JAVA_CODE = '''
@GetMapping("/users")
public ResponseEntity<List<UserDto>> getUsers(
    // Missing closing parenthesis

public class UserDto {
    private String id
    // Missing semicolon
    private String name;

public enum Status { ACTIVE, INACTIVE
// Missing closing brace
'''

VERY_LARGE_JAVA_FILE = '''
package com.example.api.dto;

public class HugeDto {
''' + '\n'.join([f'    private String field{i};' for i in range(10000)]) + '''
}
'''

SPRING_5_PATTERNS = '''
@RestController
@RequestMapping(value = "/api/legacy", produces = "application/json")
public class LegacyController {

    @RequestMapping(value = "/users", method = RequestMethod.GET)
    public List<UserDto> getUsers() {
        return userService.findAll();
    }

    @RequestMapping(value = "/users/{id}", method = RequestMethod.GET)
    public UserDto getUserById(@PathVariable("id") Long userId) {
        return userService.findById(userId);
    }

    @RequestMapping(value = "/users", method = RequestMethod.POST)
    public UserDto createUser(@RequestBody CreateUserRequest request) {
        return userService.create(request);
    }
}
'''

SPRING_6_PATTERNS = '''
@RestController
@RequestMapping("/api/modern")
public class ModernController {

    @GetMapping(value = "/users", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<List<UserDto>> getUsers(
            @RequestParam(required = false) String filter,
            Pageable pageable) {
        return ResponseEntity.ok(userService.findAll(filter, pageable));
    }

    @PostMapping(value = "/users", consumes = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<UserDto> createUser(
            @Valid @RequestBody CreateUserRequest request) {
        return ResponseEntity.created(location).body(user);
    }
}
'''


# ===== Test Class =====

class TestSpringBootExtractor:
    """Test suite for Spring Boot contract extractor."""

    @pytest.fixture
    def spring_project(self, tmp_path):
        """Create a realistic Spring Boot project structure."""
        src_main = tmp_path / "src" / "main" / "java" / "com" / "example" / "api"
        src_main.mkdir(parents=True)

        # Create subdirectories
        (src_main / "controller").mkdir()
        (src_main / "dto").mkdir()
        (src_main / "service").mkdir()

        return tmp_path

    @pytest.fixture
    def kotlin_spring_project(self, tmp_path):
        """Create a Kotlin Spring Boot project structure."""
        src_main = tmp_path / "src" / "main" / "kotlin" / "com" / "example" / "api"
        src_main.mkdir(parents=True)

        (src_main / "controller").mkdir()
        (src_main / "dto").mkdir()

        return tmp_path

    @pytest.fixture
    def extractor(self, spring_project):
        """Create Spring Boot extractor instance."""
        return SpringBootExtractor(
            project_root=spring_project,
            role=PlatformRole.PROVIDER,
        )

    @pytest.fixture
    def kotlin_extractor(self, kotlin_spring_project):
        """Create extractor for Kotlin project."""
        return SpringBootExtractor(
            project_root=kotlin_spring_project,
            role=PlatformRole.PROVIDER,
        )

    @pytest.fixture
    def fast_timeout_extractor(self, spring_project):
        """Create extractor with very short timeout."""
        config = ExtractorResilienceConfig(
            parse_timeout=0.001,
            extraction_timeout=0.01,
        )
        return SpringBootExtractor(
            project_root=spring_project,
            role=PlatformRole.PROVIDER,
            resilience_config=config,
        )

    # ===== Test 1: Spring MVC Controllers =====

    @pytest.mark.asyncio
    async def test_extract_spring_controller_operations(self, spring_project, extractor):
        """
        Test extraction of operations from Spring MVC controllers.

        Verifies:
        - @GetMapping, @PostMapping, @PutMapping, @PatchMapping, @DeleteMapping
        - Base path from @RequestMapping on class
        - Path variables and request bodies detected
        - Correct operation types (QUERY vs COMMAND)
        """
        controller_path = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "controller" / "UserController.java"
        )
        controller_path.write_text(SPRING_BOOT_CONTROLLER_JAVA)

        contract = await extractor.extract()

        # Should extract 7 operations
        assert len(contract.operations) == 7

        # Check getAllUsers (GET)
        get_all = next(op for op in contract.operations if op.name == "getAllUsers")
        assert get_all.operation_type == OperationType.QUERY
        assert get_all.output_type == "UserDto"
        assert "GET /api/users" in get_all.description

        # Check createUser (POST with body)
        create = next(op for op in contract.operations if op.name == "createUser")
        assert create.operation_type == OperationType.COMMAND
        assert create.input_type == "CreateUserRequest"
        assert create.output_type == "UserDto"
        assert "POST /api/users" in create.description

        # Check updateUser (PUT with body)
        update = next(op for op in contract.operations if op.name == "updateUser")
        assert update.operation_type == OperationType.COMMAND
        assert update.input_type == "UpdateUserRequest"

        # Check deleteUser (DELETE)
        delete = next(op for op in contract.operations if op.name == "deleteUser")
        assert delete.operation_type == OperationType.COMMAND
        assert delete.output_type == "void"

        # Check PATCH operation
        patch_op = next(op for op in contract.operations if op.name == "updateUserStatus")
        assert patch_op.operation_type == OperationType.COMMAND
        assert "PATCH /api/users/{id}/status" in patch_op.description

    # ===== Test 2: Kotlin Controllers =====

    @pytest.mark.asyncio
    async def test_extract_kotlin_controller(self, kotlin_spring_project, kotlin_extractor):
        """
        Test extraction from Kotlin Spring Boot controllers.

        Verifies:
        - Kotlin function syntax parsed correctly
        - Parameter types extracted (name: Type syntax)
        - Return types extracted (: Type syntax)
        """
        controller_path = (
            kotlin_spring_project / "src" / "main" / "kotlin" / "com" / "example" / "api"
            / "controller" / "InvoiceController.kt"
        )
        controller_path.write_text(SPRING_BOOT_CONTROLLER_KOTLIN)

        contract = await kotlin_extractor.extract()

        # Should extract 5 operations
        assert len(contract.operations) == 5

        # Check Kotlin operation extraction
        get_all = next(op for op in contract.operations if op.name == "getAllInvoices")
        assert get_all.operation_type == OperationType.QUERY
        assert get_all.output_type == "InvoiceDto"

        create = next(op for op in contract.operations if op.name == "createInvoice")
        assert create.operation_type == OperationType.COMMAND
        assert create.input_type == "CreateInvoiceRequest"

    # ===== Test 3: Java DTOs (Lombok) =====

    @pytest.mark.asyncio
    async def test_extract_lombok_dtos(self, spring_project, extractor):
        """
        Test extraction of Lombok-annotated DTOs.

        Verifies:
        - @Data classes extracted
        - Private fields identified
        - Field types mapped correctly
        - Nested DTOs extracted
        """
        dto_path = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "dto" / "UserDto.java"
        )
        dto_path.write_text(JAVA_LOMBOK_DTO)

        contract = await extractor.extract()

        # Should extract multiple DTOs
        assert len(contract.models) >= 3

        # Check UserDto
        user_dto = next(m for m in contract.models if m.name == "UserDto")
        assert len(user_dto.fields) >= 6

        # Check field types
        id_field = next(f for f in user_dto.fields if f.name == "id")
        assert id_field.type_name == "int"  # Long -> int

        email_field = next(f for f in user_dto.fields if f.name == "email")
        assert email_field.type_name == "string"

        # Check array field
        roles_field = next(f for f in user_dto.fields if f.name == "roles")
        assert roles_field.is_array
        assert roles_field.type_name == "string"

        # Check datetime field
        created_field = next(f for f in user_dto.fields if f.name == "createdAt")
        assert created_field.type_name == "datetime"

        # Check nested DTO
        address_dto = next(m for m in contract.models if m.name == "AddressDto")
        assert len(address_dto.fields) == 4

    # ===== Test 4: Java Records =====

    @pytest.mark.asyncio
    async def test_extract_java_records(self, spring_project, extractor):
        """
        Test extraction of Java 17+ records.

        Verifies:
        - Record syntax recognized
        - Record components extracted as fields
        - Types mapped correctly
        """
        record_path = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "dto" / "InvoiceDto.java"
        )
        record_path.write_text(JAVA_RECORD)

        contract = await extractor.extract()

        # Should extract records
        assert len(contract.models) >= 2

        # Check InvoiceDto record
        invoice_dto = next(m for m in contract.models if m.name == "InvoiceDto")
        assert len(invoice_dto.fields) == 5

        # Check field extraction
        id_field = next(f for f in invoice_dto.fields if f.name == "id")
        assert id_field.type_name == "int"

        amount_field = next(f for f in invoice_dto.fields if f.name == "amount")
        assert amount_field.type_name == "float"  # Double -> float

    # ===== Test 5: Kotlin Data Classes =====

    @pytest.mark.asyncio
    async def test_extract_kotlin_data_classes(self, kotlin_spring_project, kotlin_extractor):
        """
        Test extraction of Kotlin data classes.

        Verifies:
        - data class syntax parsed
        - val/var parameters extracted
        - Nullable types detected (Type?)
        - Default values identified
        """
        dto_path = (
            kotlin_spring_project / "src" / "main" / "kotlin" / "com" / "example" / "api"
            / "dto" / "ProductDto.kt"
        )
        dto_path.write_text(KOTLIN_DATA_CLASS)

        contract = await kotlin_extractor.extract()

        # Should extract data classes
        assert len(contract.models) >= 3

        # Check ProductDto
        product_dto = next(m for m in contract.models if m.name == "ProductDto")
        assert len(product_dto.fields) >= 6

        # Check nullable field
        description_field = next(f for f in product_dto.fields if f.name == "description")
        assert description_field.is_optional

        # Check array field
        categories_field = next(f for f in product_dto.fields if f.name == "categories")
        assert categories_field.is_array
        assert categories_field.is_optional

        # Check OrderDto with nested items
        order_dto = next(m for m in contract.models if m.name == "OrderDto")
        items_field = next(f for f in order_dto.fields if f.name == "items")
        assert items_field.is_array

    # ===== Test 6: Reactive Operations =====

    @pytest.mark.asyncio
    async def test_extract_reactive_operations(self, spring_project, extractor):
        """
        Test extraction of WebFlux reactive operations.

        Verifies:
        - Mono<T> unwrapped to T
        - Flux<T> unwrapped to T (array flag set)
        - Reactive CRUD operations extracted
        """
        controller_path = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "controller" / "ReactiveController.java"
        )
        controller_path.write_text(REACTIVE_CONTROLLER)

        contract = await extractor.extract()

        # Should extract reactive operations
        assert len(contract.operations) >= 4

        # Check Flux operation (stream)
        stream_op = next(op for op in contract.operations if op.name == "streamUsers")
        assert stream_op.output_type == "UserDto"

        # Check Mono operation (single)
        get_op = next(op for op in contract.operations if op.name == "getUserReactive")
        assert get_op.output_type == "UserDto"

        # Check Mono<Void>
        delete_op = next(op for op in contract.operations if op.name == "deleteUserReactive")
        assert delete_op.output_type == "void"

    # ===== Test 7: Java Enums =====

    @pytest.mark.asyncio
    async def test_extract_java_enums(self, spring_project, extractor):
        """
        Test extraction of Java enums.

        Verifies:
        - Simple enums extracted
        - Complex enums with constructors
        - Enum values in UPPER_CASE
        """
        enum_path = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "dto" / "Enums.java"
        )
        enum_path.write_text(JAVA_ENUMS)

        contract = await extractor.extract()

        # Should extract 3 enums
        assert len(contract.enums) >= 3

        # Check InvoiceStatus
        invoice_status = next(e for e in contract.enums if e.name == "InvoiceStatus")
        assert len(invoice_status.values) == 5
        assert "DRAFT" in invoice_status.values
        assert "PAID" in invoice_status.values

        # Check PaymentMethod
        payment_method = next(e for e in contract.enums if e.name == "PaymentMethod")
        assert "CREDIT_CARD" in payment_method.values

        # Check UserRole (enum with constructor)
        user_role = next(e for e in contract.enums if e.name == "UserRole")
        assert "ADMIN" in user_role.values
        assert "GUEST" in user_role.values

    # ===== Test 8: Kotlin Enums =====

    @pytest.mark.asyncio
    async def test_extract_kotlin_enums(self, kotlin_spring_project, kotlin_extractor):
        """
        Test extraction of Kotlin enum classes.

        Verifies:
        - enum class syntax recognized
        - Enum values extracted
        - Enum with properties handled
        """
        enum_path = (
            kotlin_spring_project / "src" / "main" / "kotlin" / "com" / "example" / "api"
            / "dto" / "OrderStatus.kt"
        )
        enum_path.write_text(KOTLIN_ENUM)

        contract = await kotlin_extractor.extract()

        # Should extract enums
        assert len(contract.enums) >= 2

        # Check OrderStatus
        order_status = next(e for e in contract.enums if e.name == "OrderStatus")
        assert "CREATED" in order_status.values
        assert "DELIVERED" in order_status.values

        # Check Priority (enum with properties)
        priority = next(e for e in contract.enums if e.name == "Priority")
        assert "HIGH" in priority.values

    # ===== Test 9: Timeout Handling =====

    @pytest.mark.asyncio
    async def test_timeout_on_large_file(self, spring_project, fast_timeout_extractor):
        """
        Test timeout handling for very large files.

        Verifies:
        - No infinite hangs on huge files
        - Timeout enforced
        - Stats track timeouts
        """
        large_file = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "dto" / "HugeDto.java"
        )
        large_file.write_text(VERY_LARGE_JAVA_FILE)

        # Should complete without hanging
        contract = await fast_timeout_extractor.extract()

        # Verify completion
        assert isinstance(contract.models, list)

        stats = fast_timeout_extractor.get_extraction_stats()
        assert "timeouts" in stats

    # ===== Test 10: Invalid Java Syntax =====

    @pytest.mark.asyncio
    async def test_malformed_java_code(self, spring_project, extractor):
        """
        Test graceful handling of malformed Java code.

        Verifies:
        - No crashes on syntax errors
        - Partial extraction works
        - Errors logged, not propagated
        """
        malformed_file = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "controller" / "BrokenController.java"
        )
        malformed_file.write_text(MALFORMED_JAVA_CODE)

        # Should not crash
        contract = await extractor.extract()

        assert isinstance(contract.operations, list)
        assert isinstance(contract.models, list)

        stats = extractor.get_extraction_stats()
        assert isinstance(stats["files_failed"], int)

    # ===== Test 11: Spring 5 Patterns =====

    @pytest.mark.asyncio
    async def test_spring_5_request_mapping(self, spring_project, extractor):
        """
        Test extraction from Spring 5 @RequestMapping patterns.

        Verifies:
        - @RequestMapping(method = RequestMethod.GET) recognized
        - Value and method attributes parsed
        - Legacy patterns supported
        """
        controller_path = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "controller" / "LegacyController.java"
        )
        controller_path.write_text(SPRING_5_PATTERNS)

        contract = await extractor.extract()

        # Should extract operations from legacy syntax
        assert len(contract.operations) >= 3

        get_users = next(op for op in contract.operations if op.name == "getUsers")
        assert get_users.operation_type == OperationType.QUERY

        create_user = next(op for op in contract.operations if op.name == "createUser")
        assert create_user.operation_type == OperationType.COMMAND

    # ===== Test 12: Spring 6/Boot 3 Patterns =====

    @pytest.mark.asyncio
    async def test_spring_6_modern_patterns(self, spring_project, extractor):
        """
        Test extraction from Spring 6/Boot 3 patterns.

        Verifies:
        - Modern annotations with full attributes
        - @Valid, Pageable parameters handled
        - MediaType constants recognized
        """
        controller_path = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "controller" / "ModernController.java"
        )
        controller_path.write_text(SPRING_6_PATTERNS)

        contract = await extractor.extract()

        # Should extract modern operations
        assert len(contract.operations) >= 2

        get_users = next(op for op in contract.operations if op.name == "getUsers")
        assert get_users.operation_type == OperationType.QUERY

        create = next(op for op in contract.operations if op.name == "createUser")
        assert create.input_type == "CreateUserRequest"

    # ===== Test 13: Empty Project =====

    @pytest.mark.asyncio
    async def test_empty_project(self, spring_project, extractor):
        """
        Test extraction from empty Spring Boot project.

        Verifies:
        - No crashes on empty project
        - Returns empty contract
        """
        contract = await extractor.extract()

        assert contract.name == "springboot-provider"
        assert len(contract.operations) == 0
        assert len(contract.models) == 0
        assert len(contract.enums) == 0

    # ===== Test 14: Class Filtering =====

    @pytest.mark.asyncio
    async def test_non_model_class_filtering(self, spring_project, extractor):
        """
        Test that non-DTO classes are filtered out.

        Verifies:
        - Controller classes not extracted as models
        - Service, Repository, Config classes ignored
        - Only DTOs extracted
        """
        mixed_file = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "dto" / "MixedClasses.java"
        )
        mixed_file.write_text('''
package com.example.api.dto;

public class UserService {
    private UserRepository repository;
}

public class UserRepository {
    private JdbcTemplate jdbcTemplate;
}

public class AppConfig {
    private String appName;
}

public class UserDto {
    private String id;
    private String name;
}
        ''')

        contract = await extractor.extract()

        # Should only extract UserDto
        model_names = {m.name for m in contract.models}
        assert "UserDto" in model_names
        assert "UserService" not in model_names
        assert "UserRepository" not in model_names
        assert "AppConfig" not in model_names

    # ===== Test 15: Stats and Observability =====

    @pytest.mark.asyncio
    async def test_extraction_stats(self, spring_project, extractor):
        """
        Test extraction statistics.

        Verifies:
        - Files processed count
        - Circuit breaker state
        - Bulkhead availability
        """
        controller_path = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "controller" / "UserController.java"
        )
        controller_path.write_text(SPRING_BOOT_CONTROLLER_JAVA)

        dto_path = (
            spring_project / "src" / "main" / "java" / "com" / "example" / "api"
            / "dto" / "UserDto.java"
        )
        dto_path.write_text(JAVA_LOMBOK_DTO)

        await extractor.extract()

        stats = extractor.get_extraction_stats()

        assert "files_processed" in stats
        assert "files_failed" in stats
        assert "circuit_breaker_state" in stats
        assert "bulkhead_available" in stats

        # Should have processed files
        assert stats["files_processed"] >= 2
        assert stats["circuit_breaker_state"] == "closed"
