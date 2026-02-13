# Spec Frame - API Contract Validation

> **Frame Name:** Spec Frame
> **Display Name:** API Contract Spec
> **Version:** 1.0.0
> **Category:** GLOBAL
> **Scope:** PROJECT_LEVEL

## Özet

Spec Frame, farklı platformlar (frontend/backend) arasındaki API contract'larını kod üzerinden otomatik olarak çıkaran ve karşılaştıran bir validation frame'idir. Manuel dokümantasyon gerektirmeden, consumer'ın beklentileri ile provider'ın sunduğu API'ler arasındaki uyumsuzlukları tespit eder.

## Motivasyon

Modern microservice mimarilerinde frontend ve backend farklı teknolojilerle geliştirilir:

```
┌─────────────────┐         ┌─────────────────┐
│  Flutter App    │ ──API── │  Spring Boot    │
│  (Consumer)     │         │  (Provider)     │
└─────────────────┘         └─────────────────┘
```

**Problem:** Frontend'in beklediği API ile backend'in sunduğu API arasında uyumsuzluklar runtime'da ortaya çıkar.

**Çözüm:** Spec Frame, her iki tarafın kodunu analiz ederek contract'ları çıkarır ve derleme zamanında uyumsuzlukları tespit eder.

## Mimari

```
┌─────────────────────────────────────────────────────────────────┐
│                         Spec Frame                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │  Extractors  │───▶│   Contract   │───▶│ Gap Analyzer │       │
│  │  (10 adet)   │    │    Model     │    │              │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│         │                   │                   │                │
│         ▼                   ▼                   ▼                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │ Tree-sitter  │    │   Contract   │    │   Findings   │       │
│  │   Parser     │    │    YAML      │    │    SARIF     │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Bileşenler

### 1. Contract Model (`models.py`)

Platform-agnostic contract tanımı:

```python
@dataclass
class Contract:
    name: str
    version: str = "1.0.0"
    operations: List[OperationDefinition]  # API endpoints/calls
    models: List[ModelDefinition]          # DTOs, entities
    enums: List[EnumDefinition]            # Enum definitions
    metadata: Dict[str, Any]               # Additional metadata
```

**Operation Definition:**
```python
@dataclass
class OperationDefinition:
    name: str                    # getUsers, createOrder
    method: Optional[str]        # GET, POST, PUT, DELETE
    path: Optional[str]          # /api/users, /api/orders
    input_type: Optional[str]    # CreateUserRequest
    output_type: Optional[str]   # UserResponse
    source_file: Optional[str]   # Kaynak dosya
    source_line: Optional[int]   # Satır numarası
```

### 2. Platform Extractors (`extractors/`)

Her platform için özelleştirilmiş contract extractor:

| Platform | Dosya | Rol | Desteklenen Patterns |
|----------|-------|-----|---------------------|
| **Flutter** | `flutter_extractor.py` | Consumer | Retrofit, Dio |
| **React** | `react_extractor.py` | Consumer | Axios, Fetch, React Query |
| **Angular** | `angular_extractor.py` | Consumer | HttpClient |
| **Vue** | `vue_extractor.py` | Consumer | Axios |
| **Express** | `express_extractor.py` | Provider | app.get/post/put/delete |
| **Go** | `go_extractor.py` | Provider | Gin, Echo |
| **Spring Boot** | `springboot_extractor.py` | Provider | @RestController |
| **FastAPI** | `fastapi_extractor.py` | Provider | @app.get/post |
| **ASP.NET Core** | `aspnetcore_extractor.py` | Provider | [HttpGet], [HttpPost] |
| **NestJS** | `nestjs_extractor.py` | Provider | @Get, @Post decorators |

**Extractor Base Class:**
```python
class BaseContractExtractor(ABC):
    platform_type: PlatformType
    supported_languages: List[CodeLanguage]
    file_patterns: List[str]

    @abstractmethod
    async def extract(self) -> Contract:
        """Extract contract from platform code."""
        pass
```

### 3. Gap Analyzer (`analyzer.py`)

Consumer ve provider contract'larını karşılaştırır:

```python
class GapAnalyzer:
    def analyze(
        self,
        consumer: Contract,
        provider: Contract,
    ) -> SpecAnalysisResult:
        """
        Karşılaştırma stratejisi:
        1. Exact match (getUsers == getUsers)
        2. Normalized match (getUsers == fetchUsers → users)
        3. Fuzzy match (getUserList ≈ getUsers, threshold: 0.8)
        """
```

**Tespit Edilen Gap Türleri:**

| Gap Type | Severity | Açıklama |
|----------|----------|----------|
| `missing_operation` | CRITICAL | Consumer bekliyor, provider yok |
| `unused_operation` | LOW | Provider sunuyor, consumer kullanmıyor |
| `input_type_mismatch` | HIGH | Input tipi uyumsuz |
| `output_type_mismatch` | HIGH | Output tipi uyumsuz |
| `missing_field` | HIGH | Model'de field eksik |
| `field_type_mismatch` | HIGH | Field tipi uyumsuz |
| `nullable_mismatch` | MEDIUM | Optional/required uyumsuzluğu |
| `enum_value_missing` | MEDIUM | Enum değeri eksik |

**Type Compatibility:**
```python
# Bu tipler compatible kabul edilir:
type_aliases = {
    "int": {"integer", "int32", "int64", "number"},
    "float": {"double", "decimal", "number"},
    "string": {"str", "text"},
    "bool": {"boolean"},
    "datetime": {"date", "timestamp"},
}
```

### 4. SARIF Report Generator (`report.py`)

GitHub Code Scanning uyumlu rapor üretir:

```python
class SarifReportGenerator:
    def generate(self, result: SpecAnalysisResult) -> Dict[str, Any]:
        """SARIF 2.1.0 format output."""
```

**Örnek SARIF Output:**
```json
{
  "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
  "version": "2.1.0",
  "runs": [{
    "tool": {
      "driver": {
        "name": "Warden Spec Frame",
        "version": "1.0.0"
      }
    },
    "results": [{
      "ruleId": "spec/missing-operation",
      "level": "error",
      "message": {
        "text": "Operation 'getUsers' expected by consumer but not found in provider"
      }
    }]
  }]
}
```

### 5. Resilience Patterns (`resilience.py`)

Chaos engineering prensiplerine uygun fault-tolerance:

```
┌─────────────────────────────────────────────────────────┐
│                    Request Flow                          │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐ │
│  │   Circuit    │──▶│   Timeout    │──▶│    Retry     │ │
│  │   Breaker    │   │   (30s)      │   │   (3x exp)   │ │
│  └──────────────┘   └──────────────┘   └──────────────┘ │
│         │                                      │         │
│         ▼                                      ▼         │
│  ┌──────────────┐                    ┌──────────────┐   │
│  │   Bulkhead   │                    │   Graceful   │   │
│  │   (10 max)   │                    │  Degradation │   │
│  └──────────────┘                    └──────────────┘   │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

| Pattern | Parametre | Default | Açıklama |
|---------|-----------|---------|----------|
| **Timeout** | `parse_timeout` | 30s | Dosya parsing timeout |
| **Timeout** | `extraction_timeout` | 300s | Toplam extraction timeout |
| **Retry** | `retry_max_attempts` | 3 | Maksimum deneme sayısı |
| **Retry** | `retry_initial_delay` | 1s | İlk bekleme süresi |
| **Circuit Breaker** | `circuit_failure_threshold` | 5 | Açılma eşiği |
| **Circuit Breaker** | `circuit_timeout_duration` | 60s | Recovery süresi |
| **Bulkhead** | `max_concurrent_files` | 10 | Eşzamanlı dosya limiti |

## Konfigürasyon

### `.warden/config.yaml`

```yaml
frames:
  spec:
    # Platform tanımları
    platforms:
      - name: mobile
        path: ../invoice-mobile
        type: flutter
        role: consumer

      - name: web
        path: ../invoice-web
        type: react
        role: consumer

      - name: backend
        path: ../invoice-api
        type: spring
        role: provider

    # Gap analysis ayarları
    gap_analysis:
      fuzzy_threshold: 0.8      # Fuzzy match eşiği (0.0-1.0)
      enable_fuzzy: true        # Fuzzy matching aktif mi?

    # Resilience ayarları
    resilience:
      parse_timeout: 30         # Dosya parsing timeout (saniye)
      extraction_timeout: 300   # Toplam extraction timeout (saniye)
      retry_max_attempts: 3     # Retry sayısı
      max_concurrent_files: 10  # Eşzamanlı dosya limiti
```

### Platform Types

```python
class PlatformType(Enum):
    # Frontend (Consumer)
    FLUTTER = "flutter"
    REACT = "react"
    ANGULAR = "angular"
    VUE = "vue"

    # Backend (Provider)
    EXPRESS = "express"
    GO = "go"
    SPRING = "spring"
    FASTAPI = "fastapi"
    ASPNETCORE = "aspnetcore"
    NESTJS = "nestjs"
```

## CLI Komutları

### `warden spec analyze`

İki platform arasındaki contract gap'lerini analiz eder:

```bash
# Config dosyası ile
warden spec analyze --config .warden/config.yaml

# Direkt platform belirterek
warden spec analyze --consumer ../mobile --provider ../api

# SARIF output ile
warden spec analyze --config .warden/config.yaml --sarif --output report.sarif

# Verbose mode
warden spec analyze --config .warden/config.yaml --verbose
```

### `warden spec extract`

Tek bir platformdan contract çıkarır:

```bash
# React projesinden extract
warden spec extract --path ./src --platform react

# Output dosyasına yaz
warden spec extract --path ./src --platform spring --output contract.yaml

# Verbose mode
warden spec extract --path ./src --platform flutter --verbose
```

### `warden spec list`

Desteklenen platformları listeler:

```bash
warden spec list

# Output:
# Supported Platforms:
#
# Consumer (Frontend):
#   - flutter: Flutter/Dart (Retrofit, Dio)
#   - react: React (Axios, Fetch, React Query)
#   - angular: Angular (HttpClient)
#   - vue: Vue.js (Axios)
#
# Provider (Backend):
#   - express: Express.js
#   - go: Go (Gin, Echo)
#   - spring: Spring Boot (Java/Kotlin)
#   - fastapi: FastAPI (Python)
#   - aspnetcore: ASP.NET Core
#   - nestjs: NestJS (TypeScript)
```

## Frame Dependency

```python
class SpecFrame(ValidationFrame):
    requires_frames = ["architectural"]  # Architectural frame önce çalışmalı
    requires_config = ["platforms"]      # platforms config zorunlu
```

## Test Coverage

### Unit Tests

```
tests/validation/frames/spec/
├── __init__.py
├── test_extractors.py    # 18 test - Extractor coverage
└── test_analyzer.py      # 22 test - Gap analysis coverage
```

**Test Kategorileri:**

| Kategori | Test Sayısı | Kapsam |
|----------|-------------|--------|
| Extractor Registry | 3 | Registry işlemleri |
| React Extractor | 3 | Axios, Fetch, React Query |
| Express Extractor | 2 | Routes |
| Go Extractor | 2 | Gin, Echo |
| Flutter Extractor | 2 | Retrofit, Dio |
| Spring Boot Extractor | 2 | Java, Kotlin |
| FastAPI Extractor | 1 | Python routes |
| ASP.NET Core Extractor | 2 | Controllers |
| NestJS Extractor | 1 | Decorators |
| Operation Matching | 4 | Exact, normalized, fuzzy |
| Type Checking | 3 | Input, output, compatibility |
| Model Comparison | 3 | Fields, types, optionality |
| Enum Comparison | 2 | Missing, extra values |
| Configuration | 2 | Custom severity, disable checks |
| Edge Cases | 4 | Empty, consumer-only, provider-only |

## Dosya Yapısı

```
src/warden/validation/frames/spec/
├── __init__.py
├── spec_frame.py              # Ana frame sınıfı
├── models.py                  # Contract, Operation, Model, Enum tanımları
├── analyzer.py                # GapAnalyzer
├── report.py                  # SARIF report generator
└── extractors/
    ├── __init__.py            # Registry ve exports
    ├── base.py                # BaseContractExtractor
    ├── flutter_extractor.py   # Flutter/Dart
    ├── react_extractor.py     # React
    ├── angular_extractor.py   # Angular
    ├── vue_extractor.py       # Vue.js
    ├── express_extractor.py   # Express.js
    ├── go_extractor.py        # Go (Gin, Echo)
    ├── springboot_extractor.py # Spring Boot
    ├── fastapi_extractor.py   # FastAPI
    ├── aspnetcore_extractor.py # ASP.NET Core
    └── nestjs_extractor.py    # NestJS

src/warden/shared/infrastructure/
└── resilience.py              # Resilience patterns (shared)

tests/validation/frames/spec/
├── __init__.py
├── test_extractors.py
└── test_analyzer.py
```

## Örnek Senaryo

### 1. Flutter Mobile + Spring Boot Backend

**Flutter kodu (Consumer):**
```dart
@RestApi(baseUrl: "/api")
abstract class ApiClient {
  @GET("/users")
  Future<List<UserDto>> getUsers();

  @POST("/users")
  Future<UserDto> createUser(@Body() CreateUserRequest request);

  @GET("/users/{id}")
  Future<UserDto> getUser(@Path("id") int id);
}
```

**Spring Boot kodu (Provider):**
```java
@RestController
@RequestMapping("/api")
public class UserController {

    @GetMapping("/users")
    public List<UserDto> getAllUsers() { ... }

    @PostMapping("/users")
    public UserDto createUser(@RequestBody CreateUserRequest request) { ... }

    // getUser endpoint eksik!
}
```

**Spec Frame Output:**
```
Gap Analysis Results:
─────────────────────
Consumer: mobile (flutter)
Provider: backend (spring)

CRITICAL: Operation 'getUser' expected by consumer but not found in provider
  Location: lib/api/api_client.dart:12
  Similar operations in provider: getAllUsers, createUser

Summary:
  - Matched: 2
  - Missing: 1 (CRITICAL)
  - Unused: 0
```

## CI/CD Entegrasyonu

### GitHub Actions

```yaml
name: API Contract Validation

on: [push, pull_request]

jobs:
  spec-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Run Warden Spec Analysis
        run: |
          warden spec analyze \
            --config .warden/config.yaml \
            --sarif \
            --output results.sarif

      - name: Upload SARIF to GitHub
        uses: github/codeql-action/upload-sarif@v2
        with:
          sarif_file: results.sarif
```

## Gelecek Geliştirmeler

| Özellik | Öncelik | Durum |
|---------|---------|-------|
| GraphQL desteği | HIGH | Planned |
| gRPC desteği | HIGH | Planned |
| OpenAPI export | MEDIUM | Planned |
| Contract versioning | MEDIUM | Planned |
| Breaking change detection | HIGH | Planned |
| Auto-fix suggestions | LOW | Planned |

## Katkıda Bulunma

Yeni extractor eklemek için:

1. `extractors/` altında yeni dosya oluştur
2. `BaseContractExtractor`'dan inherit et
3. `@ExtractorRegistry.register` decorator kullan
4. `extract()` metodunu implement et
5. `__init__.py`'a import ekle
6. Test yaz

```python
@ExtractorRegistry.register
class MyExtractor(BaseContractExtractor):
    platform_type = PlatformType.MY_PLATFORM
    supported_languages = [CodeLanguage.TYPESCRIPT]
    file_patterns = ["**/*.ts"]

    async def extract(self) -> Contract:
        # Implementation
        pass
```
