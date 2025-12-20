# Warden Core - Python Modular Monolith Architecture

> **Design Philosophy:** Domain-driven modular monolith with Panel TypeScript types as source of truth

**Last Updated:** 2025-12-20
**Status:** Architecture Design - Ready for Implementation

---

## 🎯 Architecture Principles

### 1. Modular Monolith
- **NOT a microservices architecture**
- **NOT a layered monolith** (no generic "services", "repositories" folders)
- **YES to domain-driven modules** - each module is a business capability
- **Single deployable unit** but with clear module boundaries
- Modules can be extracted to microservices later if needed

### 2. Domain-Driven Design (DDD)
- Organize by **business capability**, not technical layer
- Each module has its own models, services, repositories
- Clear module boundaries with well-defined interfaces
- No cross-module database access (use public APIs)

### 3. Panel-First Approach
- **SOURCE OF TRUTH:** Panel TypeScript types (`/warden-panel-development/src/lib/types/`)
- Python models MUST serialize to/from Panel JSON format (camelCase)
- Enum values MUST match Panel exactly
- Date format: ISO 8601

### 4. Python Best Practices
- Type hints everywhere (`typing`, `pydantic`)
- Max 500 lines per file (strict limit)
- Async/await for I/O operations
- Dependency injection (FastAPI `Depends`)
- Comprehensive testing (pytest)

---

## 📦 Module Structure

```
warden-core/
├── src/
│   └── warden/
│       ├── __init__.py
│       │
│       ├── shared/                    # Shared kernel (cross-module)
│       │   ├── __init__.py
│       │   ├── domain/                # Base domain models
│       │   │   ├── __init__.py
│       │   │   ├── base_model.py     # BaseDomainModel (with to_json/from_json)
│       │   │   └── value_objects.py  # FilePath, CodeHash, etc.
│       │   ├── infrastructure/        # Shared infra
│       │   │   ├── __init__.py
│       │   │   ├── logging.py        # Structlog setup
│       │   │   ├── config.py         # Settings (pydantic-settings)
│       │   │   └── exceptions.py     # Base exceptions
│       │   └── utils/
│       │       ├── __init__.py
│       │       ├── json_utils.py     # camelCase ↔ snake_case conversion
│       │       └── date_utils.py     # ISO 8601 helpers
│       │
│       ├── issues/                    # ISSUES DOMAIN MODULE
│       │   ├── __init__.py
│       │   ├── domain/                # Domain layer
│       │   │   ├── __init__.py
│       │   │   ├── models.py         # WardenIssue, StateTransition
│       │   │   ├── enums.py          # IssueSeverity, IssueState
│       │   │   └── events.py         # IssueCreated, IssueResolved (optional)
│       │   ├── application/           # Application services
│       │   │   ├── __init__.py
│       │   │   ├── issue_service.py  # IssueService (business logic)
│       │   │   └── filters.py        # IssueFilters, Pagination
│       │   ├── infrastructure/        # Infrastructure
│       │   │   ├── __init__.py
│       │   │   ├── repository.py     # IssueRepository (file-based or DB)
│       │   │   └── persistence.py    # JSON file I/O
│       │   └── api/                   # API endpoints
│       │       ├── __init__.py
│       │       ├── routes.py         # FastAPI routes for issues
│       │       └── schemas.py        # Request/response schemas
│       │
│       ├── pipeline/                  # PIPELINE DOMAIN MODULE
│       │   ├── __init__.py
│       │   ├── domain/
│       │   │   ├── __init__.py
│       │   │   ├── models.py         # PipelineRun, Step, SubStep
│       │   │   ├── enums.py          # StepStatus, StepType, SubStepType
│       │   │   └── summary.py        # PipelineSummary
│       │   ├── application/
│       │   │   ├── __init__.py
│       │   │   ├── pipeline_service.py    # PipelineOrchestrator
│       │   │   └── step_executor.py       # Step execution logic
│       │   ├── infrastructure/
│       │   │   ├── __init__.py
│       │   │   └── repository.py     # Pipeline run persistence
│       │   └── api/
│       │       ├── __init__.py
│       │       └── routes.py         # Pipeline API routes
│       │
│       ├── validation/                # VALIDATION DOMAIN MODULE
│       │   ├── __init__.py
│       │   ├── domain/
│       │   │   ├── __init__.py
│       │   │   ├── frame.py          # ValidationFrame (base class)
│       │   │   ├── enums.py          # FrameCategory, FramePriority
│       │   │   └── results.py        # ValidationFrameResult, TestResult
│       │   ├── frames/                # Validation frame implementations
│       │   │   ├── __init__.py
│       │   │   ├── security_frame.py      # Security validation
│       │   │   ├── chaos_frame.py         # Chaos engineering
│       │   │   ├── fuzz_frame.py          # Fuzz testing
│       │   │   ├── property_frame.py      # Property-based testing
│       │   │   ├── stress_frame.py        # Stress testing
│       │   │   └── architectural_frame.py # Architectural checks
│       │   ├── application/
│       │   │   ├── __init__.py
│       │   │   ├── frame_executor.py      # Parallel frame execution
│       │   │   └── frame_selector.py      # Select frames based on code type
│       │   └── api/
│       │       ├── __init__.py
│       │       └── routes.py         # Validation API routes
│       │
│       ├── analysis/                  # ANALYSIS DOMAIN MODULE
│       │   ├── __init__.py
│       │   ├── domain/
│       │   │   ├── __init__.py
│       │   │   ├── models.py         # AnalysisResult, CodeCharacteristics
│       │   │   └── classifiers.py    # Code classification logic
│       │   ├── application/
│       │   │   ├── __init__.py
│       │   │   ├── analyzer.py       # CodeAnalyzer service
│       │   │   └── classifier.py     # CodeClassifier service
│       │   ├── infrastructure/
│       │   │   ├── __init__.py
│       │   │   ├── ast_parser.py     # AST parsing (tree-sitter)
│       │   │   └── llm_client.py     # LLM integration (DeepSeek/OpenAI)
│       │   └── api/
│       │       ├── __init__.py
│       │       └── routes.py
│       │
│       ├── memory/                    # MEMORY DOMAIN MODULE
│       │   ├── __init__.py
│       │   ├── domain/
│       │   │   ├── __init__.py
│       │   │   ├── models.py         # MemoryEntry, MemoryType
│       │   │   └── embeddings.py     # Embedding models
│       │   ├── application/
│       │   │   ├── __init__.py
│       │   │   ├── memory_service.py      # Memory CRUD operations
│       │   │   └── context_builder.py     # Build context from memory
│       │   ├── infrastructure/
│       │   │   ├── __init__.py
│       │   │   ├── qdrant_client.py       # Qdrant vector DB client
│       │   │   └── embedding_service.py   # OpenAI/Azure embeddings
│       │   └── api/
│       │       ├── __init__.py
│       │       └── routes.py
│       │
│       ├── projects/                  # PROJECTS DOMAIN MODULE
│       │   ├── __init__.py
│       │   ├── domain/
│       │   │   ├── __init__.py
│       │   │   ├── models.py         # Project, ProjectSummary, ProjectDetail
│       │   │   └── enums.py          # ProjectStatus, QualityTrend
│       │   ├── application/
│       │   │   ├── __init__.py
│       │   │   └── project_service.py
│       │   ├── infrastructure/
│       │   │   ├── __init__.py
│       │   │   └── repository.py
│       │   └── api/
│       │       ├── __init__.py
│       │       └── routes.py
│       │
│       ├── reports/                   # REPORTS DOMAIN MODULE
│       │   ├── __init__.py
│       │   ├── domain/
│       │   │   ├── __init__.py
│       │   │   ├── models.py         # GuardianReport, DashboardMetrics
│       │   │   └── aggregations.py   # Report aggregation logic
│       │   ├── application/
│       │   │   ├── __init__.py
│       │   │   └── report_service.py
│       │   ├── infrastructure/
│       │   │   ├── __init__.py
│       │   │   └── repository.py
│       │   └── api/
│       │       ├── __init__.py
│       │       └── routes.py
│       │
│       ├── rules/                     # CUSTOM RULES DOMAIN MODULE
│       │   ├── __init__.py
│       │   ├── domain/
│       │   │   ├── __init__.py
│       │   │   ├── models.py         # CustomRule, RuleViolation
│       │   │   └── enums.py          # RuleCategory, RuleSeverity
│       │   ├── application/
│       │   │   ├── __init__.py
│       │   │   ├── rule_engine.py    # Rule evaluation engine
│       │   │   └── yaml_loader.py    # Load .warden/rules.yaml
│       │   ├── infrastructure/
│       │   │   ├── __init__.py
│       │   │   └── repository.py
│       │   └── api/
│       │       ├── __init__.py
│       │       └── routes.py
│       │
│       └── api/                       # API COMPOSITION LAYER
│           ├── __init__.py
│           ├── main.py               # FastAPI app factory
│           ├── dependencies.py       # Shared dependencies
│           └── middleware.py         # Logging, CORS, etc.
│
├── tests/                            # Tests mirror src structure
│   ├── __init__.py
│   ├── shared/
│   ├── issues/
│   ├── pipeline/
│   ├── validation/
│   ├── analysis/
│   ├── memory/
│   ├── projects/
│   ├── reports/
│   ├── rules/
│   └── integration/                  # Integration tests
│
├── docs/                             # Documentation
│   ├── architecture.md
│   ├── api.md
│   └── deployment.md
│
├── scripts/                          # Utility scripts
│   ├── dev_server.py
│   └── migrate_data.py
│
├── pyproject.toml                    # Poetry project config
├── README.md
├── .env.example
└── .gitignore
```

---

## 🔗 Module Dependencies

### Dependency Rules
1. **Shared module** - No dependencies on other modules (pure shared kernel)
2. **Domain modules** - Can depend on `shared` only
3. **API composition layer** - Composes all domain modules
4. **NO circular dependencies** between domain modules

### Allowed Dependencies
```
shared ← issues
shared ← pipeline
shared ← validation
shared ← analysis
shared ← memory
shared ← projects
shared ← reports
shared ← rules

api ← all domain modules
```

### Inter-Module Communication
- Modules communicate via **public application services** (dependency injection)
- NO direct access to another module's infrastructure/repository
- Use domain events for loose coupling (optional, future enhancement)

---

## 📊 Data Flow Architecture

### 1. Issue Detection Flow
```
User/CI → API → Pipeline Service → Analysis Service → Validation Frames → Issue Service → Repository → .warden/issues.json
```

### 2. Panel Integration Flow
```
Panel (Svelte) → FastAPI REST → Issue Service → to_json() → camelCase JSON → Panel
Panel (Svelte) → POST → Issue Service → from_json() → Python model → Business logic
```

### 3. Memory-Enhanced Analysis Flow
```
Pipeline → Memory Service → Qdrant → Project context → Analysis Service → LLM (with context)
```

---

## 🛠️ Technology Stack

### Core
- **Python:** 3.11+
- **Framework:** FastAPI (async, automatic OpenAPI docs)
- **DI Container:** FastAPI `Depends` (built-in)
- **Validation:** Pydantic v2 (models, settings)

### Database
- **Vector DB:** Qdrant Cloud (memory/embeddings)
- **Primary Storage:** JSON files (`.warden/` directory) - Phase 1
- **Future:** PostgreSQL (multi-project, advanced queries) - Phase 2

### Infrastructure
- **Logging:** structlog (structured logging)
- **HTTP Client:** httpx (async)
- **File I/O:** aiofiles (async)
- **Testing:** pytest + pytest-asyncio + pytest-cov

### AI/ML
- **Embeddings:** OpenAI / Azure OpenAI
- **LLM:** DeepSeek / OpenAI / Groq (via SDK or HTTP)
- **AST Parsing:** tree-sitter (multi-language support)

### Dev Tools
- **Package Manager:** Poetry
- **Formatter:** black
- **Linter:** ruff
- **Type Checker:** mypy (strict mode)

---

## 🔐 Security & Quality

### Input Validation
- All API inputs validated via Pydantic models
- Path traversal prevention (`pathlib.Path` validation)
- SQL injection prevention (parameterized queries, if using DB)
- Command injection prevention (`shlex.quote`, no shell=True)

### Error Handling
- Fail fast with clear error messages
- Structured logging for all errors
- No sensitive data in error responses
- Correlation IDs for tracing

### Resource Management
- Context managers for all I/O (`async with`)
- Proper cleanup in `finally` blocks
- Connection pooling for Qdrant
- Rate limiting for LLM calls

---

## 📏 File Size Limits

**CRITICAL RULE:** Max 500 lines per Python file

### How to Stay Under Limit
1. **Split large modules:**
   ```
   # Instead of:
   issues/domain/models.py (800 lines)

   # Do:
   issues/domain/issue.py (300 lines)
   issues/domain/state_transition.py (200 lines)
   issues/domain/filters.py (200 lines)
   ```

2. **Extract helpers:**
   ```python
   # issues/domain/_helpers.py  (private module)
   def calculate_severity_score(severity: IssueSeverity) -> int:
       pass
   ```

3. **Use imports wisely:**
   ```python
   # issues/domain/__init__.py
   from .issue import WardenIssue
   from .enums import IssueSeverity, IssueState
   from .state_transition import StateTransition
   ```

---

## 🧪 Testing Strategy

### Test Structure
```
tests/
├── unit/                    # Unit tests (fast, isolated)
│   ├── issues/
│   ├── pipeline/
│   └── validation/
├── integration/             # Integration tests (DB, API)
│   ├── api/
│   └── persistence/
└── e2e/                     # End-to-end tests
    └── pipeline_flow_test.py
```

### Test Coverage Requirements
- **Minimum:** 80% coverage
- **Critical paths:** 100% coverage (security, payment, auth)
- **Panel JSON compatibility:** MUST have tests

### Panel Integration Tests
```python
# tests/integration/test_panel_json.py
def test_issue_json_roundtrip():
    """Ensure Panel can parse our JSON."""
    issue = WardenIssue(...)
    json_data = issue.to_json()

    # Panel expectations
    assert 'filePath' in json_data  # camelCase
    assert 'file_path' not in json_data  # NOT snake_case
    assert isinstance(json_data['severity'], int)  # NOT Enum

    # Roundtrip
    parsed = WardenIssue.from_json(json_data)
    assert parsed.file_path == issue.file_path
```

---

## 🚀 Development Workflow

### 1. Feature Development
```bash
# Create feature branch
git checkout -b feature/validation-frames

# Implement feature (follow module structure)
# - Write domain models (Panel-compatible)
# - Write application service (business logic)
# - Write infrastructure (Qdrant, file I/O)
# - Write API routes

# Write tests FIRST (TDD encouraged)
pytest tests/validation/

# Format & lint
black src/
ruff check src/

# Type check
mypy src/

# Commit
git add .
git commit -m "feat(validation): Implement security frame"
```

### 2. Panel Integration Check
```bash
# Before merging, verify Panel compatibility
pytest tests/integration/test_panel_json.py -v
```

### 3. Memory Management
```bash
# Save progress to memory (session continuity)
/mem-save "Warden Core: Implemented security frame. Panel JSON tested. Next: Chaos frame."
```

---

## 📦 Deployment Architecture

### Phase 1: Single Server (MVP)
```
Docker Container:
  - FastAPI (uvicorn)
  - Qdrant (local or cloud)
  - Nginx (reverse proxy)
```

### Phase 2: Scalable (Production)
```
Load Balancer
  ↓
  ├─ FastAPI Instance 1
  ├─ FastAPI Instance 2
  └─ FastAPI Instance N
  ↓
  ├─ Qdrant Cloud
  └─ PostgreSQL (multi-project data)
```

---

## 🎯 Implementation Priority

### Phase 1: Core Foundation (Week 1)
1. ✅ Shared kernel (base models, JSON utils, logging)
2. ✅ Issues module (WardenIssue, IssueService, API)
3. ✅ Projects module (Project, ProjectService, API)
4. ✅ Panel JSON compatibility tests

### Phase 2: Validation System (Week 2)
1. ✅ Validation module (frames, executor)
2. ✅ Security frame
3. ✅ Chaos frame
4. ✅ Fuzz frame
5. ✅ Property frame
6. ✅ Stress frame

### Phase 3: Pipeline Orchestration (Week 3)
1. ✅ Pipeline module (PipelineRun, Step, SubStep)
2. ✅ Analysis module (CodeAnalyzer, CodeClassifier)
3. ✅ Pipeline orchestrator (end-to-end flow)

### Phase 4: Memory & Reports (Week 4)
1. ✅ Memory module (Qdrant integration)
2. ✅ Reports module (GuardianReport, DashboardMetrics)
3. ✅ Custom rules module (YAML loader, rule engine)

---

## 🔄 Migration from C# to Python

### What to Migrate
- ✅ Business logic and concepts
- ✅ Validation strategies (frames)
- ✅ Memory system (Qdrant)
- ✅ Pipeline orchestration pattern

### What NOT to Migrate
- ❌ C# folder structure (use Python modular monolith instead)
- ❌ C# interfaces verbatim (use Python Protocols/ABCs)
- ❌ C# dependency injection (use FastAPI Depends)
- ❌ C# async patterns (use Python async/await)

### Panel-First Migration Rule
```
For each feature:
1. Check Panel TypeScript types (SOURCE OF TRUTH)
2. Implement Python model (Panel JSON compatible)
3. Test JSON serialization/deserialization
4. Implement business logic (refer to C# for general concepts only)
5. Write tests
```

---

**Status:** Architecture design complete - Ready for implementation
**Next:** Setup Python project structure and dependencies
