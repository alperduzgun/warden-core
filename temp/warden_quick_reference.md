# Warden Quick Reference - Core Concepts & Current Status
> **Purpose:** Essential Warden concepts and implementation status
> **Last Updated:** December 27, 2024
> **Migration Status:** ~65% Complete

---

## 🎯 VISION

### Problem
```
2024+ World: Developer → AI generates code → "looks good" → merge
Result: Untested, fragile code reaches production
```

### Solution: Warden
```
"AI writes code. Warden guards production."

Developer → AI generates code → WARDEN validates → Safe PR
```

### Motto
> "Happy path is a myth. Warden proves your code survives reality."

---

## 🔄 6-PHASE PIPELINE

```
[0. PRE-ANALYSIS] → [1. ANALYSIS] → [2. CLASSIFICATION]
→ [3. VALIDATION] → [4. FORTIFICATION] → [5. CLEANING]
```

### Implementation Status

| Phase | Status | Key Components | Next Action |
|-------|--------|---------------|-------------|
| **PRE-ANALYSIS** | ✅ 100% | `project_structure_analyzer.py` (498 lines)<br>`framework_detector.py` (146 lines)<br>`convention_detector.py` (176 lines) | Complete |
| **ANALYSIS** | ⚠️ 60% | `analysis_phase.py` (484 lines)<br>`llm_analysis_phase.py` (401 lines) | LLM integration |
| **CLASSIFICATION** | ⚠️ 40% | Basic frame selection | Context sharing |
| **VALIDATION** | ✅ 90% | All 7 frames working<br>`llm_validator.py` (236 lines) | Working |
| **FORTIFICATION** | ❌ 10% | Directory structure only | Implement generator |
| **CLEANING** | ❌ 10% | Directory structure only | Implement analyzer |

---

## 🧠 CORE PRINCIPLES

```yaml
philosophy:
  - "Working" ≠ "Production-ready"
  - AI code is untrusted until proven
  - Warden reports but NEVER modifies code
  - Fail fast, fail loud, fail safe

principles:
  - KISS: Keep It Simple, Stupid
  - DRY: Don't Repeat Yourself
  - SOLID: Single responsibility principles
  - YAGNI: You Aren't Gonna Need It

safety_rules:
  - 500 lines max per file
  - Type hints everywhere
  - async/await for I/O
  - Thread-safe operations
  - Assume ALL inputs are malicious
```

---

## 🔬 VALIDATION FRAMES (7 Active)

### Working Frames
1. **SecurityFrame** ✅ - SQL injection, XSS, secrets
2. **ChaosFrame** ✅ - Network failures, timeouts
3. **OrphanFrame** ✅ - Unused code detection
4. **ArchitecturalFrame** ✅ - SOLID principles, file organization
5. **StressFrame** ✅ - Load testing, memory leaks
6. **env-security** ✅ - Custom frame for environment security
7. **demo-security** ✅ - Custom frame for demo validation

### Frame Architecture
```python
# All frames operational with:
- Parallel execution
- Priority ordering
- LLM false positive detection
- Thread-safe PipelineContext
```

---

## 🏗️ CURRENT ARCHITECTURE

### Python Project Structure
```
warden-core/                        # PROJECT_ROOT
├── src/warden/
│   ├── analysis/                  ✅ 100% Complete
│   │   └── application/
│   │       ├── project_structure_analyzer.py
│   │       ├── framework_detector.py
│   │       └── statistics_collector.py
│   │
│   ├── validation/                ✅ 90% Complete
│   │   ├── frames/               # All 7 frames working
│   │   └── infrastructure/
│   │       └── llm_validator.py  # False positive detection
│   │
│   ├── pipeline/                  ⚠️ 50% Needs integration
│   │   └── domain/
│   │       └── pipeline_context.py  # Thread-safe context
│   │
│   ├── fortification/             ❌ 10% TODO
│   ├── cleaning/                  ❌ 10% TODO
│   └── llm/                       ✅ Azure OpenAI integrated
│
├── cli/                           ✅ TypeScript/React Ink CLI
├── examples/                      # Test files
└── .warden/
    ├── config.yaml               # Production config
    └── rules.yaml                # Validation rules
```

---

## 📦 KEY MODELS & FILES

### Working Examples
```python
# Thread-safe context sharing
pipeline_context.py (355 lines) ✅

# Modular PRE-ANALYSIS
project_structure_analyzer.py (498 lines) ✅
framework_detector.py (146 lines) ✅

# LLM Integration
llm_validator.py (236 lines) ✅
```

### Need Refactoring (>500 lines)
```python
orchestrator.py (728 lines) ⚠️
file_context_analyzer.py (544 lines) ⚠️
llm_context_analyzer.py (579 lines) ⚠️
```

---

## 🔧 CONFIGURATION

### Current Production Config
```yaml
# .warden/config.yaml
settings:
  enable_pre_analysis: true
  pre_analysis_config:
    use_llm: true  # Enabled for production

llm:
  provider: azure_openai
  model: gpt-4o

frames:
  - security      # ✅
  - chaos        # ✅
  - orphan       # ✅
  - architectural # ✅
  - stress       # ✅
  - env-security # ✅ Custom
  - demo-security # ✅ Custom
```

### Environment Variables
```bash
AZURE_OPENAI_API_KEY=xxx
AZURE_OPENAI_ENDPOINT=https://xxx.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
```

---

## 🎯 PRIORITY TASKS

### High Priority
1. **Connect pipeline phases** - Share PipelineContext
2. **Implement FORTIFICATION** - LLM fix generation
3. **Implement CLEANING** - Pattern analysis

### Medium Priority
4. **Split large files** - orchestrator.py (728→<500)
5. **Fix async naming** - Add _async suffix
6. **Complete ANALYSIS** - LLM integration

### Low Priority
7. **Memory system** - mem0 integration
8. **Test coverage** - Currently ~60%

---

## ⚠️ CRITICAL RULES

### 1. Panel is Source of Truth
```
Priority: Panel TypeScript > Python Standards > C# Legacy
```

### 2. JSON Compatibility
```python
# Python internal: snake_case
file_path: str

# JSON to Panel: camelCase
{"filePath": "test.py"}

# Every model needs:
def to_json() -> dict  # → camelCase
def from_json(data: dict)  # ← camelCase
```

### 3. File Size Limit
```
MAX: 500 lines per file
Current violations: 3 files
```

### 4. Async Convention
```python
# ✅ GOOD
async def analyze_async()

# ❌ BAD
async def analyze()
```

---

## 📊 QUALITY METRICS

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Pipeline Complete | 100% | 65% | ⚠️ |
| False Positive Rate | <5% | ~5% | ✅ |
| File Size Compliance | 500 lines | 3 violations | ⚠️ |
| Async Naming | 100% | 95% | ⚠️ |
| Thread Safety | Yes | Yes | ✅ |
| LLM Integration | Full | Partial | ⚠️ |

---

## 🚀 QUICK COMMANDS

### Working Commands
```bash
# Analyze a file
warden analyze examples/vulnerable_code.py

# Run validation
warden validate examples/test_warden_with_llm.py

# Scan directory
warden scan src/

# Specific frame
warden validate --frame security examples/vulnerable_code.py
```

### CLI Development
```bash
# TypeScript CLI
cd cli/
npm run dev
```

---

## 📚 KEY DOCUMENTS

| Document | Purpose | Status |
|----------|---------|--------|
| `WARDEN_COMPLETE_STATUS.md` | Full project status | Primary |
| `session-start.md` | Session guide | Updated |
| `warden_core_rules.md` | Python standards | Active |
| `warden_quick_reference.md` | This file | Updated |

---

## 🔗 RELATED PROJECTS

- **warden-panel-development** - TypeScript UI (source of truth for types)
- **warden-csharp** - C# legacy (reference only, not to copy)

---

**Last Updated:** December 27, 2024
**Status:** ACTIVE - Quick reference for development
**Full Details:** See `WARDEN_COMPLETE_STATUS.md` for comprehensive information