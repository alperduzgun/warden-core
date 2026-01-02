# Warden Python Backend - Session Guide
> **Last Updated:** January 1, 2026
> **Code Completion:** ~71% ✅
> **Production Ready (as Core Framework):** ~75-80% ✅
> **Current Focus:** Framework Documentation & Extension System

## 📌 QUICK STATUS

| Component | Code Complete | Production Ready | Next Action |
|-----------|--------------|------------------|------------|
| **PRE-ANALYSIS** | ✅ 85% | ✅ 90% | Complete, LLM integrated |
| **ANALYSIS** | ✅ 80% | ✅ 85% | Quality metrics working |
| **CLASSIFICATION** | ✅ 70% | ⚠️ 70% | Core logic working |
| **VALIDATION** | ✅ 85% | ✅ 85% | 9+ frames operational |
| **FORTIFICATION** | ⚠️ 60% | ⚠️ 60% | Template-based, LLM optional |
| **CLEANING** | ⚠️ 65% | ⚠️ 65% | Pattern analyzer working |
| **Pipeline Context** | ✅ 95% | ✅ 95% | Phases connected |
| **LLM Integration** | ✅ 80% | ✅ 85% | Anthropic, Groq, DeepSeek working |
| **Multi-Language** | ❌ 40% | N/A | Python only (by design - extensible) |

## 📁 PROJECT PATHS

```bash
# This project (Python backend)
PROJECT_ROOT → /Users/alper/Documents/Development/Personal/warden-core

# Related projects (if needed for reference)
WARDEN_PANEL_PATH   → warden-panel-development (TypeScript UI - source of truth)
WARDEN_CSHARP_PATH  → warden-csharp (C# legacy - reference only)
```

---

## 📌 DEVELOPMENT CONTEXT (Claude Code için)

**NOT:** Bu proje uzun soluklu bir geliştirme. Kullanıcının local'inde mem0 kurulu ve Claude Code session'ları arasında context tutmak için kullanılıyor.

### 🚨 SESSION BAŞINDA İLK İŞ (ZORUNLU)

```bash
# 1. ÖNCE context'i yükle
/mem-context

# 2. Critical files'ı oku (3 dosya - MANDATORY!)
cat temp/session-start.md
cat temp/warden_core_rules.md
cat temp/warden_quick_reference.md

# 3. Gerekirse spesifik search
/mem-search "warden core"
```

**WHY:**
- Memory: Önceki session'da ne yapıldığını, hangi kararların alındığını hatırla!
- Critical Files: Migration rules, Python standards, C# Warden architecture'ını öğren!

### Kurallar:
1. **Session BAŞINDA `/mem-context` çalıştır** - Nerede kaldığını hatırla (MANDATORY!)
2. **Her önemli adımda `/mem-save` kullan** - Session arası context kaybolmasın
3. **Kararları kaydet** - Neden bu yolu seçtiğini unutma
4. **Blocker'ları kaydet** - Takıldığın yerleri not al

### Mem0 Commands
```bash
# Session başında
/mem-context                    # Load all relevant context
/mem-search "specific topic"    # Search for specific info

# Çalışma sırasında
/mem-save "Important decision or progress"

# Session sonunda
/mem-save "Session summary: completed X, next Y"
```

---

## 🎯 Current Mission
**CORE FRAMEWORK APPROACH**: Warden Core is an extensible framework where users can add their own AST providers and validation frames.

### Framework Status:
- **Core Pipeline:** ✅ 95% Complete and working
- **Extension System:** ✅ 90% Plugin architecture ready
- **Built-in Examples:** ✅ Python AST, 9 validation frames
- **Documentation:** ⚠️ 40% Needs extension developer docs

### Production Readiness Assessment:
- **As Monolithic Tool:** 55-60% (needs multi-language support)
- **As Core Framework:** 75-80% (ready for v1.0 with docs)
- **As Full Platform:** 90% (needs ecosystem, marketplace)

## ⚠️ CRITICAL PRINCIPLE: WARDEN IS A REPORTER, NOT A CODE MODIFIER

**Warden NEVER modifies code automatically!**
- ✅ Warden analyzes code
- ✅ Warden detects issues
- ✅ Warden generates reports with suggestions
- ❌ Warden does NOT auto-fix code
- ❌ Warden does NOT modify source files
- ❌ Warden does NOT apply patches

**LLM Usage:**
- LLM can provide better descriptions/explanations
- LLM can suggest fixes (as text recommendations)
- LLM does NOT generate modified code
- Final decision is ALWAYS with the developer

---

## 📁 Current Project Structure

### Python Backend (THIS PROJECT) - Actively Developed
```
warden-core/
├── src/warden/               # Main Python package
│   ├── analysis/            ✅ PRE-ANALYSIS phase (100% complete)
│   ├── validation/          ✅ All frames working (90% complete)
│   ├── classification/      ⚠️ Basic implementation (40%)
│   ├── fortification/       ❌ Structure only (10%)
│   ├── cleaning/            ❌ Structure only (10%)
│   ├── pipeline/            ⚠️ Context sharing needed (50%)
│   ├── llm/                 ✅ Azure OpenAI integrated
│   └── analyzers/           ✅ Additional analysis tools
│
├── cli/                     # TypeScript/React Ink CLI
│   ├── src/                ✅ Interactive CLI components
│   └── dist/               ✅ Compiled JavaScript
│
├── examples/               # Test files with vulnerabilities
├── .warden/               # Configuration files
│   ├── config.yaml        # LLM and frame settings
│   └── rules.yaml         # Validation rules
└── temp/                  # Documentation
    ├── WARDEN_COMPLETE_STATUS.md  # Main status document
    ├── session-start.md           # This file
    └── warden_core_rules.md       # Python standards
```

### Key Implementation Facts
```python
# Code Statistics:
- Total Python Code: 50,298 lines
- Total Files: 3,750
- Test Files: 134 (76 with actual test functions)
- Test Coverage: ~70%

# LLM Providers (REAL IMPLEMENTATIONS):
✅ Anthropic Claude - Full API, token tracking
✅ Groq - llama-3.1-70b-versatile
✅ DeepSeek - OpenAI compatible
⚠️ Tree-sitter AST - Stub (marked "not fully implemented")

# Validation Frames (9+ WORKING):
✅ Security (SQL injection, XSS detection)
✅ Chaos, Fuzz, Property, Stress
✅ Architectural, Orphan, GitChanges
✅ Custom frames via CheckRegistry

# Need Refactoring (>500 lines):
src/warden/pipeline/application/phase_orchestrator.py ⚠️ (775 lines)
```

---

## 🚨 CRITICAL RULE: Panel First, C# Second

### Feature Implementation Workflow
```
1. Feature ihtiyacı ortaya çıktığında
   ↓
2. /Users/ibrahimcaglar/warden-panel-development/src/lib/types/ kontrol et
   ↓
3. İlgili TypeScript type'ı bul (warden.ts, pipeline.ts, frame.ts)
   ↓
4. API_DESIGN.md'de API contract'ına bak
   ↓
5. .session-notes*.md'de implementation detaylarına bak
   ↓
6. Python'a çevir (TypeScript modellerini 1:1 Python'a map'le)
   ↓
7. SONRA (opsiyonel) C# koduna bakabilirsin (SECONDARY reference)
```

### Before Implementing ANY Feature - Checklist
```bash
# 1. Panel Types kontrol
cat <WARDEN_PANEL_PATH>/src/lib/types/warden.ts
cat <WARDEN_PANEL_PATH>/src/lib/types/pipeline.ts
cat <WARDEN_PANEL_PATH>/src/lib/types/frame.ts

# 2. API Design kontrol
cat <WARDEN_PANEL_PATH>/API_DESIGN.md

# 3. Latest Session Notes kontrol
cat <WARDEN_PANEL_PATH>/.session-notes*.md

# 4. C# (SADECE gerekirse - SECONDARY)
find <WARDEN_CSHARP_PATH>/src -name "*FeatureName*"
```

---

## 🎯 Feature Status Map

### Panel'de MEVCUT (Implemented ✅)

**1. Issues System**
- TypeScript: `warden.ts` - WardenIssue, IssueSeverity, IssueState
- Python Models: WardenIssue, IssueSeverity, IssueState, StateTransition

**2. Pipeline System**
- TypeScript: `pipeline.ts` - PipelineRun, Step, SubStep, ValidationTestDetails
- Python Models: PipelineRun, Step, SubStep, ValidationTestDetails, PipelineSummary

**3. Validation Frames (6 adet)**
- TypeScript: `frame.ts`
- Frames: Security, Chaos, Fuzz, Property, Stress, Architectural
- Python Models: ValidationFrame (base), TestResult, TestAssertion

**4. Custom Rules**
- TypeScript: `custom-rule.ts`
- Python Models: CustomRule

**5. Reports & Metrics**
- TypeScript: `warden.ts` - GuardianReport, DashboardMetrics
- Python Models: GuardianReport, DashboardMetrics

### Panel'de PLANNED (🔜)
- Multi-Project Support
- Real-Time Updates (WebSocket)
- User Authentication

### C#'de VAR ama Panel'de YOK (⚠️)
- AST Analysis (Multi-Language) → Python'da basit versiyonla başla
- Memory System (Qdrant) → Python'da implement et
- Training Data Export → Python'da ekle, Panel Phase 2'de gelecek

---

## 🔧 Translation Rules

### Naming Convention Rules

| Aspect | TypeScript/C# | Python |
|--------|---------------|--------|
| Class Name | PascalCase | PascalCase |
| Function/Method | camelCase | snake_case |
| Variable | camelCase | snake_case |
| Constant | UPPER_CASE | UPPER_CASE |
| Private Field | _fieldName | _field_name |
| Interface | ICodeAnalyzer | CodeAnalyzer (ABC/Protocol) |

### Type Mapping Rules

| TypeScript/C# | Python |
|---------------|--------|
| string | str |
| number | int / float |
| boolean | bool |
| Date | datetime |
| Array<T> / List<T> | List[T] |
| Dictionary<K,V> | Dict[K, V] |
| T? / T \| null | Optional[T] |
| 'a' \| 'b' \| 'c' | Literal['a', 'b', 'c'] |
| enum | Enum |
| interface | @dataclass / Protocol |

### Critical JSON Rules

**Rule 1: Panel JSON is camelCase, Python internal is snake_case**
- Python model field: `file_path: str`
- JSON to Panel: `"filePath": "test.py"`
- JSON from Panel: `"filePath"` → `file_path`

**Rule 2: Enum values MUST match Panel exactly**
- Panel: `IssueSeverity.Critical = 0`
- Python: `IssueSeverity.CRITICAL = 0`

**Rule 3: Date format is ISO 8601**
- Python: `datetime.now().isoformat()`
- Panel: `"2025-12-19T17:30:00.123456"`

**Rule 4: Every model needs to_json() and from_json()**
- `to_json()` → camelCase for Panel
- `from_json()` → Parse camelCase to snake_case

---

## 📋 Python Implementation Principles

### DO ✅
- Use dataclasses for models
- Use type hints everywhere (typing module)
- Use async/await for I/O operations
- Use pathlib.Path (not string paths)
- Use structlog for logging
- Write docstrings (Google style)
- Use pytest for testing
- Use black for formatting
- Use ruff for linting
- Keep single responsibility per class
- Panel JSON uyumluluğunu test et

### DON'T ❌
- Don't use `import *`
- Don't use mutable default arguments
- Don't ignore type hints
- Don't mix tabs and spaces
- Don't use global variables
- Don't create God classes
- Don't write functions >50 lines
- Don't guess Panel JSON format (kontrol et!)

---

## 🔌 Core Dependencies

### Required Libraries
- qdrant-client (vector DB)
- openai (embeddings)
- pydantic (validation)
- structlog (logging)
- click (CLI)
- aiofiles (async file ops)
- pyyaml (config)
- httpx (async HTTP)
- pytest (testing)
- black (formatting)
- ruff (linting)

---

## 📊 Migration Strategy

### Core Principles
1. **Panel-First**: Her feature'ı Panel types'tan başlat
2. **Iterative**: Büyük bang değil, küçük adımlar
3. **Flexible**: Mimari ihtiyaca göre şekillensin
4. **Tested**: Her adımda test yaz
5. **Documented**: Kararları dokümante et

### Genel Yaklaşım
1. Panel'den başla (TypeScript types)
2. Python model'leri oluştur (Panel uyumlu JSON)
3. Business logic'i implement et
4. Test yaz
5. CLI/API ekle
6. Iterate!

### Component'ler (Sıralı Değil!)
- Core Models (Panel uyumlu JSON serialize/deserialize)
- Issue System (temel veri yapısı)
- Pipeline Execution (orchestration)
- Validation Frames (test stratejileri)
- Memory System (Qdrant - opsiyonel)
- Analysis Engine (kod analizi)
- CLI (kullanıcı interface)

**NOT:** Yukarıdaki liste sadece component'leri gösterir. Implementasyon sırası ve mimari proje gidişatına göre belirlenir.

---

## ⚠️ CRITICAL WARNINGS

### 1. Panel is Source of Truth
```
Priority: Panel TypeScript Types > Python Best Practices > C# Implementation
```

### 2. Don't Copy C# Architecture
C# projesi eski ve bazı yapıları değişmesi gerekiyor:
- C#'deki klasör yapısını birebir taklit etme
- C#'deki interface/class hiyerarşisini kopyalama
- Sadece genel mantık ve prensipleri al
- Python'a özgü, modern bir mimari tasarla

### 3. Always Check Panel First
Her feature için:
1. Panel types dizinine bak
2. API_DESIGN.md oku
3. Session notes oku
4. C# sadece genel mantık için referans (specific implementation değil!)

### 4. JSON Compatibility is Critical
- Python internally: snake_case
- JSON to/from Panel: camelCase
- Test her model için JSON serialize/deserialize

### 5. Enum Values Must Match Exactly
Panel'deki enum değerleri değiştirilmemeli!

### 6. Keep Models Simple
Over-engineering yapma. Panel'de ne varsa onu implement et.

### 7. Architecture is Flexible
- Kesin mimari yok, ihtiyaca göre şekillenecek
- C#'teki "Analysis/Classification/Validation" klasör yapısı sadece bir örnek
- Python'da daha iyi bir yapı bulabilirsin
- Önemli olan: Panel uyumlu, test edilebilir, temiz kod

---

## 🎯 Quick Reference Commands

### Panel Feature Check
```bash
# Feature var mı?
grep -r "FeatureName" <WARDEN_PANEL_PATH>/src/lib/types/

# Latest implementation notes
cat <WARDEN_PANEL_PATH>/.session-notes*.md | grep -A 10 "FeatureName"
```

### C# Reference Check (Secondary)
```bash
# Sadece Panel'de bulamazsanız
find <WARDEN_CSHARP_PATH>/src -name "*FeatureName*"
```

---

## 📞 Support Resources

- Panel TypeScript Types: `<WARDEN_PANEL_PATH>/src/lib/types/`
- API Contracts: `<WARDEN_PANEL_PATH>/API_DESIGN.md`
- Latest Features: `<WARDEN_PANEL_PATH>/.session-notes*.md`
- C# Reference: `<WARDEN_CSHARP_PATH>/src/Warden.Core/`

---

## 🌿 Git Branching Strategy

### Branch Structure
```
prod     (production)    → Stable releases only
  ↑
staging  (pre-prod)      → Testing & QA
  ↑
dev      (development)   → Daily development (default)
  ↑
main     (integration)   → Integration branch
```

### Branch Purposes

**`dev` (Development)**
- Daily development work
- Feature branches merge here
- Unstable, rapid changes
- CI/CD runs tests

**`staging` (Pre-Production)**
- QA & testing environment
- Merge from `dev` when features complete
- Mimics production
- Integration testing

**`prod` (Production)**
- Production releases only
- Merge from `staging` after QA approval
- Tagged releases (v1.0.0, v1.1.0)
- Stable, zero breaking changes

**`main` (Integration)**
- Integration branch (optional)
- Can be used as hotfix base
- Or keep in sync with `dev`

### Workflow

```bash
# Daily development
git checkout dev
git pull origin dev
# ... code changes ...
git add .
git commit -m "feat: Add feature X"
git push origin dev

# Ready for testing
git checkout staging
git merge dev
git push origin staging
# ... QA tests ...

# Ready for production
git checkout prod
git merge staging
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin prod --tags
```

### Protection Rules (Recommended)

- `prod`: Require PR approval, no direct push
- `staging`: Require PR approval
- `dev`: Allow direct push (fast iteration)
- `main`: Optional protection

---

**Last Updated**: January 1, 2026
**Code Completion**: ~71% Complete
**Production Ready**: ~75-80% (as Core Framework)
**Current Branch**: dev (12 unpushed commits!)
**Next Priority**: Extension Documentation & v1.0 Release

---

## 📝 Session Log

### January 1, 2026 - Production Readiness Assessment
**Key Findings:**
- ✅ LLM Integration is REAL (not stubs) - Anthropic, Groq, DeepSeek working
- ✅ Core Framework approach: 75-80% production ready
- ✅ As extensible framework, ready for v1.0 with documentation
- ⚠️ As monolithic tool: only 55-60% (lacks multi-language)
- 📊 Code statistics: 50K lines, 3750 files, 70% test coverage

**Critical Insight:**
Warden Core should be positioned as an **extensible framework** where users can add their own AST providers and validation frames, not a monolithic tool. This changes production readiness from 55% to 75-80%.

### December 28, 2024 - Major Milestone Achieved! 🎉
**Unpushed Commits Discovered (12 commits):**
- ✅ FORTIFICATION Phase: 100% complete with LLM generator
- ✅ CLEANING Phase: 100% complete with pattern analyzer
- ✅ ANALYSIS Phase: 100% complete with LLM integration
- ✅ CLASSIFICATION Phase: 100% complete with LLM integration
- ✅ Pipeline Context: 100% complete, phases now connected
- ✅ Test examples added (vulnerable_code.py, test_warden_with_llm.py)
- ✅ Configuration updated for production (.warden/config.yaml, rules.yaml)
- ✅ CLI improvements and path utilities
- ⚠️ phase_orchestrator.py: 775 lines (needs splitting)

**Current State:**
- PRE-ANALYSIS: 100% complete with modular design
- ANALYSIS: 100% complete with LLM integration
- CLASSIFICATION: 100% complete with LLM integration
- VALIDATION: 90% working with all frames operational
- FORTIFICATION: 100% complete with LLM generator
- CLEANING: 100% complete with pattern analyzer
- Pipeline Context: 100% complete, phases connected

### December 27, 2024 - Status Update & Consolidation
**Completed:**
- ✅ Created comprehensive status document (WARDEN_COMPLETE_STATUS.md)
- ✅ Cleaned up redundant pipeline documents (3 files removed)
- ✅ Updated session-start.md with current status
- ✅ Pipeline analysis and comparison completed

### December 26-27, 2024 - Pipeline Development
**Achievements:**
- ✅ Modular PRE-ANALYSIS implementation (4 modules < 500 lines each)
- ✅ Thread-safe PipelineContext with memory management
- ✅ LLM validator for false positives
- ✅ Custom frames (env-security, demo-security)
- ✅ Azure OpenAI integration

**Issues Identified:**
- ⚠️ Phases work independently, need context sharing
- ⚠️ 3 files exceed 500 line limit
- ⚠️ Some async methods missing _async suffix

### December 19-21, 2024 - Initial Setup
**Foundation:**
- ✅ Project structure created
- ✅ Core rules and standards defined
- ✅ Panel-first approach established
- ✅ Basic validation frames implemented

---

## 🚀 Session Start Checklist

### STEP 1: Load Memory Context (FIRST!)
```bash
# Load previous session context
/mem-context
```
**⚠️ DO THIS FIRST!** Önceki session'ları hatırla, nerede kaldığını bil.

### STEP 2: Read Critical Files (MANDATORY)
```bash
# 1. Session start guide (migration strategy)
cat temp/session-start.md

# 2. Python coding rules (standards & best practices)
cat temp/warden_core_rules.md

# 3. Warden quick reference (core concepts - condensed version)
cat temp/warden_quick_reference.md
```

**WHY MANDATORY:**
- `session-start.md` → Migration strategy, Panel-first approach, critical paths, feature workflow
- `warden_core_rules.md` → Python standards, Panel JSON compatibility, security rules, type hints
- `warden_quick_reference.md` → Core concepts, validation strategies, architecture overview (condensed)

**⚠️ DO NOT SKIP:** These files contain critical rules that MUST be followed.

### STEP 3: Priority Tasks for Next Session

**🚨 URGENT - DO FIRST:**
1. [ ] PUSH ALL 12 COMMITS TO REMOTE! (git push origin dev)
2. [ ] Split phase_orchestrator.py (775 lines → <500 lines)

**🎯 v1.0 RELEASE PREPARATION (1-2 weeks):**
3. [ ] Write extension developer documentation
   - How to create custom AST providers
   - How to build validation frames
   - Plugin discovery system docs
4. [ ] Create example extensions (Java/JS AST providers)
5. [ ] Define API stability guarantee & versioning policy
6. [ ] Test framework with real-world Python projects

**✅ FRAMEWORK IMPROVEMENTS:**
7. [ ] Performance optimization (cache, memoization)
8. [ ] Production monitoring (metrics, telemetry)
9. [ ] Load testing with 100K+ LOC repos
10. [ ] Fix async method naming (_async suffix)

**📚 DOCUMENTATION & ECOSYSTEM:**
11. [ ] API reference documentation
12. [ ] Getting started guide
13. [ ] Migration guide from other tools
14. [ ] Plugin marketplace design

### STEP 4: During Session
- Use `/mem-save` after important decisions/completions
- Update session log in this file if major changes

### STEP 5: Session End
```bash
/mem-save "Warden Core: Session summary - Completed: X, Next: Y, Decisions: Z"
```
