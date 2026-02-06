# Circular Import Refactoring Plan

## Executive Summary

This document outlines circular import issues in the Warden Core codebase and provides a refactoring plan to establish clean layer separation following Domain-Driven Design (DDD) principles.

## Current State Analysis

### Identified Issues

1. **Function-Level Imports**: Extensive use of imports inside functions indicates circular dependencies
   - Found in 48+ files across the codebase
   - Most common in CLI commands, services, and phase executors

2. **Cross-Layer Dependencies**: Violations of clean architecture principles
   - Application layer importing from infrastructure
   - Domain layer depending on application layer
   - CLI commands tightly coupled with internal services

3. **Common Circular Import Patterns**:
   - `validation.domain.frame` <-> `validation.domain.check`
   - `pipeline.application.orchestrator` <-> `pipeline.application.executors.*`
   - `cli.commands.*` <-> `services.*` <-> `validation.*`
   - `grpc.servicer` <-> `shared.services`

## Target Architecture

### Layer Structure

```
┌─────────────────────────────────────────┐
│           CLI / Presentation            │  (main.py, cli/, grpc/)
├─────────────────────────────────────────┤
│           Application Layer             │  (orchestrators, phases, services)
├─────────────────────────────────────────┤
│             Domain Layer                │  (models, enums, interfaces)
├─────────────────────────────────────────┤
│         Infrastructure Layer            │  (adapters, repositories, external)
└─────────────────────────────────────────┘
```

### Dependency Rules

1. **Domain Layer**
   - No dependencies on other layers
   - Pure Python models, enums, protocols
   - Business logic only

2. **Application Layer**
   - Depends on Domain only
   - Contains use cases, services, orchestration
   - Should use interfaces from Domain

3. **Infrastructure Layer**
   - Depends on Domain (interfaces)
   - Implements adapters, repositories
   - External integrations (LLM, AST, LSP)

4. **CLI/Presentation Layer**
   - Depends on Application and Domain
   - Handles user interaction
   - Uses application services

## Refactoring Strategy

### Phase 1: Domain Layer Cleanup (Priority: High)

**Goal**: Make domain layer completely independent

**Tasks**:

1. **Extract Pure Models**
   ```python
   # Current (BAD)
   # validation/domain/frame.py imports from validation/domain/check.py

   # Target (GOOD)
   # validation/domain/models/frame.py - pure model
   # validation/domain/models/check.py - pure model
   # validation/domain/models/__init__.py - exports all
   ```

2. **Define Clear Interfaces**
   ```python
   # domain/interfaces.py or protocols.py
   from typing import Protocol

   class IFrameExecutor(Protocol):
       async def execute(self, file: CodeFile) -> FrameResult: ...

   class ILLMClient(Protocol):
       async def complete_async(self, prompt: str) -> LlmResponse: ...
   ```

3. **Move Business Logic to Services**
   - Extract validation logic from domain models
   - Create domain services for complex operations

**Files to Refactor**:
- `validation/domain/frame.py`
- `validation/domain/check.py`
- `rules/domain/models.py`
- `issues/domain/models.py`

### Phase 2: Application Layer Restructure (Priority: Medium)

**Goal**: Decouple application services and orchestrators

**Tasks**:

1. **Dependency Injection Pattern**
   ```python
   # Before
   class CleaningPhase:
       def __init__(self):
           from warden.shared.services import LLMService  # BAD
           self.llm = LLMService()

   # After
   class CleaningPhase:
       def __init__(self, llm_client: ILLMClient):
           self.llm = llm_client
   ```

2. **Factory Pattern for Complex Objects**
   ```python
   # application/factories/orchestrator_factory.py
   class OrchestratorFactory:
       @staticmethod
       def create(config: Config) -> PhaseOrchestrator:
           llm_client = LLMClientFactory.create(config.llm)
           rate_limiter = RateLimiterFactory.create(config.rate_limits)
           return PhaseOrchestrator(llm_client, rate_limiter)
   ```

3. **Event-Based Communication**
   - Replace direct coupling with events
   - Use observer pattern for phase coordination

**Files to Refactor**:
- `pipeline/application/orchestrator/*`
- `pipeline/application/executors/*`
- `analysis/application/*`
- `cleaning/application/*`
- `classification/application/*`
- `fortification/application/*`

### Phase 3: Infrastructure Isolation (Priority: Medium)

**Goal**: Isolate external dependencies and implementations

**Tasks**:

1. **Adapter Pattern for External Services**
   ```python
   # infrastructure/adapters/llm/
   ├── base.py (ILLMAdapter interface)
   ├── openai_adapter.py
   ├── azure_adapter.py
   └── ollama_adapter.py
   ```

2. **Repository Pattern for Data Access**
   ```python
   # infrastructure/repositories/
   ├── issue_repository.py
   ├── baseline_repository.py
   └── memory_repository.py
   ```

3. **Configuration as Dependencies**
   - Move all config loading to startup
   - Inject config objects, not config loaders

**Files to Refactor**:
- `llm/providers/*`
- `semantic_search/adapters.py`
- `lsp/*`
- `ast/providers/*`

### Phase 4: CLI/Presentation Decoupling (Priority: Low)

**Goal**: Make CLI a thin layer over application services

**Tasks**:

1. **Command Handler Pattern**
   ```python
   # cli/handlers/scan_handler.py
   class ScanCommandHandler:
       def __init__(self, orchestrator: PhaseOrchestrator):
           self.orchestrator = orchestrator

       async def handle(self, args: ScanArgs) -> ScanResult:
           return await self.orchestrator.execute(args)
   ```

2. **Facade Pattern for Bridge**
   - Simplify WardenBridge API
   - Hide internal complexity

3. **Remove Direct Service Access**
   - CLI should not import from `services/`
   - Use application layer facades

**Files to Refactor**:
- `cli/commands/*`
- `cli_bridge/bridge.py`
- `grpc/servicer/*`

## Implementation Roadmap

### Sprint 1 (Week 1-2): Domain Foundation
- [ ] Create `domain/interfaces.py` with all protocols
- [ ] Extract pure models from domain layer
- [ ] Remove all cross-layer imports from domain
- [ ] Write tests for domain models

### Sprint 2 (Week 3-4): Application Services
- [ ] Implement dependency injection in orchestrator
- [ ] Create factory classes for complex objects
- [ ] Refactor phase executors to use interfaces
- [ ] Update tests

### Sprint 3 (Week 5-6): Infrastructure Adapters
- [ ] Create adapter interfaces
- [ ] Implement LLM adapters
- [ ] Implement repository pattern
- [ ] Update integration tests

### Sprint 4 (Week 7-8): CLI Cleanup
- [ ] Create command handlers
- [ ] Refactor CLI commands
- [ ] Update gRPC servicer
- [ ] End-to-end testing

## Quick Wins (Can Start Immediately)

1. **Replace Function-Level Imports in CLI**
   - Move imports to top of file
   - Use TYPE_CHECKING for type hints only

2. **Extract Common Interfaces**
   - Create `shared/domain/interfaces.py`
   - Define ILLMClient, IFrameExecutor, IValidator

3. **Consolidate Rate Limiter Usage**
   - Already centralized in bridge.py
   - Ensure all phases use injected instance

## Testing Strategy

### Unit Tests
- Test each layer independently
- Mock dependencies at layer boundaries
- Achieve 80%+ coverage

### Integration Tests
- Test layer interactions
- Use test doubles for external services
- Validate interface contracts

### Refactoring Tests
- Create characterization tests before refactoring
- Ensure behavior doesn't change
- Run tests after each refactoring step

## Success Metrics

1. **Zero circular imports** when running:
   ```bash
   python -m pydeps src/warden --show-cycles
   ```

2. **Clean import structure**:
   - Domain: 0 imports from app/infra/cli
   - Application: Only domain imports
   - Infrastructure: Domain interfaces only

3. **Improved maintainability**:
   - Easier to add new features
   - Simpler testing
   - Better IDE support

## Notes

### Why Function-Level Imports Exist

1. **Circular Dependencies**: Most common reason
2. **Import Time Side Effects**: Some modules have heavy initialization
3. **Optional Dependencies**: Some imports are conditional (e.g., Rust bindings)
4. **Legacy Code**: Technical debt from rapid development

### Migration Strategy

- **Gradual refactoring**: Don't break existing functionality
- **Feature flags**: Use flags to switch between old and new implementations
- **Parallel implementations**: Keep old code until new code is stable
- **Incremental testing**: Test each change independently

## References

- [Python Circular Imports](https://docs.python.org/3/faq/programming.html#what-are-the-best-practices-for-using-import-in-a-module)
- [Clean Architecture by Robert C. Martin](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [Domain-Driven Design Patterns](https://martinfowler.com/bliki/DomainDrivenDesign.html)

## Appendix: High-Priority Files

### Top 20 Files with Function-Level Imports

1. `cli/commands/init.py` (20+ function-level imports)
2. `cli/commands/baseline.py` (5+ function-level imports)
3. `cli/commands/config.py` (3+ function-level imports)
4. `cleaning/application/cleaning_phase.py`
5. `analysis/services/linter_service.py`
6. `grpc/servicer/*.py` (multiple files)
7. `shared/services/semantic_search_service.py`
8. `services/package_manager/*.py` (multiple files)
9. `validation/frames/fuzz/fuzz_frame.py`
10. `infrastructure/installer.py`

Start with these files for maximum impact.
