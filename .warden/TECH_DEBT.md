# Warden Technical Debt

This document tracks known technical debt items identified by Warden's self-scan.

## God Classes (500+ lines)

These classes exceed the recommended 500-line limit and should be refactored into smaller, focused components:

| Class | File | Lines | Priority | Suggested Action |
|-------|------|-------|----------|------------------|
| `WardenService` | grpc/generated/warden_pb2_grpc.py | 1386 | Low | Auto-generated, ignore |
| `FrameExecutor` | pipeline/application/orchestrator/frame_executor.py | 1044 | High | Split by responsibility |
| `PreAnalysisPhase` | analysis/application/pre_analysis_phase.py | 961 | High | Extract analyzers |
| `PhaseOrchestrator` | pipeline/application/orchestrator/orchestrator.py | 700 | Medium | Extract phase handlers |
| `ProjectStructureAnalyzer` | analysis/application/project_structure_analyzer.py | 682 | Medium | Extract parsers |
| `LlmContextAnalyzer` | analysis/application/llm_context_analyzer.py | 629 | Medium | Extract context builders |
| `BaselineManager` | cli/commands/helpers/baseline_manager.py | 560 | Medium | Extract storage/comparison |
| `FileContextAnalyzer` | analysis/application/file_context_analyzer.py | 561 | Medium | Extract extractors |
| `LLMPhaseBase` | analysis/application/llm_phase_base.py | 555 | Low | Base class, acceptable |
| `LanguageServerClient` | lsp/client.py | 548 | Medium | Extract protocol handlers |
| `LLMAnalysisPhase` | analysis/application/llm_analysis_phase.py | 543 | Medium | Inherits from base |
| `LLMClassificationPhase` | classification/application/llm_classification_phase.py | 540 | Medium | Inherits from base |
| `ProjectDetector` | config/project_detector.py | 507 | Medium | Extract language detectors |
| `FortificationPhase` | fortification/application/fortification_phase.py | 506 | Medium | Extract fixers |

### Refactoring Principles

When refactoring god classes:

1. **Single Responsibility**: Each class should have one reason to change
2. **Extract Strategy**: Use Strategy pattern for varying algorithms
3. **Extract Factory**: Use Factory pattern for object creation
4. **Composition over Inheritance**: Prefer composition for code reuse
5. **Interface Segregation**: Define focused interfaces

### Priority Guidelines

- **High**: Core pipeline components affecting performance/maintainability
- **Medium**: Feature modules with clear extraction paths
- **Low**: Auto-generated code or acceptable base classes

---

## Large Files (1000+ lines)

| File | Lines | Notes |
|------|-------|-------|
| grpc/generated/warden_pb2_grpc.py | 2529 | Auto-generated |
| validation/frames/antipattern/antipattern_frame.py | 1142 | Multi-language support |
| pipeline/application/orchestrator/frame_executor.py | 1078 | See god class above |
| services/ci_manager.py | 1046 | CI integration complexity |
| analysis/application/pre_analysis_phase.py | 1023 | See god class above |
| validation/frames/orphan/llm_orphan_filter.py | 1003 | LLM integration complexity |

---

## Scan Date

Last scanned: 2026-02-05
Scanned by: AntiPatternFrame v3.0.0 (Universal AST)
